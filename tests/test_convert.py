"""The convert package (detection, errors), the .xd writer, and the uclick, puz and ipuz
converters on the tiny puzzles."""

import datetime as dt
import json

import pytest
from conftest import AUTHOR, COPYRIGHT, EXPECTED_CLUES, SOLUTION, TITLE, make_ipuz, make_puz
from synthetic import UCLICK, UCLICK_XD

from xdfetch import convert, xd
from xdfetch.convert import uclick

YESTERDAY = dt.date(2026, 10, 28)


def check(p: xd.Puzzle) -> None:
    text = p.to_xd()
    assert f"Title: {TITLE}\n" in text
    assert f"Author: {AUTHOR}\n" in text
    assert f"Copyright: {COPYRIGHT}\n" in text
    assert "\n".join(SOLUTION) in text
    for clue in EXPECTED_CLUES:
        assert clue in text


# --- detection ---


def test_sniff():
    assert uclick.sniff(UCLICK)
    assert not uclick.sniff(b'{"json": true}')
    assert convert.detect(UCLICK) == "uclick"
    with pytest.raises(convert.UnknownFormat):
        convert.detect(b"<html>")


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
    with pytest.raises(convert.UnknownFormat):
        convert.detect(data)
    with pytest.raises(convert.UnknownFormat):
        convert.convert(data, convert.Context(filename="x"))


def test_format_by_name():
    assert convert.convert(UCLICK, convert.Context(), fmt="uclick")[0] == "uclick"
    with pytest.raises(convert.UnknownFormat, match="no converter for 'nope'"):
        convert.convert(UCLICK, convert.Context(), fmt="nope")


def test_context_is_optional(puz_bytes):
    fmt, p = convert.convert(puz_bytes)
    assert fmt == "puz"
    assert "Date" not in p.headers


def test_builtins_are_listed():
    names = [name for name, _, _ in convert.converters()]
    assert names == ["uclick", "nytjson", "conde", "wapo", "princetonian", "ipuz", "ccxml", "puz"]


# --- uclick ---


def test_uclick_fixture_matches_expected():
    ctx = convert.Context("up", YESTERDAY, "up/fcx261028-data.xml")
    fmt, puzzle = convert.convert(UCLICK, ctx)
    assert fmt == "uclick"
    assert puzzle.check() == []
    assert puzzle.tricky == []
    assert puzzle.to_xd() == UCLICK_XD


def test_uclick_answer_mismatch_is_tricky():
    raw = UCLICK.replace(b'a="DRAKE"', b'a="DRAKX"')
    _, puzzle = convert.convert(raw, convert.Context("up", YESTERDAY, "f"))
    assert puzzle.tricky == ["A1: clue answer DRAKX differs from grid DRAKE"]
    assert puzzle.review == puzzle.tricky
    assert puzzle.clues[0].answer == "DRAKX"


def test_uclick_bad_grid():
    raw = UCLICK.replace(b'<Width v="5" />', b'<Width v="6" />')
    with pytest.raises(convert.ConvertError):
        convert.convert(raw, convert.Context("up", YESTERDAY, "f"))


def test_uclick_edited_by_in_byline():
    raw = UCLICK.replace(b'<Author v="By Ann Setter" />', b'<Author v="By Di Setter, Edited by Ed Editor" />')
    _, p = convert.convert(raw, convert.Context("ucs", YESTERDAY, "f"))
    assert p.headers["Author"] == "Di Setter"
    assert p.headers["Editor"] == "Ed Editor"
    assert p.tricky == []
    raw = UCLICK.replace(b'<Author v="By Ann Setter" />', b'<Author v="By Di Setter, Edited" />')
    _, p = convert.convert(raw, convert.Context("ucs", YESTERDAY, "f"))
    assert p.headers["Author"] == "Di Setter"
    assert p.headers["Editor"] == "Cy Editor"
    assert p.tricky
    assert "truncated" in p.tricky[0]


def test_uclick_stray_cp1252_quote_before_encoded_apostrophe():
    """A cp1252 quote kept in front of the feed's %27 ("students\x92%27 grades") must not
    come out as '' (never seen in the corpus) or as U+0092."""
    raw = UCLICK.replace(b"with an %27apostrophe%27", "the students\u0092%27 grades".encode())
    _, p = convert.convert(raw, convert.Context("up", YESTERDAY, "f"))
    a1 = [c.text for c in p.clues if c.number == 1 and c.direction == "A"]
    assert a1 == ['"Male" duck, the students\' grades']
    assert p.tricky == []


# --- the .xd writer ---


def test_typography():
    assert xd.plain("“Hi” … café x") == '"Hi" ... café x'
    assert xd.plain("em — dash stays") == "em — dash stays"
    assert xd.clue_text("<i>Rock</i> &amp; <b>roll</b><br>x") == "{/Rock/} & {*roll*} x"
    assert xd.clue_text("E=mc<sup>2</sup>") == "E=mc{^2^}"


