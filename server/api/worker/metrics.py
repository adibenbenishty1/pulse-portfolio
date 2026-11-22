"""Background metrics HTTP server owned by the worker lifecycle."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from wsgiref.simple_server import WSGIServer

from prometheus_client import Counter, start_http_server

logger = logging.getLogger(__name__)

MESSAGES_RECEIVED = Counter(
    "pulse_worker_messages_received_total", "Messages received by the worker."
)
JOBS_COMPLETED = Counter(
    "pulse_worker_jobs_completed_total", "Jobs committed as completed."
)
JOBS_FAILED = Counter("pulse_worker_jobs_failed_total", "Jobs committed as failed.")


@contextmanager
def metrics_server(host: str, port: int) -> Iterator[WSGIServer]:
    """Serve the default registry, then release the listener and server thread."""
    server, thread = start_http_server(port, addr=host)
    try:
        logger.info("Worker metrics listening on %s:%s", host, server.server_port)
        yield server
    finally:
        try:
            server.shutdown()
        finally:
            server.server_close()
            thread.join()
