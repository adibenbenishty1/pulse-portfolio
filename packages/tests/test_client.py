import httpx
import pytest

from client import PulseClient


def test_health_request() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    with PulseClient(
        base_url="http://pulse.example:9000", transport=httpx.MockTransport(respond)
    ) as client:
        assert client.health() == {"status": "ok"}

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "http://pulse.example:9000/health/live"


def test_default_base_url() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8000/health/live"
        return httpx.Response(200, json={"status": "ok"})

    with PulseClient(transport=httpx.MockTransport(respond)) as client:
        client.health()


def test_http_error_is_propagated() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    with (
        PulseClient(transport=transport) as client,
        pytest.raises(httpx.HTTPStatusError) as error,
    ):
        client.health()

    assert error.value.response.status_code == 503


def test_connection_error_is_propagated() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with (
        PulseClient(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(httpx.ConnectError, match="Connection refused"),
    ):
        client.health()


@pytest.mark.parametrize("payload", [{}, {"status": 1}, ["ok"]])
def test_invalid_health_response(payload: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    with (
        PulseClient(transport=transport) as client,
        pytest.raises(ValueError, match="string 'status'"),
    ):
        client.health()


def test_context_manager_closes_after_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    client = PulseClient(transport=transport)

    with pytest.raises(httpx.HTTPStatusError), client:
        client.health()

    with pytest.raises(RuntimeError, match="client has been closed"):
        client.health()


def test_explicit_close() -> None:
    client = PulseClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client.close()

    with pytest.raises(RuntimeError, match="client has been closed"):
        client.health()
