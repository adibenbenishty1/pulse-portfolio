"""Typed application configuration with local development defaults."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Config(BaseSettings):
    """Application defaults with PULSE_* overrides; no .env file is loaded."""

    model_config = SettingsConfigDict(
        env_prefix="PULSE_", env_file=None, extra="ignore", hide_input_in_errors=True
    )

    # basic
    ENV: str = "local"

    # database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "pulse"
    DB_TEST_NAME: str = "pulse_test"
    DB_USER: str = "pulse"
    DB_PASSWORD: str = "pulse-local-only"

    # rabbit-mq
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: str = "5672"
    RABBITMQ_USERNAME: str = "pulse"
    RABBITMQ_PASSWORD: str = "pulse-local-only"
    RABBITMQ_VIRTUAL_HOST: str = "/"
    RABBITMQ_QUEUE_NAME: str = "pulse.processing"

    # worker metrics
    WORKER_METRICS_HOST: str = "127.0.0.1"
    WORKER_METRICS_PORT: Annotated[int, Field(ge=1, le=65535)] = 9100

    # storage
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_ROOT: Path = Path("data/storage")
    S3_BUCKET: str = ""
    S3_REGION: str = "us-east-2"

    # uploads
    MAX_UPLOAD_BYTES: PositiveInt = 5 * 1024 * 1024

    @model_validator(mode="after")
    def validate_s3_settings(self) -> Self:
        if self.STORAGE_BACKEND == "s3":
            for name, value in (
                ("PULSE_S3_BUCKET", self.S3_BUCKET),
                ("PULSE_S3_REGION", self.S3_REGION),
            ):
                if not value or any(character.isspace() for character in value):
                    raise ValueError(f"{name} must be set without whitespace for S3")
        return self

    @property
    def database_url(self) -> URL:
        """Build a driver URL without manually escaping credentials."""
        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )


# instance
# --------
config = Config()
