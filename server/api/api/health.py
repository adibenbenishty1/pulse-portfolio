"""Health and metrics endpoints for the Pulse API."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Confirm that the API can handle an HTTP request."""
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Expose the current Prometheus metrics."""
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
