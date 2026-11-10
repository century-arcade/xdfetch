"""The ipuz converter, beyond the tiny puzzle in test_convert."""

import datetime as dt
import json

import pytest
from conftest import make_ipuz

from xdfetch import convert, xd
from xdfetch.convert import ipuz

DAY = dt.date(2026, 10, 28)


def run(d: dict) -> xd.Puzzle:
    fmt, p = convert.convert(json.dumps(d, ensure_ascii=False).encode(), convert.Context("x", DAY, "f"))
    assert fmt == "ipuz"
    return p


def test_full_output():
    d = make_ipuz()
    d["intro"] = "Edited by Cy Editor"
    d["notes"] = "A note."
    assert run(d).to_xd() == (
        "Title: Tiny\nAuthor: A. Setter\nEditor: Cy Editor\nCopyright: © 2026 Nobody\nDate: 2026-10-28\n\n\n"
        "CAT\nA#O\nBOW\n\n\n"
        "A1. Café pet ~ CAT\nA3. Ribbon knot ~ BOW\n\nD1. Taxi ~ CAB\nD2. Pull a barge ~ TOW\n\n\nA note.\n"
    )


def test_circles_rebus_and_styles():
    d = make_ipuz()
    d["puzzle"][0][0] = {"cell": 1, "style": {"shapebg": "circle"}}
    d["puzzle"][2][2] = {"cell": 0, "style": {"barred": "R", "highlight": True}}
    d["solution"][0][2] = {"value": "TE"}
    d["solution"][2][0] = "BB"
    d["solution"][0][0] = "CC"  # circled: a lowercase letter key
    p = run(d)
    assert p.grid == ["aA1", "A#O", "2OW"]
    assert p.headers["Special"] == "circle"
    assert p.headers["Rebus"] == "a=CC 1=TE 2=BB"
    assert [c.answer for c in p.clues] == ["CCATE", "BBOW", "CCABB", "TEOW"]
    assert "bar R at row 2 col 2" in p.tricky
    assert "highlight True at row 2 col 2" in p.tricky


def test_clue_forms_and_numbering_trouble():
    d = make_ipuz()
    d["puzzle"][0][2] = 5  # the file numbers this square differently
    d["clues"]["Across"] = [
        {"number": 1, "clue": "<I>Café</I> pet", "answer": "CAT"},
        ["x", "No number"],
        [9, "No slot"],
        "junk",
    ]
    p = run(d)
    assert p.clues[0].text == "{/Café/} pet"
    assert p.review == [
        "the outlet's cell numbers differ from standard numbering at row 0 col 2",
        "A clue with no number: No number",
        "A9: clue has no slot in the grid",
    ]
    assert "a clue carries its own answer key; the grid's is used" in p.tricky


def test_empty_square_needs_review():
    d = make_ipuz()
    d["solution"][1][0] = None
    p = run(d)
    assert p.grid[1] == " #O"
    assert p.review == ["empty square at row 1 col 0"]


def test_bare_copyright_is_dropped_and_ampersand_joins():
    d = make_ipuz()
    d["copyright"] = "©"
    d["author"] = "Ann Setter & Bo Second"
    p = run(d)
    assert "Copyright" not in p.headers
    assert p.headers["Author"] == "Ann Setter and Bo Second"


@pytest.mark.parametrize("change", ["no clues", "wrong size", "not json"])
def test_broken(change):
    d = make_ipuz()
    if change == "no clues":
        d["clues"] = {}
    elif change == "wrong size":
        d["dimensions"]["width"] = 4
    data = b'{"ipuz.org" "puzzle" "solution"' if change == "not json" else json.dumps(d).encode()
    with pytest.raises(convert.ConvertError):
        ipuz.convert(data, convert.Context())
