"""Committed registrations in the test database; cleanup only each test's keys."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from api.models import Document, Job, JobStatus
from api.services.documents import DocumentService
from api.storage import LocalFileStorage, StoredDocument

pytestmark = pytest.mark.integration


class TrackingStorage(LocalFileStorage):
    """Remember test-created keys, including files removed by compensation."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.keys: list[str] = []

    def save(self, content: bytes) -> StoredDocument:
        stored = super().save(content)
        self.keys.append(stored.storage_key)
        return stored


@pytest.fixture
def storage(database_engine: Engine, tmp_path: Path) -> Iterator[TrackingStorage]:
    storage = TrackingStorage(tmp_path / "storage")
    try:
        yield storage
    finally:
        # These tests intentionally commit, so remove only their generated keys.
        with Session(database_engine) as cleanup, cleanup.begin():
            ids = select(Document.id).where(Document.storage_key.in_(storage.keys))
            cleanup.execute(delete(Job).where(Job.document_id.in_(ids)))
            cleanup.execute(
                delete(Document).where(Document.storage_key.in_(storage.keys))
            )
        for key in storage.keys:
            try:
                LocalFileStorage.delete(storage, key)
            except FileNotFoundError:
                pass


def test_registration_is_visible_from_another_session(
    database_engine: Engine, storage: TrackingStorage
) -> None:
    content = b"Pulse checkpoint 4 integration document\n"
    with Session(database_engine) as session:
        result = DocumentService(storage, session).register(
            content,
            original_filename="checkpoint-4-integration.txt",
            content_type="text/plain",
        )
    with Session(database_engine) as verify:
        document = verify.get(Document, result.document_id)
        job = verify.get(Job, result.job_id)
        assert document is not None and job is not None
        assert job.document_id == document.id and document.jobs == [job]
        assert job.status == JobStatus.PENDING and job.attempt_count == 0
        assert document.original_filename == "checkpoint-4-integration.txt"
        assert document.content_type == "text/plain"
        assert document.file_size_bytes == len(content)
        assert document.sha256 == hashlib.sha256(content).hexdigest()
        assert storage.read(document.storage_key) == content


def test_identical_registrations_create_distinct_records(
    database_engine: Engine, storage: TrackingStorage
) -> None:
    with Session(database_engine) as session:
        service = DocumentService(storage, session)
        first = service.register(
            b"same", original_filename="same.txt", content_type="text/plain"
        )
        second = service.register(
            b"same", original_filename="same.txt", content_type="text/plain"
        )
    assert first.document_id != second.document_id
    assert first.job_id != second.job_id
    assert len(set(storage.keys)) == 2
    with Session(database_engine) as verify:
        documents = verify.scalars(
            select(Document).where(Document.storage_key.in_(storage.keys))
        ).all()
        assert len(documents) == 2
        assert documents[0].sha256 == documents[1].sha256


def test_failed_job_insert_rolls_back_document_and_cleans_file(
    database_engine: Engine, storage: TrackingStorage
) -> None:
    documents: list[Document] = []

    def invalid_job(session: Session, flush_context: object, instances: object) -> None:
        for model in session.new:
            if isinstance(model, Job):
                model.attempt_count = -1
            elif isinstance(model, Document):
                documents.append(model)

    with Session(database_engine) as session:
        event.listen(session, "before_flush", invalid_job)
        with pytest.raises(IntegrityError):
            DocumentService(storage, session).register(
                b"rollback", original_filename="rollback.txt", content_type="text/plain"
            )
        assert not session.in_transaction()
    with Session(database_engine) as verify:
        assert verify.get(Document, documents[0].id) is None
        assert (
            verify.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.document_id == documents[0].id)
            )
            == 0
        )
    with pytest.raises(FileNotFoundError):
        storage.read(storage.keys[0])


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_commit_failure_rolls_back_both_records(
    database_engine: Engine,
    storage: TrackingStorage,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_fails: bool,
) -> None:
    error = SQLAlchemyError("simulated pre-commit failure")
    if cleanup_fails:
        monkeypatch.setattr(
            storage, "delete", MagicMock(side_effect=OSError("cleanup failed"))
        )
    with Session(database_engine) as session:
        monkeypatch.setattr(session, "commit", MagicMock(side_effect=error))
        with pytest.raises(SQLAlchemyError) as raised:
            DocumentService(storage, session).register(
                b"rollback", original_filename="rollback.txt", content_type="text/plain"
            )
        assert raised.value is error
        assert not session.in_transaction()
    with Session(database_engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.storage_key == storage.keys[0])
            )
            == 0
        )
    if cleanup_fails:
        assert storage.read(storage.keys[0]) == b"rollback"
        assert "Storage cleanup failed" in error.__notes__[0]
    else:
        with pytest.raises(FileNotFoundError):
            storage.read(storage.keys[0])
