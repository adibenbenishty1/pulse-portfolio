from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from api.db.wait import main


def test_wait_retries_then_accepts_a_query() -> None:
    connection = MagicMock()
    with (
        patch("api.db.wait.create_engine") as create_engine,
        patch("api.db.wait.time.sleep") as sleep,
        patch("api.db.wait.time.monotonic", side_effect=[0, 1]),
    ):
        engine = create_engine.return_value
        engine.connect.side_effect = [
            OperationalError("connect", None, Exception("private-password")),
            connection,
        ]
        result = CliRunner().invoke(main, ["--timeout", "10"])

    assert result.exit_code == 0
    assert engine.connect.call_count == 2
    connection.__enter__.return_value.execute.assert_called_once()
    sleep.assert_called_once_with(2)
    engine.dispose.assert_called_once()


def test_wait_timeout_fails_without_exposing_credentials() -> None:
    with (
        patch("api.db.wait.create_engine") as create_engine,
        patch("api.db.wait.time.monotonic", side_effect=[0, 10]),
    ):
        engine = create_engine.return_value
        engine.connect.side_effect = OperationalError(
            "connect", None, Exception("private-password")
        )
        result = CliRunner().invoke(main, ["--timeout", "10"])

    assert result.exit_code == 1
    assert "Timed out waiting for PostgreSQL" in result.output
    assert "private-password" not in result.output
    engine.dispose.assert_called_once()
