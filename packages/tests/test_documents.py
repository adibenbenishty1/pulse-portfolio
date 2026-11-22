"""SDK document and job operations using HTTPX MockTransport only."""

from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from client import (
    DocumentResponse,
    DocumentUploadResponse,
    JobStatus,
    ProcessingJobResponse,
    PulseClient,
)


@pytest.mark.parametrize("as_string", [False, True])
def test_upload_sends_binary_multipart_with_original_filename(
    tmp_path: Path, upload_payload: dict[str, str], as_string: bool
) -> None:
    directory = tmp_path / "private-parent"
    directory.mkdir()
    path = directory / "quarterly invoice.pdf"
    content = b"%PDF opaque bytes\x00\xff\r\nnot invoice JSON"
    path.write_bytes(content)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: "
            + request.headers["Content-Type"].encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + request.content
        )
        assert message.get_content_type() == "multipart/form-data"
        parts = list(message.iter_parts())
        assert len(parts) == 1
        assert parts[0].get_param("name", header="Content-Disposition") == "file"
        assert parts[0].get_filename() == path.name
        assert parts[0].get_content_type() == "application/pdf"
        assert parts[0].get_payload(decode=True) == content
        assert str(directory).encode() not in request.content
        return httpx.Response(201, json=upload_payload)

    with PulseClient(
        base_url="http://pulse.example:9000", transport=httpx.MockTransport(respond)
    ) as client:
        result = client.upload_document(str(path) if as_string else path)

    assert isinstance(result, DocumentUploadResponse)
    assert result.document_id == UUID(upload_payload["document_id"])
    assert result.job_id == UUID(upload_payload["job_id"])
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://pulse.example:9000/documents"


@pytest.mark.parametrize("as_string", [False, True])
def test_get_document_parses_metadata(
    document_payload: dict[str, object], as_string: bool
) -> None:
    document_id = UUID(str(document_payload["id"]))

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"http://pulse.example:9000/documents/{document_id}"
        return httpx.Response(200, json=document_payload)

    with PulseClient(
        base_url="http://pulse.example:9000", transport=httpx.MockTransport(respond)
    ) as client:
        document = client.get_document(str(document_id) if as_string else document_id)

    assert isinstance(document, DocumentResponse)
    assert document.id == document_id
    assert document.original_filename == "invoice.pdf"
    assert document.content_type == "application/pdf"
    assert document.file_size_bytes == 123
    assert document.sha256 == "a" * 64
    assert document.created_at == datetime(2026, 10, 18, 9, tzinfo=UTC)
    assert document.model_dump(mode="json") == document_payload
    assert not hasattr(document, "storage_key")


@pytest.mark.parametrize("as_string", [False, True])
def test_get_job_parses_initial_status_and_null_fields(
    job_payload: dict[str, object], as_string: bool
) -> None:
    job_id = UUID(str(job_payload["id"]))

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"http://pulse.example:9000/jobs/{job_id}"
        return httpx.Response(200, json=job_payload)

    with PulseClient(
        base_url="http://pulse.example:9000", transport=httpx.MockTransport(respond)
    ) as client:
        job = client.get_job(str(job_id) if as_string else job_id)

    assert isinstance(job, ProcessingJobResponse)
    assert job.id == job_id
    assert job.document_id == UUID(str(job_payload["document_id"]))
    assert job.status is JobStatus.PENDING
    assert job.attempt_count == 0
    assert job.created_at == datetime(2026, 10, 18, 9, tzinfo=UTC)
    assert job.started_at is None
    assert job.completed_at is None
    assert job.error_message is None
    assert job.model_dump(mode="json") == job_payload


@pytest.mark.parametrize("job_status", list(JobStatus))
def test_get_job_preserves_status_timestamps_and_error(
    job_payload: dict[str, object], job_status: JobStatus
) -> None:
    job_payload.update(
        status=job_status.value,
        attempt_count=2,
        started_at="2026-10-18T11:00:01+02:00",
        completed_at="2026-10-18T11:00:02+02:00",
        error_message="Document processing failed"
        if job_status is JobStatus.FAILED
        else None,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=job_payload)
    )

    with PulseClient(transport=transport) as client:
        job = client.get_job(str(job_payload["id"]))

    assert job.status is job_status
    assert job.attempt_count == 2
    assert job.started_at == datetime(2026, 10, 18, 9, 0, 1, tzinfo=UTC)
    assert job.completed_at == datetime(2026, 10, 18, 9, 0, 2, tzinfo=UTC)
    assert job.started_at.utcoffset().total_seconds() == 7200
    assert job.error_message == job_payload["error_message"]


