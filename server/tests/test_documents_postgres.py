"""HTTP registration and reads with PostgreSQL isolation and temporary files."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.config import config
from api.db.session import get_session
from api.models import Document, Job, JobStatus
from api.storage import LocalFileStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def upload_client(
    database: Session,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(config, "STORAGE_ROOT", tmp_path / "uploads")
    connection = database.get_bind()

    def request_session() -> Iterator[Session]:
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session

    client.app.dependency_overrides[get_session] = request_session
    return client


def test_upload_and_read_document_metadata_and_pending_job(
    upload_client: TestClient, database: Session
) -> None:
    content = b"opaque upload bytes\x00\xff; invoice JSON is not parsed"
    filename = f"../../{uuid4()}.json"
    response = upload_client.post(
        "/documents", files={"file": (filename, content, "application/json")}
    )
    assert response.status_code == 201
    result = response.json()
    document = database.get(Document, UUID(result["document_id"]))
    job = database.get(Job, UUID(result["job_id"]))
    assert document is not None and job is not None
    assert document.original_filename == filename
    assert document.content_type == "application/json"
    assert document.file_size_bytes == len(content)
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert job.document_id == document.id
    upload_client.app.state.publisher.publish.assert_called_once_with(job.id)
    assert job.status == JobStatus.PENDING
    assert job.attempt_count == 0
    assert document.jobs == [job]
    storage = LocalFileStorage(config.STORAGE_ROOT)
    assert storage.read(document.storage_key) == content
    assert UUID(Path(document.storage_key).stem).version == 4
    assert not (config.STORAGE_ROOT.parent.parent / Path(filename).name).exists()
    assert len(list((config.STORAGE_ROOT / "documents").iterdir())) == 1

    # Metadata reads must also work when the document's bytes are unavailable.
    storage.delete(document.storage_key)
    document_response = upload_client.get(f"/documents/{document.id}")
    assert document_response.status_code == 200
    metadata = document_response.json()
    created_at = metadata.pop("created_at")
    assert datetime.fromisoformat(created_at) == document.created_at
    assert metadata == {
        "id": str(document.id),
        "original_filename": filename,
        "content_type": "application/json",
        "file_size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    job_response = upload_client.get(f"/jobs/{job.id}")
    assert job_response.status_code == 200
    job_metadata = job_response.json()
    created_at = job_metadata.pop("created_at")
    assert datetime.fromisoformat(created_at) == job.created_at
    assert job_metadata == {
        "id": str(job.id),
        "document_id": str(document.id),
        "status": "PENDING",
        "attempt_count": 0,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }


@pytest.mark.parametrize(
    "job_status", [JobStatus.PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED]
)
def test_get_job_returns_persisted_processing_details(
    upload_client: TestClient, database: Session, job_status: JobStatus
) -> None:
    created_at = datetime(2026, 10, 18, 9, tzinfo=UTC)
    document = Document(
        original_filename="invoice.pdf",
        storage_key=f"documents/{uuid4()}.bin",
        content_type="application/pdf",
        file_size_bytes=123,
        sha256="a" * 64,
    )
    job = Job(
        document=document,
        status=job_status,
        attempt_count=2,
        created_at=created_at,
        started_at=created_at + timedelta(seconds=1),
        completed_at=(
            None
            if job_status == JobStatus.PROCESSING
            else created_at + timedelta(seconds=2)
        ),
        error_message="Document processing failed"
        if job_status == JobStatus.FAILED
        else None,
    )
    database.add(job)
    database.flush()

    response = upload_client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(job.id)
    assert payload["document_id"] == str(document.id)
    assert payload["status"] == job_status.value
    assert payload["attempt_count"] == 2
    assert datetime.fromisoformat(payload["created_at"]) == created_at
    assert datetime.fromisoformat(payload["started_at"]) == job.started_at
    if job.completed_at is None:
        assert payload["completed_at"] is None
    else:
        assert datetime.fromisoformat(payload["completed_at"]) == job.completed_at
    assert payload["error_message"] == job.error_message


@pytest.mark.parametrize("resource", ["documents", "jobs"])
def test_missing_persisted_resource_returns_not_found(
    upload_client: TestClient, resource: str
) -> None:
    response = upload_client.get(f"/{resource}/{uuid4()}")

    assert response.status_code == 404
    assert not config.STORAGE_ROOT.exists()


def test_persistence_failure_rolls_back_rows_and_removes_only_new_file(
    upload_client: TestClient, database: Session
) -> None:
    storage = LocalFileStorage(config.STORAGE_ROOT)
    existing = storage.save(b"unrelated stored document")
    filename = f"{uuid4()}.txt"
    connection = database.get_bind()
    jobs_before = database.scalar(select(func.count()).select_from(Job))

    def fail_job_insert(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO PROCESSING_JOBS"):
            raise SQLAlchemyError("postgresql://user:secret@private-host/pulse")

    event.listen(connection, "before_cursor_execute", fail_job_insert)
    try:
        response = upload_client.post(
            "/documents", files={"file": (filename, b"new upload", "text/plain")}
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_job_insert)

    upload_client.app.state.publisher.publish.assert_not_called()
    assert response.status_code == 500
    assert response.json() == {"detail": "Document upload failed"}
    assert (
        database.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.original_filename == filename)
        )
        == 0
    )
    assert database.scalar(select(func.count()).select_from(Job)) == jobs_before
    assert storage.read(existing.storage_key) == b"unrelated stored document"
    assert list((config.STORAGE_ROOT / "documents").iterdir()) == [
        config.STORAGE_ROOT / existing.storage_key
    ]
