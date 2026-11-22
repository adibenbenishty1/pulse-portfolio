"""Use application configuration and metadata for online and offline migrations."""

from sqlalchemy import create_engine, pool

from alembic import context
from api.config import config
from api.db.base import Base
from api.models import Document, Job  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        config.database_url,
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
