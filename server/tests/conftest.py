from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from alembic import command
from api.config import Config
from api.main import create_app
from api.messaging.jobpublisher import JobPublisher


@pytest.fixture(scope="session")
def config() -> Config:
    """Select the test environment and database on the shared configuration."""
    from api.config import config

    if config.ENV.lower() not in {"local", "dev", "development", "test", "testing"}:
        raise RuntimeError("Tests must not run against a production configuration")
    config.ENV = "test"
    config.DB_NAME = config.DB_TEST_NAME
    return config


@pytest.fixture
def publisher(monkeypatch) -> MagicMock:
    """Replace only the broker publisher; retain the real application lifespan."""
    publisher = MagicMock(spec=JobPublisher)

    def publish(job_id):
        result = Future()
        result.set_result(None)
        return result

    publisher.publish.side_effect = publish
    monkeypatch.setattr("api.main.JobPublisher", lambda: publisher)
    return publisher


@pytest.fixture
def client(publisher) -> Iterator[TestClient]:
    """Yield a fresh test client and close it after each test."""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def database_engine(config) -> Iterator[Engine]:
    """Migrate and connect to the database selected by the config fixture."""
    engine = create_engine(
        config.database_url,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        alembic_config = AlembicConfig(
            str(Path(__file__).resolve().parents[1] / "alembic.ini")
        )
        command.upgrade(alembic_config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def database(database_engine) -> Iterator[Session]:
    """Roll back each test's outer transaction when its connection closes."""
    with database_engine.connect() as connection:
        connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
