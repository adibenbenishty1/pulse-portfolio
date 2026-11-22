"""PostgreSQL tests using the test database, with per-test rollback."""

from datetime import UTC
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import Document, Job, JobStatus

pytestmark = pytest.mark.integration


def new_document() -> Document:
    return Document(
        original_filename="sample.txt",
        storage_key=str(uuid4()),
        content_type="text/plain",
        file_size_bytes=0,
        sha256="a" * 64,
    )


def test_migration_tables_and_foreign_key(database_engine: Engine) -> None:
    schema = inspect(database_engine)
    assert {"documents", "processing_jobs"} <= set(schema.get_table_names())
    foreign_key = schema.get_foreign_keys("processing_jobs")[0]
    assert foreign_key["constrained_columns"] == ["document_id"]
    assert foreign_key["referred_table"] == "documents"
    assert foreign_key["referred_columns"] == ["id"]
    assert foreign_key["options"]["ondelete"] == "RESTRICT"


def test_duplicate_content_multiple_jobs_and_defaults(database: Session) -> None:
    first, second = new_document(), new_document()
    jobs = [Job(document=first), Job(document=first)]
    database.add_all([first, second, *jobs])
    database.flush()

    assert first.id != second.id
    assert first.sha256 == second.sha256
    assert len(first.jobs) == 2
    assert all(
        job.status == JobStatus.PENDING and job.attempt_count == 0 for job in jobs
    )
    assert first.created_at.utcoffset() == UTC.utcoffset(None)
    assert all(job.created_at.utcoffset() == UTC.utcoffset(None) for job in jobs)


@pytest.mark.parametrize(
    "violation",
    [
        "duplicate_storage_key",
        "negative_file_size",
        "negative_attempt_count",
        "invalid_status",
        "orphan_job",
        "delete_document",
        "invalid_checksum",
        "missing_filename",
    ],
)
def test_database_rejects_invalid_records(database: Session, violation: str) -> None:
    document = new_document()
    job = Job(document=document)
    database.add(job)
    database.flush()

    with pytest.raises(IntegrityError):
        if violation == "duplicate_storage_key":
            duplicate = new_document()
            duplicate.storage_key = document.storage_key
            database.add(duplicate)
        elif violation == "negative_file_size":
            document.file_size_bytes = -1
        elif violation == "negative_attempt_count":
            job.attempt_count = -1
        elif violation == "invalid_status":
            # Bypass ORM enum validation to exercise the database CHECK constraint.
            database.execute(
                text("UPDATE processing_jobs SET status = 'UNKNOWN' WHERE id = :id"),
                {"id": job.id},
            )
        elif violation == "orphan_job":
            job.document_id = uuid4()
        elif violation == "delete_document":
            database.delete(document)
        elif violation == "invalid_checksum":
            document.sha256 = "not-a-sha256"
        elif violation == "missing_filename":
            database.execute(
                text("UPDATE documents SET original_filename = NULL WHERE id = :id"),
                {"id": document.id},
            )
        database.flush()
