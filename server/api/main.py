"""Application factory for the Pulse API."""

from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from api.api.documents import router as documents_router
from api.api.health import router as health_router
from api.api.jobs import router as jobs_router
from api.messaging.jobpublisher import JobPublisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    publisher = JobPublisher()
    app.state.publisher = publisher

    try:
        publisher.start()
        yield
    finally:
        publisher.stop()


def create_app() -> FastAPI:
    """Create a new application with its HTTP routers registered."""
    app = FastAPI(title="Pulse API", version=version("pulse-api"), lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(jobs_router)
    return app


app = FastAPI(lifespan=lifespan)
