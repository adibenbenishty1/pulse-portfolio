"""HTTP upload validation and dependency wiring without PostgreSQL."""

import logging
from pathlib import Path
from tempfile import SpooledTemporaryFile
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette import formparsers

from api.api import utils
from api.api.utils import get_document_service
from api.config import config
from api.db import session as database
from api.services.documents import DocumentRegistration, DocumentService
from api.storage import LocalFileStorage


@pytest.fixture
def service(client: TestClient) -> MagicMock:
    service = MagicMock(spec=DocumentService)
    service.register.return_value = DocumentRegistration(uuid4(), uuid4())
    client.app.dependency_overrides[get_document_service] = lambda: service
    return service


def test_upload_returns_created_ids_and_calls_service(
    client: TestClient, service: MagicMock, publisher: MagicMock
) -> None:
    content = b"opaque bytes, not valid invoice JSON\x00"
    response = client.post(
        "/documents", files={"file": ("invoice.json", content, "application/json")}
    )

    assert response.status_code == 201
    result = service.register.return_value
    assert response.json() == {
        "document_id": str(result.document_id),
        "job_id": str(result.job_id),
    }
    service.register.assert_called_once_with(
        content, original_filename="invoice.json", content_type="application/json"
    )
    publisher.publish.assert_called_once_with(result.job_id)


def test_upload_openapi_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    upload = schema["paths"]["/documents"]["post"]
    assert "multipart/form-data" in upload["requestBody"]["content"]
    assert "201" in upload["responses"]
    properties = schema["components"]["schemas"]["DocumentUploadResponse"]["properties"]
    assert properties["document_id"]["format"] == "uuid"
    assert properties["job_id"]["format"] == "uuid"


