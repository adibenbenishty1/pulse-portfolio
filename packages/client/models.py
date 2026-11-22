"""SDK response models for Pulse's public HTTP contract."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class JobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID


class DocumentResponse(BaseModel):
    id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    created_at: datetime


class ProcessingJobResponse(BaseModel):
    id: UUID
    document_id: UUID
    status: JobStatus
    attempt_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
