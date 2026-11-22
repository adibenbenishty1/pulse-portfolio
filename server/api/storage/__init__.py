"""Document byte storage, independent of HTTP and persistence infrastructure."""

from api.storage.base import DocumentStorage, StoredDocument
from api.storage.factory import create_document_storage
from api.storage.local import LocalFileStorage
from api.storage.s3 import S3DocumentStorage

__all__ = [
    "DocumentStorage",
    "LocalFileStorage",
    "S3DocumentStorage",
    "StoredDocument",
    "create_document_storage",
]
