"""Process-scoped engine and request-scoped synchronous sessions."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.config import config

# Engine creation is lazy about connections: importing this module does not
# connect to PostgreSQL or create tables. The pool lives for the process lifetime.
engine = create_engine(
    config.database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"options": "-c timezone=UTC"},
)
SessionFactory = sessionmaker(bind=engine)


def get_session() -> Iterator[Session]:
    """Yield one session; callers commit explicitly, and cleanup rolls back leftovers."""
    with SessionFactory() as session:
        yield session