@pytest.mark.parametrize("method", ["get_document", "get_job"])
@pytest.mark.parametrize("status_code", [404, 422])
def test_read_http_errors_preserve_request_response_and_detail(
    method: str, status_code: int
) -> None:
    detail = "Resource not found" if status_code == 404 else [{"type": "uuid_parsing"}]
    resource_id = (
        "43852ac3-9554-4f67-b594-566cbaaa9d91" if status_code == 404 else "bad-uuid"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json={"detail": detail})
    )

    with PulseClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            getattr(client, method)(resource_id)

    assert error.value.response.status_code == status_code
    assert error.value.response.json() == {"detail": detail}
    assert error.value.request.method == "GET"
    assert error.value.request.url.path.endswith(f"/{resource_id}")


@pytest.mark.parametrize("status_code", [400, 413, 422])
def test_upload_http_validation_errors_are_preserved(
    tmp_path: Path, status_code: int
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")
    detail = "Upload rejected"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json={"detail": detail})
    )

    with PulseClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            client.upload_document(path)

    assert error.value.response.status_code == status_code
    assert error.value.response.json() == {"detail": detail}
    assert error.value.request.method == "POST"


@pytest.mark.parametrize("method", ["upload_document", "get_document", "get_job"])
def test_connection_failures_are_propagated(tmp_path: Path, method: str) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with PulseClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(httpx.ConnectError, match="Connection refused") as error:
            getattr(client, method)(path if method == "upload_document" else "bad-uuid")

    assert error.value.request is not None


@pytest.mark.parametrize("method", ["upload_document", "get_document", "get_job"])
@pytest.mark.parametrize("invalid_json", [False, True])
def test_invalid_response_content_is_rejected(
    tmp_path: Path, method: str, invalid_json: bool
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, content=b"not JSON")
            if invalid_json
            else httpx.Response(200, json={})
        )
    )

    with PulseClient(transport=transport) as client:
        with pytest.raises(ValueError if invalid_json else ValidationError):
            getattr(client, method)(path if method == "upload_document" else "bad-uuid")


@pytest.mark.parametrize(
    "field, value", [("id", "not-a-uuid"), ("created_at", "not-a-timestamp")]
)
def test_invalid_document_field_types_are_rejected(
    document_payload: dict[str, object], field: str, value: str
) -> None:
    document_payload[field] = value
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=document_payload)
    )

    with PulseClient(transport=transport) as client:
        with pytest.raises(ValidationError) as error:
            client.get_document(str(document_payload["id"]))

    assert error.value.errors()[0]["loc"] == (field,)


def test_unknown_job_status_is_rejected(job_payload: dict[str, object]) -> None:
    job_payload["status"] = "UNKNOWN"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=job_payload)
    )

    with PulseClient(transport=transport) as client:
        with pytest.raises(ValidationError) as error:
            client.get_job(str(job_payload["id"]))

    assert error.value.errors()[0]["loc"] == ("status",)


@pytest.mark.parametrize(
    "outcome",
    ["success", "http_error", "connection_error", "invalid_response", "file_error"],
)
def test_upload_reads_in_chunks_closes_file_and_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upload_payload: dict[str, str],
    outcome: str,
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"x" * (3 * 64 * 1024 + 1))
    opened = []
    read_sizes: list[int] = []
    original_open = Path.open
    requests: list[httpx.Request] = []

    def open_file(file_path: Path, mode: str = "r", **kwargs):
        assert mode == "rb"
        handle = original_open(file_path, mode, **kwargs)
        original_read = handle.read

        def read(size: int = -1) -> bytes:
            assert 0 < size <= 64 * 1024
            read_sizes.append(size)
            if outcome == "file_error":
                raise OSError("File read failed")
            return original_read(size)

        monkeypatch.setattr(handle, "read", read)
        opened.append(handle)
        return handle

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if outcome == "connection_error":
            raise httpx.ReadError("Response lost after upload", request=request)
        return httpx.Response(
            500 if outcome == "http_error" else 201,
            json={} if outcome == "invalid_response" else upload_payload,
        )

    monkeypatch.setattr(Path, "open", open_file)
    with PulseClient(transport=httpx.MockTransport(respond)) as client:
        if outcome == "success":
            client.upload_document(path)
        else:
            error = {
                "http_error": httpx.HTTPStatusError,
                "connection_error": httpx.ReadError,
                "invalid_response": ValidationError,
                "file_error": OSError,
            }[outcome]
            with pytest.raises(error):
                client.upload_document(path)

    assert len(opened) == 1
    assert opened[0].closed
    assert read_sizes
    if outcome != "file_error":
        assert len(read_sizes) >= 4
        assert len(requests) == 1
    else:
        assert requests == []


@pytest.mark.parametrize("is_directory", [False, True])
def test_invalid_upload_path_fails_before_sending_a_request(
    tmp_path: Path, is_directory: bool
) -> None:
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: requests.append(request))
    path = tmp_path if is_directory else tmp_path / "missing.pdf"

    with PulseClient(transport=transport) as client:
        with pytest.raises(IsADirectoryError if is_directory else FileNotFoundError):
            client.upload_document(path)

    assert requests == []
