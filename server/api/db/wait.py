"""Wait for an authenticated PostgreSQL connection before running migrations."""

import time

import click
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from api.config import config


@click.command()
@click.option("--timeout", type=click.IntRange(min=1), default=120, show_default=True)
def main(timeout: int) -> None:
    """Wait up to TIMEOUT seconds for PostgreSQL to accept a query."""
    engine = create_engine(config.database_url, connect_args={"connect_timeout": 3})
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except OperationalError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise click.ClickException(
                        "Timed out waiting for PostgreSQL."
                    ) from None
                click.echo("Waiting for PostgreSQL...")
                time.sleep(min(2, remaining))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
