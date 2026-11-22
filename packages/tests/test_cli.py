import json
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from click.testing import CliRunner

from client import PulseClient
from client.cli import cli


def test_version_command() -> None:
    result = CliRunner().invoke(cli, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == version("pulse-client")


@pytest.mark.parametrize(
    ("args", "env", "expected_url"),
    [
        (["health"], {"PULSE_BASE_URL": ""}, "http://localhost:8000"),
        (["health"], {"PULSE_BASE_URL": "http://env.example"}, "http://env.example"),
        (
            ["--base-url", "http://option.example", "health"],
            {"PULSE_BASE_URL": "http://env.example"},
            "http://option.example",
        ),
    ],
)
def test_health_command(
    args: list[str], env: dict[str, str], expected_url: str
) -> None:
    with patch("client.cli.PulseClient") as client_class:
        client = client_class.return_value.__enter__.return_value
        client.health.return_value = {"status": "ok"}
        result = CliRunner().invoke(cli, args, env=env)

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "ok"}
    client_class.assert_called_once_with(base_url=expected_url)
    client.health.assert_called_once_with()
    client_class.return_value.__exit__.assert_called_once()


def test_health_command_reports_request_error() -> None:
    with patch("client.cli.PulseClient") as client_class:
        client = client_class.return_value.__enter__.return_value
        client.health.side_effect = httpx.ConnectError("Connection refused")
        result = CliRunner().invoke(cli, ["health"])

    assert result.exit_code == 1
    assert "Health check failed: Connection refused" in result.output


@pytest.mark.parametrize("command", ["upload-document", "get-document", "get-job"])
@pytest.mark.parametrize(
    "options, env, expected_url",
    [
        ([], {"PULSE_BASE_URL": ""}, "http://localhost:8000"),
        ([], {"PULSE_BASE_URL": "http://env.example"}, "http://env.example"),
        (
            ["--base-url", "http://option.example"],
            {"PULSE_BASE_URL": "http://env.example"},
            "http://option.example",
        ),
    ],
)
def test_document_commands_send_requests_and_print_json(
    tmp_path: Path,
    upload_payload: dict[str, str],
    document_payload: dict[str, object],
    job_payload: dict[str, object],
    command: str,
    options: list[str],
    env: dict[str, str],
    expected_url: str,
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")
    argument, method, endpoint, payload = {
        "upload-document": (str(path), "POST", "/documents", upload_payload),
        "get-document": (
            upload_payload["document_id"],
            "GET",
            f"/documents/{upload_payload['document_id']}",
            document_payload,
        ),
        "get-job": (
            upload_payload["job_id"],
            "GET",
            f"/jobs/{upload_payload['job_id']}",
            job_payload,
        ),
    }[command]
    requests: list[httpx.Request] = []
    clients: list[PulseClient] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201 if method == "POST" else 200, json=payload)

    def make_client(**kwargs) -> PulseClient:
        client = PulseClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    with patch("client.cli.PulseClient", side_effect=make_client) as client_class:
        result = CliRunner().invoke(cli, [*options, command, argument], env=env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload
    client_class.assert_called_once_with(base_url=expected_url)
    assert len(requests) == 1
    assert requests[0].method == method
    assert str(requests[0].url) == f"{expected_url}{endpoint}"
    with pytest.raises(RuntimeError, match="client has been closed"):
        clients[0].health()


@pytest.mark.parametrize(
    "command, message",
    [
        ("upload-document", "Document upload failed"),
        ("get-document", "Document retrieval failed"),
        ("get-job", "Job retrieval failed"),
    ],
)
@pytest.mark.parametrize(
    "failure", ["connection", "not_found", "validation", "bad_response"]
)
def test_document_commands_report_failures_and_close_client(
    tmp_path: Path,
    upload_payload: dict[str, str],
    command: str,
    message: str,
    failure: str,
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")
    argument = (
        str(path) if command == "upload-document" else upload_payload["document_id"]
    )
    clients: list[PulseClient] = []
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "connection":
            raise httpx.ConnectError("Connection refused", request=request)
        if failure == "bad_response":
            return httpx.Response(200, json={})
        return httpx.Response(
            404 if failure == "not_found" else 422, json={"detail": "Request rejected"}
        )

    def make_client(**kwargs) -> PulseClient:
        client = PulseClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    with patch("client.cli.PulseClient", side_effect=make_client):
        result = CliRunner().invoke(cli, [command, argument])

    assert result.exit_code == 1
    assert message in result.output
    assert len(requests) == 1
    if failure == "connection":
        assert "Connection refused" in result.output
    elif failure != "bad_response":
        assert str(404 if failure == "not_found" else 422) in result.output
    with pytest.raises(RuntimeError, match="client has been closed"):
        clients[0].health()


@pytest.mark.parametrize("is_directory", [False, True])
def test_upload_command_requires_an_existing_file(
    tmp_path: Path, is_directory: bool
) -> None:
    path = tmp_path if is_directory else tmp_path / "missing.pdf"
    with patch("client.cli.PulseClient") as client_class:
        result = CliRunner().invoke(cli, ["upload-document", str(path)])

    assert result.exit_code == 2
    client_class.assert_not_called()


@pytest.mark.parametrize("command", ["get-document", "get-job"])
def test_read_commands_require_a_uuid(command: str) -> None:
    with patch("client.cli.PulseClient") as client_class:
        result = CliRunner().invoke(cli, [command, "not-a-uuid"])

    assert result.exit_code == 2
    assert "not a valid UUID" in result.output
    client_class.assert_not_called()


def test_upload_command_reports_local_file_errors(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"document bytes")
    with patch("client.cli.PulseClient") as client_class:
        client = client_class.return_value.__enter__.return_value
        client.upload_document.side_effect = OSError("Permission denied")
        result = CliRunner().invoke(cli, ["upload-document", str(path)])

    assert result.exit_code == 1
    assert "Document upload failed: Permission denied" in result.output
    client_class.return_value.__exit__.assert_called_once()
