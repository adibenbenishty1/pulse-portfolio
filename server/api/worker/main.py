"""Entry point for the Pulse worker."""

import json
import logging
import sys
from datetime import datetime
from uuid import UUID

import pika

from api.config import config
from api.db.session import SessionFactory
from api.models import Analysis, Job, JobStatus
from api.services.documents import DocumentService
from api.services.text_analysis import analyze_text
from api.storage import create_document_storage
from api.utils import error_record
from api.worker.metrics import (
    JOBS_COMPLETED,
    JOBS_FAILED,
    MESSAGES_RECEIVED,
    metrics_server,
)

logger = logging.getLogger(__name__)


def handle_message(channel, method, properties, body):
    MESSAGES_RECEIVED.inc()
    message = json.loads(body.decode("utf-8"))
    job_id = UUID(message["job_id"])

    print(f"Received job: {job_id}", flush=True)
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")

        try:
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now()
            session.commit()
            documents_service = DocumentService(
                storage=create_document_storage(config), session=session
            )
            doc_bytes = documents_service.read(job.document_id)
            logger.info("Read %s bytes for job %s", len(doc_bytes), job_id)

            result = analyze_text(doc_bytes)

            analysis = Analysis(job_id=job_id, results=result)
            session.add(analysis)
            logger.info("Text statistics for job %s: %s", job_id, json.dumps(result))
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            session.commit()
            JOBS_COMPLETED.inc()
        except Exception as e:
            session.rollback()
            job.status = JobStatus.FAILED
            job.error_message = repr(e)
            session.add(error_record(e))
            session.commit()
            JOBS_FAILED.inc()
            logger.exception("Job %s failed", job_id)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

    channel.basic_ack(delivery_tag=method.delivery_tag)


def main() -> None:
    """Configure console logging and start the worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logger.info("Pulse worker starting")
    with metrics_server(config.WORKER_METRICS_HOST, config.WORKER_METRICS_PORT):
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config.RABBITMQ_HOST,
                port=int(config.RABBITMQ_PORT),
                credentials=pika.PlainCredentials(
                    config.RABBITMQ_USERNAME,
                    config.RABBITMQ_PASSWORD,
                ),
            )
        )

        try:
            channel = connection.channel()

            channel.queue_declare(
                queue=config.RABBITMQ_QUEUE_NAME,
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )

            channel.basic_qos(prefetch_count=1)

            channel.basic_consume(
                queue=config.RABBITMQ_QUEUE_NAME,
                on_message_callback=handle_message,
                auto_ack=False,
            )
            logger.info("Waiting for jobs. Press Ctrl+C to stop.")
            channel.start_consuming()
        finally:
            if connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
