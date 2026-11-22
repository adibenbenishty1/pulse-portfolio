"""Terminal commands built on the Pulse client SDK."""

import json
from importlib.metadata import version as package_version
from pathlib import Path
from uuid import UUID

import click
import httpx

from client import PulseClient


@click.group()
@click.option(
    "--base-url",
    default="http://localhost:8000",
    envvar="PULSE_BASE_URL",
    show_default=True,
    help="URL of the Pulse API.",
)
@click.pass_context
def cli(ctx: click.Context, base_url: str) -> None:
    """Communicate with the Pulse API."""
    ctx.obj = base_url


@cli.command()
@click.pass_obj
def health(base_url: str) -> None:
    """Check the API liveness endpoint."""
    try:
        with PulseClient(base_url=base_url) as client:
            result = client.health()
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Health check failed: {exc}") from exc
    click.echo(json.dumps(result))


@cli.command()
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.pass_obj
def upload_document(base_url: str, path: Path) -> None:
    """Upload a local file and print its document and job IDs."""
    try:
        with PulseClient(base_url=base_url) as client:
            result = client.upload_document(path)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise click.ClickException(f"Document upload failed: {exc}") from exc
    click.echo(result.model_dump_json())


@cli.command()
@click.argument("document_id", type=click.UUID)
@click.pass_obj
def get_document(base_url: str, document_id: UUID) -> None:
    """Print a document's metadata as JSON."""
    try:
        with PulseClient(base_url=base_url) as client:
            result = client.get_document(document_id)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Document retrieval failed: {exc}") from exc
    click.echo(result.model_dump_json())


@cli.command()
@click.argument("job_id", type=click.UUID)
@click.pass_obj
def get_job(base_url: str, job_id: UUID) -> None:
    """Print a processing job's status as JSON."""
    try:
        with PulseClient(base_url=base_url) as client:
            result = client.get_job(job_id)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Job retrieval failed: {exc}") from exc
    click.echo(result.model_dump_json())


@cli.command()
def version() -> None:
    """Print the installed client version."""
    click.echo(package_version("pulse-client"))
