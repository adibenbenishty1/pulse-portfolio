import hashlib
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from api.config import Config
from api.storage import StoredDocument, create_document_storage, s3

BUCKET = "pulse-test"
REGION = "us-east-2"


@pytest.fixture
def s3_storage(monkeypatch):
    client = boto3.session.Session(
        aws_access_key_id="test", aws_secret_access_key="test"
    ).client("s3", region_name=REGION)
    session = Mock()
    session.client.return_value = client
    monkeypatch.setattr(s3.boto3.session, "Session", Mock(return_value=session))
    monkeypatch.setenv("PULSE_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("PULSE_S3_BUCKET", BUCKET)
    monkeypatch.setenv("PULSE_S3_REGION", REGION)
    storage = create_document_storage(Config())
    session.client.assert_called_once_with("s3", region_name=REGION)
    with Stubber(client) as stubber:
        yield storage, stubber
        stubber.assert_no_pending_responses()


def test_save_read_and_idempotent_delete(s3_storage, monkeypatch):
    storage, stubber = s3_storage
    identifier = uuid4()
    monkeypatch.setattr(s3, "uuid4", lambda: identifier)
    key = f"documents/{identifier}.bin"
    content = b"Pulse S3 document"
    params = {"Bucket": BUCKET, "Key": key}
    stream = BytesIO(content)
    stubber.add_response(
        "put_object", {}, params | {"Body": content, "IfNoneMatch": "*"}
    )
    stubber.add_response(
        "get_object", {"Body": StreamingBody(stream, len(content))}, params
    )
    stubber.add_response("delete_object", {}, params)
    stubber.add_response("delete_object", {}, params)

    assert storage.save(content) == StoredDocument(
        key, len(content), hashlib.sha256(content).hexdigest()
    )
    assert storage.read(key) == content
    assert stream.closed
    storage.delete(key)
    storage.delete(key)


def test_save_never_overwrites_existing_object(s3_storage, monkeypatch):
    storage, stubber = s3_storage
    identifier = uuid4()
    monkeypatch.setattr(s3, "uuid4", lambda: identifier)
    stubber.add_client_error(
        "put_object",
        service_error_code="PreconditionFailed",
        http_status_code=412,
        expected_params={
            "Bucket": BUCKET,
            "Key": f"documents/{identifier}.bin",
            "Body": b"replacement",
            "IfNoneMatch": "*",
        },
    )
    with pytest.raises(FileExistsError):
        storage.save(b"replacement")


@pytest.mark.parametrize(
    ("code", "status", "exception"),
    [
        ("NoSuchKey", 404, FileNotFoundError),
        ("AccessDenied", 403, ClientError),
        ("NoSuchBucket", 404, ClientError),
        ("404", 404, ClientError),
    ],
)
def test_read_only_translates_missing_object_errors(
    s3_storage, code, status, exception
):
    storage, stubber = s3_storage
    key = f"documents/{uuid4()}.bin"
    stubber.add_client_error(
        "get_object",
        service_error_code=code,
        http_status_code=status,
        expected_params={"Bucket": BUCKET, "Key": key},
    )
    with pytest.raises(exception):
        storage.read(key)


def test_read_closes_body_when_read_fails(s3_storage):
    storage, stubber = s3_storage
    key = f"documents/{uuid4()}.bin"
    endpoint_error = EndpointConnectionError(endpoint_url="https://s3.example")
    stream = Mock(spec=BytesIO)
    stream.read.side_effect = endpoint_error
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(stream, None)},
        {"Bucket": BUCKET, "Key": key},
    )
    with pytest.raises(EndpointConnectionError) as exc:
        storage.read(key)
    assert exc.value is endpoint_error
    stream.close.assert_called_once_with()


@pytest.mark.parametrize("key", ["documents/../secret", "documents/file.bin"])
def test_reject_invalid_keys_without_calling_s3(s3_storage, key):
    storage, _ = s3_storage
    for operation in (storage.read, storage.delete):
        with pytest.raises(ValueError, match="Invalid document storage key"):
            operation(key)
