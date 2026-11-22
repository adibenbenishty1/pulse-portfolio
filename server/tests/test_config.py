from pathlib import Path

import pytest
from pydantic import ValidationError

from api.config import Config


@pytest.fixture(autouse=True)
def clear_configuration_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in Config.model_fields:
        monkeypatch.delenv(f"PULSE_{field}", raising=False)


def test_development_defaults() -> None:
    config = Config()

    assert config.ENV == "local"
    assert config.DB_HOST == "localhost"
    assert config.DB_PORT == 5432
    assert config.DB_NAME == config.DB_USER == "pulse"
    assert config.DB_TEST_NAME == "pulse_test"
    assert config.DB_PASSWORD == "pulse-local-only"
    assert config.MAX_UPLOAD_BYTES == 5 * 1024 * 1024
    assert config.STORAGE_BACKEND == "local"
    assert config.WORKER_METRICS_HOST == "127.0.0.1"
    assert config.WORKER_METRICS_PORT == 9100
    assert config.database_url.drivername == "postgresql+psycopg"


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for field, value in {
        "ENV": "development",
        "DB_HOST": "postgres.example",
        "DB_PORT": "55432",
        "DB_NAME": "other_database",
        "DB_TEST_NAME": "other_test_database",
        "DB_USER": "other_user",
        "DB_PASSWORD": "secret@with:/symbols%",
        "MAX_UPLOAD_BYTES": "1024",
        "WORKER_METRICS_HOST": "0.0.0.0",
        "WORKER_METRICS_PORT": "9200",
    }.items():
        monkeypatch.setenv(f"PULSE_{field}", value)

    config = Config()
    assert config.ENV == "development"
    assert config.DB_HOST == "postgres.example"
    assert config.DB_PORT == 55432
    assert config.DB_NAME == "other_database"
    assert config.DB_TEST_NAME == "other_test_database"
    assert config.DB_USER == "other_user"
    assert config.DB_PASSWORD == "secret@with:/symbols%"
    assert config.MAX_UPLOAD_BYTES == 1024
    assert config.WORKER_METRICS_HOST == "0.0.0.0"
    assert config.WORKER_METRICS_PORT == 9200
    assert config.database_url.password == "secret@with:/symbols%"
    assert "secret@with:/symbols%" not in str(config.database_url)


def test_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSE_DB_PORT", "invalid")
    with pytest.raises(ValidationError) as error:
        Config()
    assert "input_value" not in str(error.value)


@pytest.mark.parametrize("port", ["0", "-1", "65536", "invalid"])
def test_invalid_worker_metrics_port(monkeypatch, port):
    monkeypatch.setenv("PULSE_WORKER_METRICS_PORT", port)
    with pytest.raises(ValidationError):
        Config()


@pytest.mark.parametrize("limit", ["0", "-1", "invalid"])
def test_invalid_upload_limit(monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    monkeypatch.setenv("PULSE_MAX_UPLOAD_BYTES", limit)
    with pytest.raises(ValidationError):
        Config()


def test_dotenv_is_not_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("PULSE_ENV=production\nPULSE_DB_NAME=unexpected\n")
    monkeypatch.chdir(tmp_path)
    config = Config()
    assert config.ENV == "local"
    assert config.DB_NAME == "pulse"


def test_default_storage_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PULSE_STORAGE_ROOT", raising=False)
    assert Config().STORAGE_ROOT == Path("data/storage")


def test_storage_root_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_STORAGE_ROOT", str(tmp_path / "custom-storage"))
    assert Config().STORAGE_ROOT == tmp_path / "custom-storage"
