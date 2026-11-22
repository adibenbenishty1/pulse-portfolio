"""Immutable document storage in an existing private S3 bucket."""

import hashlib
import re
from contextlib import closing
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from api.storage.base import StoredDocument

DOCUMENTS_SUFFIX = "documents/"
_KEY = re.compile(
    DOCUMENTS_SUFFIX
    + r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.bin"
)


class S3DocumentStorage:
    """Store and retrieve Pulse documents using the AWS credential chain."""

    def __init__(self, bucket: str, region: str) -> None:
        self._bucket = bucket
        self._client = boto3.session.Session().client("s3", region_name=region)

    @staticmethod
    def _validate_key(storage_key: str) -> None:
        if _KEY.fullmatch(storage_key) is None:
            raise ValueError("Invalid document storage key")

    def save(self, content: bytes) -> StoredDocument:
        result = StoredDocument(
            storage_key=f"{DOCUMENTS_SUFFIX}{uuid4()}.bin",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=result.storage_key,
                Body=content,
                IfNoneMatch="*",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] in {"PreconditionFailed", "412"}:
                raise FileExistsError(result.storage_key) from error
            raise
        return result

    def read(self, storage_key: str) -> bytes:
        self._validate_key(storage_key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=storage_key)
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(storage_key) from error
            raise
        with closing(response["Body"]) as body:
            return body.read()

    def delete(self, storage_key: str) -> None:
        self._validate_key(storage_key)
        self._client.delete_object(Bucket=self._bucket, Key=storage_key)
