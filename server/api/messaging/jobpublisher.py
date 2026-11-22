import json
import logging
from concurrent.futures import Future
from queue import Empty, Full, Queue
from threading import Event, Thread
from uuid import UUID

import pika

from api.config import config

logger = logging.getLogger(__name__)


class JobPublisher:
    def __init__(self):
        self._tasks = Queue(maxsize=100)
        self._stop = Event()
        self._ready = Future()
        self._thread = Thread(target=self.run, name="rabbitmq_publisher")

    def start(self):
        self._thread.start()
        self._ready.result(timeout=15)

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=15)

    def publish(self, job_id: UUID):

        result = Future()

        try:
            self._tasks.put_nowait((job_id, result))
        except Full:
            result.set_exception(RuntimeError("Publisher queue is full"))

        return result

    def run(self):
        connection = None
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=config.RABBITMQ_HOST,
                    port=int(config.RABBITMQ_PORT),
                    credentials=pika.PlainCredentials(
                        config.RABBITMQ_USERNAME, config.RABBITMQ_PASSWORD
                    ),
                )
            )
            channel = connection.channel()
            channel.queue_declare(
                queue=config.RABBITMQ_QUEUE_NAME,
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )

            # Publish waits for broker confirmation.
            channel.confirm_delivery()
            self._ready.set_result(None)

            while not self._stop.is_set():
                # Service network events, including heartbeats.
                connection.process_data_events(time_limit=0)

                try:
                    job_id, result = self._tasks.get(timeout=0.1)
                except Empty:
                    continue

                try:
                    message = {
                        "job_id": str(job_id),
                    }

                    body = json.dumps(message).encode("utf-8")

                    channel.basic_publish(
                        exchange="",
                        routing_key=config.RABBITMQ_QUEUE_NAME,
                        body=body,
                        mandatory=True,
                        properties=pika.BasicProperties(
                            content_type="application/json",
                            delivery_mode=2,
                        ),
                    )

                    result.set_result(None)

                except Exception as error:
                    result.set_exception(error)
                    raise

                finally:
                    self._tasks.task_done()
        except Exception as error:
            if not self._ready.done():
                self._ready.set_exception(error)
            logger.exception("RabbitMQ message publish error")
        finally:
            # 5. Close this call's connection, including on failure.
            if connection is not None and connection.is_open:
                connection.close()
