from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from api.models import Document, Job, JobStatus


def test_document_identity_and_uniqueness() -> None:
    table = Document.__table__
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("storage_key",) in unique_columns
    assert ("sha256",) not in unique_columns
    assert table.c.id.type.as_uuid
    assert all(not column.nullable for column in table.columns)


def test_one_document_can_have_multiple_jobs() -> None:
    document = Document()
    first = Job(document=document)
    second = Job(document=document)

    assert document.jobs == [first, second]
    assert inspect(Document).relationships.jobs.uselist
    assert not inspect(Job).relationships.document.uselist


def test_postgresql_constraints_and_timestamps() -> None:
    documents = str(
        CreateTable(Document.__table__).compile(dialect=postgresql.dialect())
    )
    jobs = str(CreateTable(Job.__table__).compile(dialect=postgresql.dialect()))

    assert "file_size_bytes >= 0" in documents
    assert "sha256 ~ '^[0-9a-f]{64}$'" in documents
    assert "attempt_count >= 0" in jobs
    assert "REFERENCES documents (id) ON DELETE RESTRICT" in jobs
    assert "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')" in jobs
    for model, names in (
        (Document, ["created_at"]),
        (Job, ["created_at", "started_at", "completed_at"]),
    ):
        assert all(model.__table__.c[name].type.timezone for name in names)
    assert Job.__table__.c.started_at.nullable
    assert Job.__table__.c.completed_at.nullable
    assert Job.__table__.c.error_message.nullable


def test_job_defaults_and_enum_representation() -> None:
    table = Job.__table__
    assert table.c.status.default.arg is JobStatus.PENDING
    assert table.c.attempt_count.default.arg == 0
    assert not table.c.status.type.native_enum
    assert table.c.status.type.create_constraint
