"""Threaded publisher contracts without a running RabbitMQ broker."""

import json
from queue import Queue
from threading import get_ident
from unittest.mock import MagicMock
from uuid import uuid4

import pika
import pytest

from api.config import config
from api.messaging.jobpublisher import JobPublisher


@pytest.fixture
def broker(monkeypatch):
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("api.messaging.jobpublisher.pika.BlockingConnection", connect)
    return connect, connection, connection.channel.return_value


def test_configured_queue_and_confirmed_persistent_publish(monkeypatch, broker):
    connect, connection, channel = broker
    monkeypatch.setattr(config, "RABBITMQ_HOST", "broker.example")
    monkeypatch.setattr(config, "RABBITMQ_PORT", "5673")
    monkeypatch.setattr(config, "RABBITMQ_USERNAME", "worker")
    monkeypatch.setattr(config, "RABBITMQ_PASSWORD", "test-password")
    monkeypatch.setattr(config, "RABBITMQ_QUEUE_NAME", "test.processing")
    thread_ids = []
    channel.basic_publish.side_effect = lambda **kwargs: thread_ids.append(get_ident())
    publisher = JobPublisher()
    job_ids = [uuid4(), uuid4()]
    try:
        publisher.start()
        for job_id in job_ids:
            publisher.publish(job_id).result(timeout=2)
    finally:
        publisher.stop()

    parameters = connect.call_args.args[0]
    assert parameters.host == "broker.example"
    assert parameters.port == 5673
    assert parameters.credentials.username == "worker"
    assert parameters.credentials.password == "test-password"
    connect.assert_called_once()
    channel.queue_declare.assert_called_once_with(
        queue="test.processing", durable=True, arguments={"x-queue-type": "quorum"}
    )
    channel.confirm_delivery.assert_called_once_with()
    assert [call[0] for call in channel.method_calls][:2] == [
        "queue_declare",
        "confirm_delivery",
    ]
    for call, job_id in zip(channel.basic_publish.call_args_list, job_ids, strict=True):
        message = call.kwargs
        assert message["exchange"] == ""
        assert message["routing_key"] == "test.processing"
        assert message["mandatory"] is True
        assert isinstance(message["body"], bytes)
        assert json.loads(message["body"]) == {"job_id": str(job_id)}
        assert message["properties"].content_type == "application/json"
        assert message["properties"].delivery_mode == 2
    assert len(set(thread_ids)) == 1
    assert thread_ids[0] != get_ident()
    connection.process_data_events.assert_called()
    connection.close.assert_called_once_with()
    assert not publisher._thread.is_alive()


@pytest.mark.parametrize("failure", ["connection", "declaration", "confirmation"])
def test_startup_failure_propagates_and_thread_stops(broker, failure):
    connect, connection, channel = broker
    error = pika.exceptions.AMQPConnectionError("unavailable")
    target = {
        "connection": connect,
        "declaration": channel.queue_declare,
        "confirmation": channel.confirm_delivery,
    }[failure]
    target.side_effect = error
    publisher = JobPublisher()
    try:
        with pytest.raises(pika.exceptions.AMQPConnectionError) as caught:
            publisher.start()
        assert caught.value is error
    finally:
        publisher.stop()
    assert not publisher._thread.is_alive()
    if failure == "connection":
        connection.close.assert_not_called()
    else:
        connection.close.assert_called_once_with()


def test_publish_failure_reaches_future_and_closes_connection(broker):
    _, connection, channel = broker
    error = pika.exceptions.StreamLostError("Connection lost")
    channel.basic_publish.side_effect = error
    publisher = JobPublisher()
    try:
        publisher.start()
        with pytest.raises(pika.exceptions.StreamLostError) as caught:
            publisher.publish(uuid4()).result(timeout=2)
        assert caught.value is error
    finally:
        publisher.stop()
    connection.close.assert_called_once_with()
    assert not publisher._thread.is_alive()


def test_full_local_queue_returns_failed_future():
    publisher = JobPublisher()
    publisher._tasks = Queue(maxsize=1)
    first = publisher.publish(uuid4())
    second = publisher.publish(uuid4())
    assert not first.done()
    with pytest.raises(RuntimeError, match="Publisher queue is full"):
        second.result(timeout=0)
