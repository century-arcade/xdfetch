import json

import pytest
from conftest import AUTHOR, COPYRIGHT, EXPECTED_CLUES, SOLUTION, TITLE, make_ipuz, make_puz

from xdfetch.formats import ConvertError, convert, identify


def format_name(data: bytes) -> str | None:
    fmt = identify(data)
    return fmt.name if fmt else None


def check(xd: str) -> None:
    assert f"Title: {TITLE}\n" in xd
    assert f"Author: {AUTHOR}\n" in xd
    assert f"Copyright: {COPYRIGHT}\n" in xd
    assert "\n".join(SOLUTION) in xd
    for clue in EXPECTED_CLUES:
        assert clue in xd


def test_puz(puz_bytes):
    assert format_name(puz_bytes) == "puz"
    check(convert(puz_bytes, "tiny.puz"))


def test_puz_circle():
    xd = convert(make_puz(circle_first=True), "tiny.puz")
    assert "Special: circle\n" in xd
    assert "cAT\nA#O\nBOW" in xd  # a circled square is lowercase


def test_ipuz(ipuz_bytes):
    assert format_name(ipuz_bytes) == "ipuz"
    check(convert(ipuz_bytes, "tiny.ipuz"))


def test_ipuz_jsonp(ipuz_bytes):
    wrapped = b"ipuz(" + ipuz_bytes + b")"
    assert format_name(wrapped) == "ipuz"
    check(convert(wrapped, "tiny.ipuz"))


def test_format_by_content_not_extension(puz_bytes):
    check(convert(puz_bytes, "puzzle.json"))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<html><body>Subscribe to keep reading</body></html>",
        b'{"kind": ["http://ipuz.org/sudoku#1"]}',
        b"[1, 2, 3]",
    ],
)
def test_not_a_puzzle(data):
    assert identify(data) is None
    with pytest.raises(ConvertError, match="not a puzzle format"):
        convert(data, "x")


def test_broken_ipuz():
    broken = make_ipuz()
    del broken["dimensions"]
    with pytest.raises(ConvertError, match="not a valid ipuz"):
        convert(json.dumps(broken).encode(), "broken.ipuz")


def test_broken_puz(puz_bytes):
    with pytest.raises(ConvertError, match="not a valid puz"):
        convert(puz_bytes[:60], "broken.puz")
