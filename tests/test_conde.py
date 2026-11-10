"""The conde converter (Condé Nast's puzzle service record)."""

import datetime as dt
import json

import pytest
from synthetic import CONDE_XD, as_bytes, conde

from xdfetch import convert
from xdfetch.convert import conde as converter

YESTERDAY = dt.date(2026, 10, 28)
RAW = as_bytes(conde())


def test_sniff_and_fixture():
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "conde"
    fmt, p = convert.convert(RAW, convert.Context("tny", YESTERDAY, "tny-2026-10-28.json"))
    assert fmt == "conde"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == CONDE_XD


def test_sniff_wants_a_record_that_starts_with_its_id():
    assert not converter.sniff(as_bytes({"data": conde()["data"]}))


def test_mini_title_and_help():
    d = conde()
    d["data"] = (
        d["data"]
        .replace("title: The Crossword:", "title: The Mini Crossword:")
        .replace("subtitle: Today’s theme: Birds.\n", "")
    )
    d["data"] += "\n## Help\n\n<div>A blurb about the <b>series</b>.</div>\n"
    _, p = convert.convert(as_bytes(d), convert.Context("tnymini", YESTERDAY, "f"))
    assert p.headers["Title"] == "Wednesday, October 28, 2026"
    assert p.tricky == ["Help text not carried: A blurb about the series."]


def test_shading_and_answer_mismatch():
    d = conde()
    d["data"] = d["data"].replace("O { background: circle }", "O { background: circle }\nS { background: #ccc }")
    d["data"] = d["data"].replace("\n.....\n.#.#.\n..O..", "\nS....\n.#.#.\n..O..")
    d["data"] = d["data"].replace("~ DWARF", "~ DWARX")
    _, p = convert.convert(as_bytes(d), convert.Context("tny", YESTERDAY, "f"))
    assert "both circled and shaded" in p.tricky[0]
    assert "D1: clue answer DWARX differs from grid DWARF" in p.tricky
    assert p.grid[0] == "dRAKE"


def test_clue_lines_that_dont_fit():
    d = conde()
    d["data"] = d["data"].replace("A5. Handbills ~ FLYERS", "A5. Handbills ~ FLYERS\nA9. No such slot ~ X\nnonsense")
    _, p = convert.convert(as_bytes(d), convert.Context("tny", YESTERDAY, "f"))
    assert p.review == ["A9: clue has no slot in the grid", "clue line not understood: nonsense"]


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        json.dumps({"id": "x", "data": "## Metadata\n\ntitle: t\n"}).encode(),
        json.dumps({"id": "x", "data": "## Grid\n\nAB\nC\n\n## Clues\n\nA1. x ~ AB\n"}).encode(),
    ],
)
def test_not_a_puzzle(data):
    with pytest.raises(convert.ConvertError):
        converter.convert(data, convert.Context("tny", YESTERDAY, "f"))


def test_theme_of():
    assert converter.theme_of("Today’s theme: Carry-on items.") == "Carry-on items"
    assert converter.theme_of("Today's theme: And so on...") == "And so on..."
    assert converter.theme_of("") == ""
