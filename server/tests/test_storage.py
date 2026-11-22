import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from api.config import Config
from api.storage import DocumentStorage, LocalFileStorage, local


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "storage")


@pytest.mark.parametrize("content", [b"", b'{"raw": true}\r\n', bytes(range(256))])
def test_save_read_and_metadata(storage: LocalFileStorage, content: bytes) -> None:
    adapter: DocumentStorage = storage
    result = adapter.save(content)

    assert adapter.read(result.storage_key) == content
    assert result.size_bytes == len(content)
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.storage_key.startswith("documents/")
    assert UUID(Path(result.storage_key).stem).version == 4


def test_identical_content_is_not_deduplicated(storage: LocalFileStorage) -> None:
    first = storage.save(b"same")
    second = storage.save(b"same")
    assert first.storage_key != second.storage_key
    assert first.sha256 == second.sha256


def test_collision_does_not_overwrite(
    storage: LocalFileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = uuid4()
    monkeypatch.setattr(local, "uuid4", lambda: identifier)
    original = storage.save(b"original")

    with pytest.raises(FileExistsError):
        storage.save(b"replacement")

    assert storage.read(original.storage_key) == b"original"
    assert len(list((tmp_path / "storage/documents").iterdir())) == 1


def test_read_missing_file(storage: LocalFileStorage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.read(f"documents/{uuid4()}.bin")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../secret",
        "documents/../../secret",
        "documents/./file.bin",
        "documents//file.bin",
        "documents/not-a-uuid.bin",
        f"documents/{uuid4()}.json",
        f"documents/{uuid4()}.bin/extra",
        "documents\\file.bin",
        "documents/\x00.bin",
        "documents/.temporary.tmp",
    ],
)
def test_invalid_keys(storage: LocalFileStorage, key: str) -> None:
    for operation in (storage.read, storage.delete):
        with pytest.raises(ValueError, match="Invalid document storage key"):
            operation(key)


def test_delete_only_removes_requested_document(storage: LocalFileStorage) -> None:
    first, second = storage.save(b"first"), storage.save(b"second")
    storage.delete(first.storage_key)
    storage.delete(first.storage_key)
    with pytest.raises(FileNotFoundError):
        storage.read(first.storage_key)
    assert storage.read(second.storage_key) == b"second"


@pytest.mark.parametrize("part", ["root", "ancestor", "documents"])
def test_reject_symlink_directories(tmp_path: Path, part: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    if part == "root":
        root = tmp_path / "storage"
        root.symlink_to(outside, target_is_directory=True)
    elif part == "ancestor":
        ancestor = tmp_path / "linked"
        ancestor.symlink_to(outside, target_is_directory=True)
        root = ancestor / "storage"
    else:
        root = tmp_path / "storage"
        root.mkdir()
        (root / "documents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        LocalFileStorage(root)
    assert list(outside.iterdir()) == []


def test_reject_document_symlink(storage: LocalFileStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched")
    key = f"documents/{uuid4()}.bin"
    (tmp_path / "storage" / key).symlink_to(outside)

    with pytest.raises(OSError):
        storage.read(key)
    with pytest.raises(ValueError, match="regular file"):
        storage.delete(key)
    assert outside.read_bytes() == b"untouched"


@pytest.mark.parametrize("operation", ["save", "read", "delete"])
def test_directory_symlink_swap_is_rejected(
    storage: LocalFileStorage, tmp_path: Path, operation: str
) -> None:
    saved = storage.save(b"original")
    root = tmp_path / "storage"
    (root / "documents").rename(root / "original-documents")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "documents").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        if operation == "save":
            storage.save(b"new")
        else:
            getattr(storage, operation)(saved.storage_key)
    assert list(outside.iterdir()) == []


def test_partial_write_is_invisible_and_cleaned_up(
    storage: LocalFileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = uuid4()
    monkeypatch.setattr(local, "uuid4", lambda: identifier)
    real_fdopen = os.fdopen

    def failing_fdopen(descriptor: int, mode: str) -> object:
        output = real_fdopen(descriptor, mode)
        wrapper = MagicMock(wraps=output)
        wrapper.__enter__.return_value = wrapper
        wrapper.__exit__.side_effect = output.__exit__

        def partial_write(content: bytes) -> None:
            output.write(content[:2])
            output.flush()
            assert not (tmp_path / f"storage/documents/{identifier}.bin").exists()
            raise OSError("simulated partial write")

        wrapper.write.side_effect = partial_write
        return wrapper

    monkeypatch.setattr(local.os, "fdopen", failing_fdopen)
    with pytest.raises(OSError, match="simulated partial write"):
        storage.save(b"incomplete")
    assert list((tmp_path / "storage/documents").iterdir()) == []


@pytest.mark.parametrize("failure", ["fsync", "link"])
def test_flush_or_publication_failure_cleans_temporary_file(
    storage: LocalFileStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(local.os, failure, MagicMock(side_effect=OSError("simulated")))
    with pytest.raises(OSError, match="simulated"):
        storage.save(b"data")
    assert list((tmp_path / "storage/documents").iterdir()) == []


def test_relative_root_is_anchored_at_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PULSE_STORAGE_ROOT", raising=False)
    storage = LocalFileStorage(Config().STORAGE_ROOT)
    saved = storage.save(b"data")
    monkeypatch.chdir(tmp_path.parent)
    assert storage.read(saved.storage_key) == b"data"
    assert (tmp_path / "data/storage" / saved.storage_key).is_file()


def test_existing_temporary_file_is_not_overwritten_or_deleted(
    storage: LocalFileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = uuid4()
    temporary = tmp_path / f"storage/documents/.{identifier}.tmp"
    temporary.write_bytes(b"other writer")
    monkeypatch.setattr(local, "uuid4", lambda: identifier)

    with pytest.raises(FileExistsError):
        storage.save(b"replacement")
    assert temporary.read_bytes() == b"other writer"


def test_save_does_not_replace_destination_symlink(
    storage: LocalFileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = uuid4()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched")
    destination = tmp_path / f"storage/documents/{identifier}.bin"
    destination.symlink_to(outside)
    monkeypatch.setattr(local, "uuid4", lambda: identifier)

    with pytest.raises(FileExistsError):
        storage.save(b"replacement")
    assert destination.is_symlink()
    assert outside.read_bytes() == b"untouched"
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_nonregular_documents_are_rejected(
    storage: LocalFileStorage, tmp_path: Path, kind: str
) -> None:
    key = f"documents/{uuid4()}.bin"
    destination = tmp_path / "storage" / key
    if kind == "directory":
        destination.mkdir()
    else:
        os.mkfifo(destination)

    with pytest.raises((ValueError, IsADirectoryError)):
        storage.read(key)
    with pytest.raises(ValueError, match="regular file"):
        storage.delete(key)
    assert destination.exists()
