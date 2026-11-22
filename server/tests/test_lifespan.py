"""Application ownership of the RabbitMQ publisher."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


def test_lifespan_starts_exposes_and_stops_publisher(publisher):
    app = create_app()
    publisher.start.assert_not_called()
    with TestClient(app) as client:
        assert client.app.state.publisher is publisher
        publisher.start.assert_called_once_with()
        publisher.stop.assert_not_called()
        assert client.get("/health/live").status_code == 200
    publisher.stop.assert_called_once_with()


def test_failed_startup_stops_publisher(publisher):
    publisher.start.side_effect = RuntimeError("broker unavailable")
    with pytest.raises(RuntimeError, match="broker unavailable"):
        with TestClient(create_app()):
            pytest.fail("Application must not accept requests after startup failure")
    publisher.stop.assert_called_once_with()


def test_lifespan_stops_publisher_when_application_raises(publisher):
    with pytest.raises(RuntimeError, match="application failed"):
        with TestClient(create_app()):
            raise RuntimeError("application failed")
    publisher.stop.assert_called_once_with()
