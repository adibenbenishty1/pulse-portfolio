from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from api.models import Error, Job, JobStatus
from api.worker import main as worker


@pytest.mark.parametrize("exception", [FileNotFoundError("missing"), ValueError("bad")])
def test_failed_job_records_error_and_rejects_message(monkeypatch, exception):
    session = MagicMock()
    job = Job(id=uuid4(), document_id=uuid4())
    session.get.return_value = job
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(worker, "SessionFactory", factory)

    def read_document(*args):
        raise exception

    service = MagicMock()
    service.read.side_effect = read_document
    monkeypatch.setattr(worker, "DocumentService", MagicMock(return_value=service))
    channel = MagicMock()
    method = MagicMock(delivery_tag=42)

    worker.handle_message(channel, method, None, f'{{"job_id": "{job.id}"}}'.encode())

    record = session.add.call_args.args[0]
    assert isinstance(record, Error)
    assert record.error_message == repr(exception)
    assert record.location == f"{__name__}.{read_document.__qualname__}"
    assert job.status == JobStatus.FAILED
    assert job.error_message == repr(exception)
    session.rollback.assert_called_once()
    assert session.commit.call_count == 2
    channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
    channel.basic_ack.assert_not_called()
