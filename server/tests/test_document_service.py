import hashlib
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.models import Document, Job, JobStatus
from api.services.documents import DocumentService
from api.storage import LocalFileStorage


@pytest.fixture
def session() -> MagicMock:
    session = MagicMock(spec=Session)
    session.in_transaction.return_value = False

    def flush_defaults() -> None:
        document, job = session.add_all.call_args.args[0]
        assert document.id is None and job.id is None
        document.id, job.id = uuid4(), uuid4()
        job.status, job.attempt_count = JobStatus.PENDING, 0

    session.flush.side_effect = flush_defaults
    return session


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "storage")


def test_read_document_bytes(session: MagicMock, storage: LocalFileStorage) -> None:
    content = bytes(range(256))
    stored = storage.save(content)
    document = Document(id=uuid4(), storage_key=stored.storage_key)
    session.get.return_value = document

    assert DocumentService(storage, session).read(document.id) == content
    session.get.assert_called_once_with(Document, document.id)


def test_read_missing_document(session: MagicMock, storage: LocalFileStorage) -> None:
    session.get.return_value = None
    with pytest.raises(ValueError, match="does not exist"):
        DocumentService(storage, session).read(uuid4())


def test_read_missing_file(session: MagicMock, storage: LocalFileStorage) -> None:
    stored = storage.save(b"removed")
    storage.delete(stored.storage_key)
    document = Document(id=uuid4(), storage_key=stored.storage_key)
    session.get.return_value = document

    with pytest.raises(FileNotFoundError):
        DocumentService(storage, session).read(document.id)


def test_registration_metadata_and_transaction(
    session: MagicMock, storage: LocalFileStorage
) -> None:
    content = bytes(range(256))
    result = DocumentService(storage, session).register(
        content,
        original_filename="../../original.json",
        content_type="application/json",
    )
    document, job = session.add_all.call_args.args[0]

    assert isinstance(document, Document) and isinstance(job, Job)
    assert job.document is document and document.jobs == [job]
    assert document.original_filename == "../../original.json"
    assert document.content_type == "application/json"
    assert document.file_size_bytes == len(content)
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert storage.read(document.storage_key) == content
    assert result.document_id == document.id
    assert result.job_id == job.id
    assert job.status == JobStatus.PENDING and job.attempt_count == 0
    session.flush.assert_called_once()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.refresh.assert_not_called()
    session.execute.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("failure", ["flush", "commit"])
def test_database_failure_rolls_back_and_removes_only_new_file(
    session: MagicMock, storage: LocalFileStorage, failure: str
) -> None:
    existing = storage.save(b"pre-existing")
    error = SQLAlchemyError("database failure")
    getattr(session, failure).side_effect = error

    with pytest.raises(SQLAlchemyError) as raised:
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )

    assert raised.value is error
    session.rollback.assert_called_once()
    document, _ = session.add_all.call_args.args[0]
    with pytest.raises(FileNotFoundError):
        storage.read(document.storage_key)
    assert storage.read(existing.storage_key) == b"pre-existing"


def test_compensation_succeeds_if_document_is_already_absent(
    session: MagicMock, storage: LocalFileStorage
) -> None:
    error = SQLAlchemyError("database failure")

    def fail_commit():
        document, _ = session.add_all.call_args.args[0]
        storage.delete(document.storage_key)
        raise error

    session.commit.side_effect = fail_commit
    with pytest.raises(SQLAlchemyError) as raised:
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )

    assert raised.value is error
    assert not getattr(error, "__notes__", [])


def test_cleanup_failure_preserves_database_error(
    session: MagicMock,
    storage: LocalFileStorage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = SQLAlchemyError("original database failure")
    session.commit.side_effect = error
    monkeypatch.setattr(
        storage, "delete", MagicMock(side_effect=OSError("cleanup failed"))
    )

    with pytest.raises(SQLAlchemyError) as raised:
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )

    assert raised.value is error
    session.rollback.assert_called_once()
    assert "cleanup failed" in caplog.text
    assert "Storage cleanup failed" in error.__notes__[0]
    document, _ = session.add_all.call_args.args[0]
    assert storage.read(document.storage_key) == b"new"
    LocalFileStorage.delete(storage, document.storage_key)


def test_rollback_failure_still_attempts_storage_cleanup(
    session: MagicMock, storage: LocalFileStorage
) -> None:
    error = SQLAlchemyError("original database failure")
    session.commit.side_effect = error
    session.rollback.side_effect = SQLAlchemyError("rollback failed")
    with pytest.raises(SQLAlchemyError) as raised:
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )
    assert raised.value is error
    document, _ = session.add_all.call_args.args[0]
    with pytest.raises(FileNotFoundError):
        storage.read(document.storage_key)


def test_storage_failure_does_not_touch_database(
    session: MagicMock, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "save", MagicMock(side_effect=OSError("save failed")))
    with pytest.raises(OSError, match="save failed"):
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )
    session.add_all.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_active_session_is_rejected_before_storage(
    session: MagicMock, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.in_transaction.return_value = True
    save = MagicMock()
    monkeypatch.setattr(storage, "save", save)
    with pytest.raises(ValueError, match="idle session"):
        DocumentService(storage, session).register(
            b"new", original_filename="new.txt", content_type="text/plain"
        )
    save.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_later_caller_error_does_not_delete_committed_content(
    session: MagicMock, storage: LocalFileStorage
) -> None:
    with pytest.raises(RuntimeError, match="response failed"):
        DocumentService(storage, session).register(
            b"committed", original_filename="new.txt", content_type="text/plain"
        )
        raise RuntimeError("response failed")
    document, _ = session.add_all.call_args.args[0]
    assert storage.read(document.storage_key) == b"committed"
    session.rollback.assert_not_called()
