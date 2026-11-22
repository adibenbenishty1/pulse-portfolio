"""Select document storage for the API and worker."""

from api.config import Config
from api.storage.base import DocumentStorage
from api.storage.local import LocalFileStorage
from api.storage.s3 import S3DocumentStorage


def create_document_storage(config: Config) -> DocumentStorage:
    if config.STORAGE_BACKEND == "s3":
        return S3DocumentStorage(bucket=config.S3_BUCKET, region=config.S3_REGION)
    elif config.STORAGE_BACKEND == "local":
        return LocalFileStorage(config.STORAGE_ROOT)
    else:
        raise ValueError(f"Unsupported storage backend: {config.STORAGE_BACKEND!r}")
