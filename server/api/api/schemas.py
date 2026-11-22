"""Pydantic response models for the HTTP API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.models import JobStatus


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    created_at: datetime


class ProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    status: JobStatus
    attempt_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
