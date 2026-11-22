from importlib.metadata import version

from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_documentation_and_application_metadata(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()

    assert schema["info"]["version"] == version("pulse-api")
    assert "/health/live" in schema["paths"]
