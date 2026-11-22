"""Document upload and metadata endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from prometheus_client import Counter
from sqlalchemy.orm import Session

from api.api.schemas import DocumentResponse, DocumentUploadResponse
from api.api.utils import get_document_service, read_upload
from api.db.session import get_session
from api.models import Document
from api.services.documents import DocumentService

FILES_SAVED = Counter(
    "pulse_api_files_saved_total",
    "Files saved by the Pulse API.",
)
MESSAGES_PUBLISHED = Counter(
    "pulse_api_messages_published_total",
    "Messages published by the Pulse API.",
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
    responses={
        400: {"description": "Empty file or filename"},
        413: {"description": "File exceeds the configured upload limit"},
        500: {"description": "Document upload failed"},
    },
)
def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentUploadResponse:
    """Validate an upload and delegate registration to DocumentService."""
    if not file.filename or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nonempty filename is required",
        )
    try:
        content = read_upload(file)
        result = service.register(
            content,
            original_filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
        )
        FILES_SAVED.inc()
        future = request.app.state.publisher.publish(result.job_id)
        future.result(timeout=15)
        MESSAGES_PUBLISHED.inc()
        return DocumentUploadResponse(
            document_id=result.document_id, job_id=result.job_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Document upload failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed",
        ) from None


@router.get(
    "/{document_id}",
    status_code=status.HTTP_200_OK,
    response_model=DocumentResponse,
    responses={
        404: {"description": "Document not found"},
        500: {"description": "Document retrieval failed"},
    },
)
def get_document(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> DocumentResponse:
    """Return public document metadata without accessing stored bytes."""
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
            )
        return DocumentResponse.model_validate(document)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Document retrieval failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document retrieval failed",
        ) from None
