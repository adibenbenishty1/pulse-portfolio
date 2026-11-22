from unittest.mock import MagicMock
from urllib.request import urlopen

import pytest

from api.worker import main as worker
from api.worker.metrics import metrics_server


def test_metrics_endpoint_and_cleanup():
    with pytest.raises(RuntimeError, match="stop worker"):
        with metrics_server("127.0.0.1", 0) as server:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/metrics", timeout=2
            ) as response:
                assert response.status == 200
                body = response.read().decode()
            assert "python_info" in body
            assert "process_cpu_seconds_total" in body
            raise RuntimeError("stop worker")

    assert server.socket.fileno() == -1


@pytest.mark.parametrize("connection_fails", [False, True])
def test_worker_closes_metrics_on_exit(monkeypatch, connection_fails):
    metrics = MagicMock()
    monkeypatch.setattr(worker, "metrics_server", metrics)
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(worker.pika, "BlockingConnection", connect)
    if connection_fails:
        connect.side_effect = RuntimeError("broker unavailable")
        with pytest.raises(RuntimeError, match="broker unavailable"):
            worker.main()
    else:
        worker.main()
        connection.channel.return_value.start_consuming.assert_called_once()
        connection.close.assert_called_once()

    metrics.assert_called_once_with(
        worker.config.WORKER_METRICS_HOST, worker.config.WORKER_METRICS_PORT
    )
    metrics.return_value.__exit__.assert_called_once()