def test_empty_markup_is_a_space():
    assert xd.clue_text('"Big"<i> </i>top') == '"Big" top'
    assert xd.clue_text("a<i></i>b") == "ab"


def test_mojibake_repair_matches_xd():
    """The same passes as xd's puz2xd.decode() / xdfile.utils (doc/character-encoding.md)."""
    assert xd.plain("students\x92 grades \x93x\x94") == 'students\' grades "x"'  # cp1252 C1
    assert xd.plain("caf\xc3\xa9 \xc3\xaale") == "café êle"  # UTF-8 read as latin-1
    assert xd.plain("Â\x92s") == "'s"  # UTF-8 C1 read as latin-1: orphan Â then the trailer
    assert xd.plain("x\x80\x94y") == "x—y"  # a UTF-8 em dash that lost its lead byte
    assert xd.plain('"abc"\x9d') == '"abc"'  # stray quote trailer
    assert xd.plain("Caf\x8e") == "Café"  # Mac Roman é, not cp1252 Ž
    assert xd.plain("Ã\x82x") == "x"  # the known stray artifact
    for keep in ("\x80", "\x98", "\x81"):  # ambiguous or undefined: left for a human
        assert keep in xd.plain(f"a{keep}b")
    p = xd.Puzzle()
    p.grid = ["AB", "CD"]
    p.clues = [xd.Clue("A", 1, "bad\x81clue", "AB")]
    p.set("Title", "t")
    p.set("Date", "2026-10-29")
    assert p.check() == ["C1 control U+0081 survives in A1"]
    p.clues = [xd.Clue("A", 1, "clue", "AB")]
    p.grid = ["A B", "CD#"]  # a space is not a grid character (xdlint XD002); caught before lint
    assert p.check() == ["grid character ' ' at row 0 col 1"]
    p.grid = ["A*", "♠D"]  # a declared rebus key is a grid character, whatever it is
    assert p.check() == ["grid character '*' at row 0 col 1"]
    p.set("Rebus", "*=AA ♠=BB")
    assert p.check() == []


def test_check_wants_title_date_and_clues():
    p = xd.Puzzle()
    assert p.check() == ["no grid"]
    p.grid = ["AB", "C"]
    assert p.check() == ["grid rows differ in length", "no clues", "no Title header", "no Date header"]


def test_numbering():
    grid = ["ABCDE", "F#G#H", "IJKLM", "N#O#P", "QRSTU"]
    n = xd.number_grid(grid)
    assert n == {
        ("A", 1): (0, 0),
        ("D", 1): (0, 0),
        ("D", 2): (0, 2),
        ("D", 3): (0, 4),
        ("A", 4): (2, 0),
        ("A", 5): (4, 0),
    }
    assert xd.answer_at(grid, "D", 0, 2) == "CGKOS"


def test_writer_layout():
    p = xd.Puzzle()
    p.grid = ["AB", "C#"]
    p.clues = [xd.Clue("D", 1, "Down", "AC"), xd.Clue("A", 1, "", "AB")]
    p.set("Date", "2026-10-29")
    p.set("Title", "  Some   title ")
    p.set("Author", "")  # empty headers are left out
    p.set("Xtra", "x")  # unknown headers go last
    assert (
        p.to_xd() == "Title: Some title\nDate: 2026-10-29\nXtra: x\n\n\nAB\nC#\n\n\nA1. [XXX] ~ AB\n\nD1. Down ~ AC\n\n"
    )
    p.notes = "A note.\n"
    assert p.to_xd().endswith("D1. Down ~ AC\n\n\nA note.\n")


# --- puz and ipuz, the tiny puzzles ---


def test_puz(puz_bytes):
    assert convert.detect(puz_bytes) == "puz"
    check(convert.convert(puz_bytes, convert.Context(filename="tiny.puz"))[1])


def test_puz_circle():
    _, p = convert.convert(make_puz(circle_first=True))
    assert p.headers["Special"] == "circle"
    assert p.grid == ["cAT", "A#O", "BOW"]  # a circled square is lowercase


def test_ipuz(ipuz_bytes):
    assert convert.detect(ipuz_bytes) == "ipuz"
    check(convert.convert(ipuz_bytes)[1])


def test_ipuz_jsonp_and_bom(ipuz_bytes):
    for wrapped in (b"ipuz(" + ipuz_bytes + b")", b"\xef\xbb\xbf" + ipuz_bytes):
        assert convert.detect(wrapped) == "ipuz"
        check(convert.convert(wrapped)[1])


def test_broken_ipuz():
    broken = make_ipuz()
    del broken["dimensions"]
    with pytest.raises(convert.ConvertError, match="not an ipuz crossword"):
        convert.convert(json.dumps(broken).encode())


def test_broken_puz(puz_bytes):
    with pytest.raises(convert.ConvertError):
        convert.convert(puz_bytes[:60])
