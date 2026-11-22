import pytest

from api.services.text_analysis import analyze_text


@pytest.mark.parametrize(
    ("text", "words", "lines", "characters"),
    [
        ("", 0, 0, 0),
        ("Hello world\nNext line", 4, 2, 21),
        ("one\r\ntwo\r\n", 2, 2, 10),
        (" \t\n\n", 0, 2, 4),
        ("שלום עולם 😊", 3, 1, 11),
    ],
)
def test_text_statistics(text: str, words: int, lines: int, characters: int) -> None:
    assert analyze_text(text.encode("utf-8")) == {
        "word_count": words,
        "line_count": lines,
        "character_count": characters,
    }


def test_invalid_utf8_is_rejected() -> None:
    with pytest.raises(UnicodeDecodeError):
        analyze_text(b"\xff")
