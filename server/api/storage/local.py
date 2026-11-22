"""Atomic, non-overwriting local storage for Linux/WSL filesystems."""

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from api.storage.base import StoredDocument

_KEY = re.compile(
    r"documents/([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.bin)"
)
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class LocalFileStorage:
    """Store bounded byte payloads beneath an application-controlled root."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).absolute()
        if ".." in self._root.parts:
            raise ValueError("Storage root must not contain '..'")
        with self._documents_directory(create=True):
            pass

    @contextmanager
    def _documents_directory(self, *, create: bool = False) -> Iterator[int]:
        # Walk from / without resolving symlinks. Each opened directory pins its
        # identity, so replacing a path with a symlink cannot redirect the walk.
        directory = os.open(self._root.anchor, _DIRECTORY_FLAGS)
        try:
            for part in (*self._root.parts[1:], "documents"):
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory)
                os.close(directory)
                directory = child
            yield directory
        finally:
            os.close(directory)

    @staticmethod
    def _filename(storage_key: str) -> str:
        match = _KEY.fullmatch(storage_key)
        if match is None:
            raise ValueError("Invalid document storage key")
        return match.group(1)

    def save(self, content: bytes) -> StoredDocument:
        """Publish complete bytes atomically; a UUID collision never overwrites."""
        filename = f"{uuid4()}.bin"
        temporary = f".{uuid4()}.tmp"
        result = StoredDocument(
            storage_key=f"documents/{filename}",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        with self._documents_directory() as directory:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                # Hard-link publication is atomic and fails if the destination
                # exists. os.replace() would silently overwrite it instead.
                os.link(
                    temporary,
                    filename,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            finally:
                os.unlink(temporary, dir_fd=directory)
        return result

    def read(self, storage_key: str) -> bytes:
        filename = self._filename(storage_key)
        with self._documents_directory() as directory:
            descriptor = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "rb") as content:
                if not stat.S_ISREG(os.fstat(content.fileno()).st_mode):
                    raise ValueError("Stored document must be a regular file")
                return content.read()

    def delete(self, storage_key: str) -> None:
        filename = self._filename(storage_key)
        try:
            with self._documents_directory() as directory:
                info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Stored document must be a regular file")
                # unlink never follows a symlink if an entry changes after stat.
                os.unlink(filename, dir_fd=directory)
        except FileNotFoundError:
            pass
