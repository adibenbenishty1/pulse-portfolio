"""Minimal storage contract for immutable document bytes."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    size_bytes: int
    sha256: str


class DocumentStorage(Protocol):
    def save(self, content: bytes) -> StoredDocument:
        """Store new content at a fresh key, owned exclusively by this save call.

        Never return an existing key; callers may delete this key on failure.
        """
        ...

    def read(self, storage_key: str) -> bytes:
        """Retrieve the original bytes, or raise FileNotFoundError if absent."""
        ...

    def delete(self, storage_key: str) -> None:
        """Delete content for internal compensation; absent files raise FileNotFoundError."""
        ...