def test_empty_file_is_rejected(client: TestClient, service: MagicMock) -> None:
    response = client.post(
        "/documents", files={"file": ("empty.txt", b"", "text/plain")}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Uploaded file must not be empty"}
    service.register.assert_not_called()
    client.app.state.publisher.publish.assert_not_called()


@pytest.mark.parametrize("filename", ["", "   "])
def test_filename_is_required(
    client: TestClient, service: MagicMock, filename: str
) -> None:
    # An explicit empty filename remains an UploadFile rather than a text field.
    body = (
        '--upload\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'
        "content\r\n--upload--\r\n"
    ).encode()
    response = client.post(
        "/documents",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=upload"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "A nonempty filename is required"}
    service.register.assert_not_called()
    client.app.state.publisher.publish.assert_not_called()


@pytest.mark.parametrize("data", [{}, {"file": "not a file upload"}])
def test_file_field_is_required(
    client: TestClient, service: MagicMock, data: dict[str, str]
) -> None:
    response = client.post("/documents", data=data)
    assert response.status_code == 422
    service.register.assert_not_called()
    client.app.state.publisher.publish.assert_not_called()


def test_missing_content_type_uses_binary_default(
    client: TestClient, service: MagicMock
) -> None:
    response = client.post(
        "/documents",
        content=(
            b'--upload\r\nContent-Disposition: form-data; name="file"; '
            b'filename="upload.bin"\r\n\r\ncontent\r\n--upload--\r\n'
        ),
        headers={"Content-Type": "multipart/form-data; boundary=upload"},
    )
    assert response.status_code == 201
    service.register.assert_called_once_with(
        b"content",
        original_filename="upload.bin",
        content_type="application/octet-stream",
    )


@pytest.mark.parametrize(
    "limit, size, expected_status",
    [
        (5, 1, 201),
        (5, 5, 201),
        (5, 6, 413),
        (5 * 1024 * 1024, 2 * 1024 * 1024, 201),
        (5 * 1024 * 1024, 5 * 1024 * 1024 + 1, 413),
    ],
)
def test_configured_size_limit(
    client: TestClient,
    service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    size: int,
    expected_status: int,
) -> None:
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", limit)
    response = client.post("/documents", files={"file": ("upload.bin", b"x" * size)})
    assert response.status_code == expected_status
    if expected_status == 413:
        service.register.assert_not_called()
        client.app.state.publisher.publish.assert_not_called()
    else:
        service.register.assert_called_once()


def test_oversized_upload_stops_reading_at_limit_plus_one(
    client: TestClient, service: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = 64 * 1024 + 3
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", limit)
    uploaded = SpooledTemporaryFile(max_size=1024 * 1024)
    original_read = uploaded.read
    read_sizes: list[int] = []
    bytes_read = 0

    def read(size: int = -1) -> bytes:
        nonlocal bytes_read
        read_sizes.append(size)
        content = original_read(size)
        bytes_read += len(content)
        return content

    monkeypatch.setattr(uploaded, "read", read)
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", lambda **kwargs: uploaded)
    response = client.post(
        "/documents", files={"file": ("large.bin", b"x" * (limit * 3))}
    )
    assert response.status_code == 413
    assert bytes_read == limit + 1
    assert all(0 < size <= limit + 1 for size in read_sizes)
    assert uploaded.closed
    service.register.assert_not_called()
    client.app.state.publisher.publish.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        SQLAlchemyError("postgresql://user:secret-password@private-host/pulse"),
        OSError("/private/storage/internal-document.bin"),
        RuntimeError("unexpected internal detail"),
    ],
    ids=["persistence", "storage", "unexpected"],
)
def test_unexpected_failure_is_logged_and_returns_generic_error(
    client: TestClient,
    service: MagicMock,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    service.register.side_effect = error
    with caplog.at_level(logging.ERROR, logger="api.api.documents"):
        response = client.post(
            "/documents", files={"file": ("upload.txt", b"content", "text/plain")}
        )
    assert response.status_code == 500
    assert response.json() == {"detail": "Document upload failed"}
    assert str(error) not in response.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize(
    "content, limit, fails, expected_status",
    [
        (b"content", 1024, False, 201),
        (b"content", 1024, True, 500),
        (b"", 1024, False, 400),
        (b"content", 1, False, 413),
    ],
)
def test_dependency_wiring_closes_request_session(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    limit: int,
    fails: bool,
    expected_status: int,
) -> None:
    session = Session()
    close = MagicMock(wraps=session.close)
    monkeypatch.setattr(session, "close", close)
    session_factory = MagicMock(return_value=session)
    storage = MagicMock(spec=LocalFileStorage)
    storage_factory = MagicMock(return_value=storage)
    service = MagicMock(spec=DocumentService)
    service.register.return_value = DocumentRegistration(uuid4(), uuid4())
    if fails:
        service.register.side_effect = SQLAlchemyError("simulated persistence failure")
    service_factory = MagicMock(return_value=service)
    monkeypatch.setattr(database, "SessionFactory", session_factory)
    monkeypatch.setattr(utils, "create_document_storage", storage_factory)
    monkeypatch.setattr(utils, "DocumentService", service_factory)
    monkeypatch.setattr(config, "STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", limit)

    response = client.post("/documents", files={"file": ("upload.txt", content)})

    assert response.status_code == expected_status
    session_factory.assert_called_once_with()
    storage_factory.assert_called_once_with(config)
    service_factory.assert_called_once_with(storage=storage, session=session)
    close.assert_called_once_with()
    assert not session.in_transaction()
    if expected_status in {400, 413}:
        service.register.assert_not_called()
        client.app.state.publisher.publish.assert_not_called()


def test_storage_initialization_failure_is_safe_and_closes_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = Session()
    close = MagicMock(wraps=session.close)
    monkeypatch.setattr(session, "close", close)
    monkeypatch.setattr(database, "SessionFactory", MagicMock(return_value=session))
    monkeypatch.setattr(
        utils,
        "create_document_storage",
        MagicMock(side_effect=OSError("/private/storage could not be opened")),
    )
    with caplog.at_level(logging.ERROR, logger="api.api.utils"):
        response = client.post("/documents", files={"file": ("upload.txt", b"content")})
    assert response.status_code == 500
    assert response.json() == {"detail": "Document upload failed"}
    assert "/private/storage" not in response.text
    assert any(record.exc_info for record in caplog.records)
    close.assert_called_once_with()


@pytest.mark.parametrize("failure", ["publish", "confirmation", "timeout"])
def test_upload_publish_failure_returns_generic_error(
    client, service, publisher, failure
):
    from concurrent.futures import Future

    error = RuntimeError("private broker details")
    if failure == "publish":
        publisher.publish.side_effect = error
    else:
        future = Future()
        future.set_exception(
            TimeoutError("private broker details") if failure == "timeout" else error
        )
        publisher.publish.side_effect = None
        publisher.publish.return_value = future

    response = client.post("/documents", files={"file": ("upload.txt", b"content")})

    assert response.status_code == 500
    assert response.json() == {"detail": "Document upload failed"}
    publisher.publish.assert_called_once_with(service.register.return_value.job_id)


def test_upload_waits_for_publish_confirmation(client, service, publisher):
    future = MagicMock()
    publisher.publish.side_effect = None
    publisher.publish.return_value = future

    response = client.post("/documents", files={"file": ("upload.txt", b"content")})

    assert response.status_code == 201
    publisher.publish.assert_called_once_with(service.register.return_value.job_id)
    future.result.assert_called_once_with(timeout=15)
