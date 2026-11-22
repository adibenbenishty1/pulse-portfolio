"""Synchronous statistics for UTF-8 text documents."""

from typing import TypedDict


class TextStatistics(TypedDict):
    word_count: int
    line_count: int
    character_count: int


def analyze_text(doc_bytes: bytes) -> TextStatistics:
    """Count whitespace-separated words, split lines, and Unicode characters.

    Whitespace and line endings count as characters. Empty text has zero lines;
    a trailing line ending does not add an extra line. Invalid UTF-8 raises
    UnicodeDecodeError.
    """
    text = doc_bytes.decode("utf-8")
    return {
        "word_count": len(text.split()),
        "line_count": len(text.splitlines()),
        "character_count": len(text),
    }
