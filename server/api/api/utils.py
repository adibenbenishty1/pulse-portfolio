"""Upload reading and service dependencies for the HTTP API."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from api.config import config
from api.db.session import get_session
from api.services.documents import DocumentService
from api.storage import create_document_storage

logger = logging.getLogger(__name__)


def read_upload(file: UploadFile) -> bytes:
    """Read a nonempty payload without consuming more than the limit plus one byte."""
    limit = config.MAX_UPLOAD_BYTES
    content = bytearray()
    while chunk := file.file.read(min(64 * 1024, limit - len(content) + 1)):
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Uploaded file exceeds the maximum size",
            )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must not be empty",
        )
    return bytes(content)


def get_document_service(
    session: Annotated[Session, Depends(get_session)],
) -> DocumentService:
    """Build a service; get_session owns and closes its request session."""
    try:
        storage = create_document_storage(config)
        return DocumentService(storage=storage, session=session)
    except Exception:
        logger.exception("Document upload dependency initialization failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed",
        ) from None
