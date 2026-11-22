from unittest.mock import patch

from click.testing import CliRunner

from api.cli.main import worker_cli


def test_serve_calls_worker_main() -> None:
    with patch("api.worker.main.main") as main:
        result = CliRunner().invoke(worker_cli, ["serve"])

    assert result.exit_code == 0
    main.assert_called_once_with()


def test_help_does_not_start_worker() -> None:
    with patch("api.worker.main.main") as main:
        result = CliRunner().invoke(worker_cli, ["--help"])

    assert result.exit_code == 0
    assert "serve" in result.output
    main.assert_not_called()
