from importlib.metadata import version
from unittest.mock import patch

from click.testing import CliRunner

from api.cli.main import cli


def test_version_command() -> None:
    result = CliRunner().invoke(cli, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == version("pulse-api")


def test_serve_command() -> None:
    with patch("api.cli.main.uvicorn.run") as run:
        result = CliRunner().invoke(cli, ["serve"])

    assert result.exit_code == 0
    run.assert_called_once_with(
        "api.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


def test_init_db_from_another_directory(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    with patch("api.cli.main.command.upgrade") as upgrade:
        result = CliRunner().invoke(cli, ["init-db"])

    assert result.exit_code == 0
    migration_config, revision = upgrade.call_args.args
    assert Path(migration_config.config_file_name).is_file()
    assert Path(migration_config.get_main_option("script_location")).is_dir()
    assert revision == "head"
    assert "successfully" in result.output


def test_init_db_failure_returns_error_without_exposing_credentials() -> None:
    with patch(
        "api.cli.main.command.upgrade", side_effect=RuntimeError("secret-password")
    ):
        result = CliRunner().invoke(cli, ["init-db"])

    assert result.exit_code != 0
    assert "Database initialization failed" in result.output
    assert "secret-password" not in result.output


def test_removed_serve_queue_command_is_unavailable():
    result = CliRunner().invoke(cli, ["serve-queue"])

    assert result.exit_code == 2
    assert "No such command" in result.output
