"""Public HTTP response examples shared by SDK and CLI tests."""

import pytest


@pytest.fixture
def upload_payload() -> dict[str, str]:
    return {
        "document_id": "43852ac3-9554-4f67-b594-566cbaaa9d91",
        "job_id": "1bc3e37c-009b-4b0d-85f1-331188958afe",
    }


@pytest.fixture
def document_payload(upload_payload: dict[str, str]) -> dict[str, object]:
    return {
        "id": upload_payload["document_id"],
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "file_size_bytes": 123,
        "sha256": "a" * 64,
        "created_at": "2026-10-18T09:00:00Z",
    }


@pytest.fixture
def job_payload(upload_payload: dict[str, str]) -> dict[str, object]:
    return {
        "id": upload_payload["job_id"],
        "document_id": upload_payload["document_id"],
        "status": "PENDING",
        "attempt_count": 0,
        "created_at": "2026-10-18T09:00:00Z",
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
