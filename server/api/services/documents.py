"""Document registration with a shared database transaction and file compensation."""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from api.models import Document, Job
from api.storage import DocumentStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentRegistration:
    document_id: UUID
    job_id: UUID


class DocumentService:
    """Register documents using an idle session that the caller owns and closes.

    Each register call owns its transaction and commits both records together.
    Do not share the session concurrently or pass a session with unrelated work.
    """

    def __init__(self, storage: DocumentStorage, session: Session) -> None:
        self._storage = storage
        self._session = session

    def read(self, document_id: UUID) -> bytes:
        """Read the stored bytes for an existing document."""
        document = self._session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} does not exist")
        return self._storage.read(document.storage_key)

    def register(
        self, content: bytes, *, original_filename: str, content_type: str
    ) -> DocumentRegistration:
        if self._session.in_transaction():
            raise ValueError("Document registration requires an idle session")

        # A successful save must return a newly created, exclusively owned key.
        # Storage failures must not commit or disturb the database session.
        stored = self._storage.save(content)
        try:
            document = Document(
                original_filename=original_filename,
                storage_key=stored.storage_key,
                content_type=content_type,
                file_size_bytes=stored.size_bytes,
                sha256=stored.sha256,
            )
            job = Job(document=document)
            self._session.add_all([document, job])
            self._session.flush()
            # Defaults generate IDs during flush. Capture them before commit
            # expires the ORM objects, avoiding any post-commit database query.
            result = DocumentRegistration(document_id=document.id, job_id=job.id)
            self._session.commit()
        except Exception as error:
            try:
                self._session.rollback()
            except Exception:
                error.add_note("Database rollback also failed; see application logs")
                logger.exception("Document registration rollback failed")
            try:
                self._storage.delete(stored.storage_key)
            except Exception:
                error.add_note(
                    f"Storage cleanup failed for {stored.storage_key}; see application logs"
                )
                logger.exception(
                    "Document registration cleanup failed for key %s",
                    stored.storage_key,
                )
            raise

        # Nothing after a successful commit belongs in the compensation block.
        return result
