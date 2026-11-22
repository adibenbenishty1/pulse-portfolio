"""Processing job status endpoint."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.api.schemas import ProcessingJobResponse
from api.db.session import get_session
from api.models import Job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProcessingJobResponse,
    responses={
        404: {"description": "Job not found"},
        500: {"description": "Job retrieval failed"},
    },
)
def get_job(
    job_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> ProcessingJobResponse:
    """Return the persisted job status and nullable processing details."""
    try:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
            )
        return ProcessingJobResponse.model_validate(job)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Job retrieval failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Job retrieval failed",
        ) from None
