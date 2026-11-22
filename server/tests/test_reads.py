"""Document and job read contracts and request cleanup without PostgreSQL."""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.db import session as database
from api.db.session import get_session
from api.models import Document, Job, JobStatus


@pytest.fixture
def document() -> Document:
    return Document(
        id=uuid4(),
        original_filename="invoice.pdf",
        storage_key=f"documents/{uuid4()}.bin",
        content_type="application/pdf",
        file_size_bytes=123,
        sha256="a" * 64,
        created_at=datetime(2026, 10, 18, 9, tzinfo=UTC),
    )


@pytest.fixture
def job(document: Document) -> Job:
    return Job(
        id=uuid4(),
        document_id=document.id,
        status=JobStatus.PENDING,
        attempt_count=0,
        created_at=document.created_at,
        started_at=None,
        completed_at=None,
        error_message=None,
    )


@pytest.fixture
def read_session(client: TestClient) -> MagicMock:
    session = MagicMock(spec=Session)
    client.app.dependency_overrides[get_session] = lambda: session
    return session


def test_get_document_returns_only_public_metadata(
    client: TestClient, read_session: MagicMock, document: Document
) -> None:
    read_session.get.return_value = document

    response = client.get(f"/documents/{document.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "id",
        "original_filename",
        "content_type",
        "file_size_bytes",
        "sha256",
        "created_at",
    }
    assert UUID(payload["id"]) == document.id
    assert payload["original_filename"] == document.original_filename
    assert payload["content_type"] == document.content_type
    assert type(payload["file_size_bytes"]) is int
    assert payload["file_size_bytes"] == document.file_size_bytes
    assert payload["sha256"] == document.sha256
    assert datetime.fromisoformat(payload["created_at"]) == document.created_at
    assert document.storage_key not in response.text
    read_session.get.assert_called_once_with(Document, document.id)


def test_get_job_returns_pending_status_and_explicit_null_fields(
    client: TestClient, read_session: MagicMock, job: Job
) -> None:
    read_session.get.return_value = job

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "id",
        "document_id",
        "status",
        "attempt_count",
        "created_at",
        "started_at",
        "completed_at",
        "error_message",
    }
    assert UUID(payload["id"]) == job.id
    assert UUID(payload["document_id"]) == job.document_id
    assert payload["status"] == "PENDING"
    assert type(payload["attempt_count"]) is int
    assert payload["attempt_count"] == 0
    assert datetime.fromisoformat(payload["created_at"]) == job.created_at
    assert payload["started_at"] is None
    assert payload["completed_at"] is None
    assert payload["error_message"] is None
    read_session.get.assert_called_once_with(Job, job.id)


@pytest.mark.parametrize("job_status", list(JobStatus))
def test_job_status_serializes_as_its_string_value(
    client: TestClient,
    read_session: MagicMock,
    job: Job,
    job_status: JobStatus,
) -> None:
    job.status = job_status
    read_session.get.return_value = job

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == job_status.value


def test_get_job_preserves_processing_details(
    client: TestClient, read_session: MagicMock, job: Job
) -> None:
    job.status = JobStatus.FAILED
    job.attempt_count = 2
    job.started_at = job.created_at + timedelta(seconds=1)
    job.completed_at = job.created_at + timedelta(seconds=2)
    job.error_message = "Document processing failed"
    read_session.get.return_value = job

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["attempt_count"] == 2
    assert datetime.fromisoformat(payload["started_at"]) == job.started_at
    assert datetime.fromisoformat(payload["completed_at"]) == job.completed_at
    assert payload["error_message"] == job.error_message


@pytest.mark.parametrize(
    "resource, model, message",
    [
        ("documents", Document, "Document not found"),
        ("jobs", Job, "Job not found"),
    ],
)
def test_missing_resource_returns_not_found(
    client: TestClient,
    read_session: MagicMock,
    resource: str,
    model: type[Document] | type[Job],
    message: str,
) -> None:
    resource_id = uuid4()
    read_session.get.return_value = None

    response = client.get(f"/{resource}/{resource_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": message}
    read_session.get.assert_called_once_with(model, resource_id)


@pytest.mark.parametrize("resource", ["documents", "jobs"])
@pytest.mark.parametrize("resource_id", ["not-a-uuid", "1234"])
def test_invalid_uuid_is_rejected_without_querying(
    client: TestClient,
    read_session: MagicMock,
    resource: str,
    resource_id: str,
) -> None:
    response = client.get(f"/{resource}/{resource_id}")

    assert response.status_code == 422
    read_session.get.assert_not_called()


@pytest.mark.parametrize(
    "resource, logger, message",
    [
        ("documents", "api.api.documents", "Document retrieval failed"),
        ("jobs", "api.api.jobs", "Job retrieval failed"),
    ],
)
def test_database_failure_is_logged_and_returns_a_generic_error(
    client: TestClient,
    read_session: MagicMock,
    caplog: pytest.LogCaptureFixture,
    resource: str,
    logger: str,
    message: str,
) -> None:
    error = SQLAlchemyError(
        "postgresql://user:secret-password@private-host/pulse /private/storage"
    )
    read_session.get.side_effect = error

    with caplog.at_level(logging.ERROR, logger=logger):
        response = client.get(f"/{resource}/{uuid4()}")

    assert response.status_code == 500
    assert response.json() == {"detail": message}
    assert str(error) not in response.text
    assert any(record.name == logger and record.exc_info for record in caplog.records)


@pytest.mark.parametrize("resource", ["documents", "jobs"])
@pytest.mark.parametrize("outcome", ["found", "missing", "error", "invalid"])
def test_read_dependency_closes_session_without_committing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    document: Document,
    job: Job,
    resource: str,
    outcome: str,
) -> None:
    session = Session()
    close = MagicMock(wraps=session.close)
    commit = MagicMock(wraps=session.commit)
    get = MagicMock(return_value=document if resource == "documents" else job)
    session_factory = MagicMock(return_value=session)
    monkeypatch.setattr(session, "close", close)
    monkeypatch.setattr(session, "commit", commit)
    monkeypatch.setattr(session, "get", get)
    monkeypatch.setattr(database, "SessionFactory", session_factory)
    resource_id = str(uuid4())
    expected_status = 200
    if outcome == "missing":
        get.return_value = None
        expected_status = 404
    elif outcome == "error":
        get.side_effect = SQLAlchemyError("simulated query failure")
        expected_status = 500
    elif outcome == "invalid":
        resource_id = "not-a-uuid"
        expected_status = 422

    response = client.get(f"/{resource}/{resource_id}")

    assert response.status_code == expected_status
    session_factory.assert_called_once_with()
    close.assert_called_once_with()
    commit.assert_not_called()
    assert not session.in_transaction()
    if outcome == "invalid":
        get.assert_not_called()


def test_read_openapi_uses_uuid_paths_and_typed_responses(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path, model in [
        ("/documents/{document_id}", "DocumentResponse"),
        ("/jobs/{job_id}", "ProcessingJobResponse"),
    ]:
        operation = schema["paths"][path]["get"]
        parameter = operation["parameters"][0]
        assert parameter["in"] == "path"
        assert parameter["schema"]["format"] == "uuid"
        assert operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == {"$ref": f"#/components/schemas/{model}"}
        assert "404" in operation["responses"]
        assert "422" in operation["responses"]
    models = schema["components"]["schemas"]
    assert "storage_key" not in models["DocumentResponse"]["properties"]
    assert models["DocumentResponse"]["properties"]["created_at"]["format"] == (
        "date-time"
    )
    assert models["JobStatus"]["enum"] == [status.value for status in JobStatus]
