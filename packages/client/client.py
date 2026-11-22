"""HTTP client for the Pulse API."""

from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

import httpx

from client.models import (
    DocumentResponse,
    DocumentUploadResponse,
    ProcessingJobResponse,
)


class PulseClient:
    """Communicate with Pulse over HTTP; close the client after use."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, transport=transport)

    def health(self) -> dict[str, str]:
        """Return the API's status; propagate HTTPX errors on request failure."""
        response = self._client.get("/health/live")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            # The server returned invalid content; the caller's arguments are valid.
            raise ValueError("Health response must contain a string 'status'")
        return {"status": payload["status"]}

    def upload_document(self, path: Path | str) -> DocumentUploadResponse:
        """Upload a binary file once and return its document and job IDs."""
        path = Path(path)
        with path.open("rb") as content:
            response = self._client.post(
                "/documents", files={"file": (path.name, content)}
            )
        response.raise_for_status()
        return DocumentUploadResponse.model_validate(response.json())

    def get_document(self, document_id: UUID | str) -> DocumentResponse:
        """Return document metadata; propagate HTTP and response validation errors."""
        response = self._client.get(f"/documents/{document_id}")
        response.raise_for_status()
        return DocumentResponse.model_validate(response.json())

    def get_job(self, job_id: UUID | str) -> ProcessingJobResponse:
        """Return a processing job's persisted status and processing details."""
        response = self._client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        return ProcessingJobResponse.model_validate(response.json())

    def close(self) -> None:
        """Release the HTTP client's resources."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
