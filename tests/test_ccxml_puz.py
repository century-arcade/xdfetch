"""Crossword Compiler XML (ccxml) and Across Lite (puz), in the shapes Arkadium's feeds serve."""

import datetime as dt
import struct

import pytest
from synthetic import CCXML, CCXML_XD, FOUR_PUZ_XD, four_puz, puz_section

from xdfetch import convert
from xdfetch.convert import ccxml, puz, uclick

DAY = dt.date(2026, 10, 9)
TITLE_IS_DATE = {"title": "date"}


def ctx(day=DAY, params=TITLE_IS_DATE):
    return convert.Context("arkmini", day, "f", params=params)


# --- sniffing ---


def test_sniff():
    assert ccxml.sniff(CCXML)
    assert puz.sniff(four_puz())
    assert not uclick.sniff(CCXML)  # its <crossword> is nested in <crossword-compiler>
    assert convert.detect(CCXML) == "ccxml"
    assert convert.detect(four_puz()) == "puz"
    assert not ccxml.sniff(b'{"data": {"crossword": [], "rectangular-puzzle": 1}}')  # XML only


# --- ccxml ---


def test_ccxml_fixture():
    fmt, p = convert.convert(CCXML, ctx())
    assert fmt == "ccxml"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == CCXML_XD


def test_ccxml_title_without_the_date_param():
    _, p = convert.convert(CCXML, ctx(params={}))
    assert p.headers["Title"] == "Mini Crossword"
    _, p = convert.convert(CCXML.replace(b"<title>Mini Crossword</title>", b"<title></title>"), ctx(params={}))
    assert p.headers["Title"] == "October 9, 2026"


def test_bar_between_letters_is_tricky():
    raw = CCXML.replace(b'<cell x="2" y="2" solution="A"', b'<cell x="2" y="2" solution="A" left-bar="true"')
    _, p = convert.convert(raw, ctx())
    assert p.tricky == ["cell (2, 2): a left-bar between two letters, not carried"]


def test_dropped_clue_is_tricky_and_placeholdered():
    """A file can drop a clue and leave its number on the end of the clue before."""
    raw = CCXML.replace(b'<clue word="5" number="4" format="4">Herb <i>sometimes</i> dried</clue>', b"")
    raw = raw.replace(b"Small jump</clue>", b"Small jump 4</clue>")
    _, p = convert.convert(raw, ctx())
    assert p.tricky == ["A4: no clue in the file; its number is on the end of A1"]
    assert p.review == p.tricky
    assert "A4. [XXX] ~ SAGE" in p.to_xd()


def test_byline_from_creator_line():
    raw = CCXML.replace(b"<creator>Ann Setter</creator>", b"<creator>Sunday Crossword by Ann Setter</creator>")
    _, p = convert.convert(raw, ctx())
    assert p.headers["Author"] == "Ann Setter"


def test_circles_and_rebus():
    raw = CCXML.replace(b'<cell x="2" y="1" solution="H"', b'<cell x="2" y="1" solution="H" background-shape="circle"')
    raw = raw.replace(b'<cell x="4" y="1" solution="P"', b'<cell x="4" y="1" solution="PS"')
    _, p = convert.convert(raw, ctx())
    assert p.grid[0] == "#hO1"
    assert p.headers["Special"] == "circle"
    assert p.headers["Rebus"] == "1=PS"
    assert "A1. Small jump ~ HOPS" in p.to_xd()
    assert "D3. Energy... ~ PSEP" in p.to_xd()


def test_unknown_cell_attributes_and_wrong_way_word():
    raw = CCXML.replace(b'<cell x="3" y="1" solution="O"', b'<cell x="3" y="1" solution="O" hint="true"')
    raw = raw.replace(b'<word id="2" x="2" y="1-4"/>', b'<word id="2" x="2-4" y="1"/>')
    _, p = convert.convert(raw, ctx())
    assert "cell (3, 1): attributes xd can't carry (hint)" in p.tricky
    assert "D1: its word runs the other way" in p.review


def test_build_takes_a_document_from_elsewhere():
    """What a plugin reading another rendering of the same document hands to build()."""
    doc = ccxml.read(CCXML)
    doc["record"] = {"date": "2026-10-09"}
    doc["lost"] = ["A1: clue markup (b) out of place"]
    p = ccxml.build(doc, ctx(day=dt.date(2026, 10, 10)))
    assert p.tricky == [
        "A1: clue markup (b) out of place",
        "the feed dates this puzzle 2026-10-09, filed as 2026-10-10",
    ]
    del doc["record"], doc["lost"]
    assert ccxml.build(doc, ctx()).to_xd() == CCXML_XD


@pytest.mark.parametrize(
    "raw",
    [
        b'<?xml version="1.0"?><crossword-compiler><rectangular-puzzle/></crossword-compiler>',
        b'<?xml version="1.0"?><crossword-compiler><rectangular-puzzle><crossword/></rectangular-puzzle>'
        b"</crossword-compiler>",
        CCXML.replace(b'<cell x="1" y="1" type="block"/>', b""),
        CCXML.replace(b'<cell x="1" y="1" type="block"/>', b'<cell x="1" y="1" type="void"/>'),
    ],
)
def test_not_a_crossword(raw):
    with pytest.raises(convert.ConvertError):
        ccxml.convert(raw, convert.Context("arkmini", DAY, "f"))


# --- puz ---


def test_puz_fixture():
    fmt, p = convert.convert(four_puz(), ctx())
    assert fmt == "puz"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == FOUR_PUZ_XD


def test_puz_title_without_the_date_param():
    _, p = convert.convert(four_puz(), ctx(params={}))
    assert p.headers["Title"] == "Mini 101"


def test_puz_rebus_and_circles():
    n = 16
    grbs = bytes(2 if i == 3 else 0 for i in range(n))  # square 3 is rebus entry 1
    gext = bytes(0x80 if i == 1 else 0 for i in range(n))
    extra = puz_section(b"GRBS", grbs) + puz_section(b"RTBL", b" 1:PS;") + puz_section(b"GEXT", gext)
    _, p = convert.convert(four_puz(extra), ctx())
    assert p.grid[0] == "#hO1"
    assert p.headers["Rebus"] == "1=PS"
    assert p.headers["Special"] == "circle"
    assert "A1. Small jump ~ HOPS" in p.to_xd()


def test_puz_other_square_flags_are_tricky():
    extra = puz_section(b"GEXT", bytes(0x10 if i == 1 else 0 for i in range(16)))
    _, p = convert.convert(four_puz(extra), ctx())
    assert p.tricky == ["GEXT square flags other than circles, not carried"]
    assert "Special" not in p.headers


def test_puz_rebus_without_its_table_entry():
    extra = puz_section(b"GRBS", bytes(5 if i == 3 else 0 for i in range(16))) + puz_section(b"RTBL", b" 1:PS;")
    with pytest.raises(convert.ConvertError, match="no entry in RTBL"):
        convert.convert(four_puz(extra), ctx())


def test_puz_scrambled_is_refused():
    raw = bytearray(four_puz())
    raw[0x32] = 4
    with pytest.raises(convert.ConvertError):
        convert.convert(bytes(raw), ctx())


def test_puz_too_few_clues():
    raw = bytearray(four_puz())
    struct.pack_into("<H", raw, 0x2E, 7)
    with pytest.raises(convert.ConvertError, match="7 clues for 8 slots"):
        convert.convert(bytes(raw), ctx())
