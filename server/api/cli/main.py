"""Commands for running and inspecting the Pulse API and worker."""

from importlib.metadata import version as package_version
from pathlib import Path

import click
import uvicorn
from alembic.config import Config as AlembicConfig

from alembic import command


@click.group()
def cli() -> None:
    """Run and inspect the Pulse API."""


@click.group()
def worker_cli() -> None:
    """Run the Pulse worker."""


@worker_cli.command("serve")
def serve_worker() -> None:
    """Start consuming document-processing jobs."""
    from api.worker.main import main

    main()


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
def serve(host: str) -> None:
    """Start the API on port 8000."""
    uvicorn.run(
        "api.main:create_app",
        factory=True,
        host=host,
        port=8000,
    )


@cli.command()
def version() -> None:
    """Print the installed application version."""
    click.echo(package_version("pulse-api"))


@cli.command()
def init_db() -> None:
    """Apply pending migrations to the configured, existing PostgreSQL database."""
    alembic_config = AlembicConfig(
        str(Path(__file__).resolve().parents[2] / "alembic.ini")
    )
    try:
        command.upgrade(alembic_config, "head")
    except Exception:
        raise click.ClickException(
            "Database initialization failed. Check PostgreSQL is running, the "
            "configured database exists, and the connection settings are correct."
        ) from None
    click.echo("Database migrations applied successfully.")
