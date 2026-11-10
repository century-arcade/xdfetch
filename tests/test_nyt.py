"""The nytjson converter (the New York Times's v6 puzzle JSON)."""

import datetime as dt

import pytest
from synthetic import NYT_XD, as_bytes, nyt

from xdfetch import convert
from xdfetch.convert import nytjson as converter

YESTERDAY = dt.date(2026, 10, 28)
RAW = as_bytes(nyt())


def test_sniff_and_fixture():
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "nytjson"
    fmt, p = convert.convert(RAW, convert.Context("nyt", YESTERDAY, "nyt-2026-10-28.json"))
    assert fmt == "nytjson"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == NYT_XD


def test_clue_text():
    assert converter.clue_text({"plain": "a “b”"}) == ('a "b"', False)
    assert converter.clue_text({"formatted": "<b>Bold</b> and <em> spaced </em>!"}) == (
        "{*Bold*} and {/spaced/} !",
        False,
    )
    assert converter.clue_text({"formatted": '<img src="x" alt="a cat"> seen', "plain": "x"}) == ("[a cat] seen", True)
    assert converter.clue_text({"formatted": '<img src="x" alt="">', "plain": "Picture of a dog"}) == (
        "[Picture of a dog]",
        True,
    )


def test_title_and_shading_and_notes():
    d = nyt()
    d["title"] = "Sunday Puzzle"
    for c in d["body"][0]["cells"]:
        if c.get("type") == 2:
            c["type"] = 3
    d["body"][0]["overlays"] = {"afterSolve": "x"}
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", YESTERDAY, "f"))
    assert p.headers["Title"] == "Sunday Puzzle"
    assert p.headers["Special"] == "shaded"
    assert any("animation over the grid (afterSolve)" in t for t in p.tricky)


def test_circles_and_shading_together():
    d = nyt()
    d["body"][0]["cells"][0]["type"] = 3
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", YESTERDAY, "f"))
    assert p.headers["Special"] == "circle"
    assert p.grid[0] == "DRAKE"
    assert p.tricky == ["circles and shading together: 1 shaded squares kept as plain ones, the circles lowercase"]


def test_empty_square_and_two_readings():
    d = nyt()
    cells = d["body"][0]["cells"]
    cells[1]["answer"] = ""  # R, in 1-Across only
    cells[1]["moreAnswers"] = {"valid": ["R"]}
    cells[3]["answer"] = "K"
    cells[3]["moreAnswers"] = {"valid": ["K/Z"]}
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", YESTERDAY, "f"))
    joined = "\n".join(p.tricky)
    assert "1 squares the answer leaves empty" in joined
    assert "(R)" in joined
    assert "two readings" in joined
    assert "K/Z for K" in joined
    # both mean the .xd is probably wrong: a person must look
    assert len(p.review) == 2
    assert all(r in p.tricky for r in p.review)
    assert p.grid[0] == "D1AKE"
    assert p.headers["Rebus"] == "1= 2=RS"
    assert p.clues[0].answer == "DRAKE"


def test_digit_square_keeps_its_digit():
    d = nyt()
    d["body"][0]["cells"][24]["answer"] = "7"
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", YESTERDAY, "f"))
    assert p.headers["Rebus"] == "7=7"
    assert p.grid[4] == "FLYE7"


def test_symbol_square_and_picture_clue():
    d = nyt()
    cells = d["body"][0]["cells"]
    cells[24]["answer"] = "&"
    cells[24]["moreAnswers"] = {"valid": ["AND"]}  # the word the symbol also stands for
    cells[0]["answer"] = "@"
    d["body"][0]["clues"][1]["text"] = [{"plain": "A bird", "formatted": '<img src="x" alt="a duck">'}]
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", YESTERDAY, "f"))
    assert p.headers["Rebus"] == "1=@ 2=AND"
    assert "symbol squares @ as Rebus keys" in p.tricky
    assert "picture clues 4A: the picture's description, in brackets" in p.tricky
    assert p.clues[1].text == "[a duck]"


def test_date_mismatch_and_numbering():
    d = nyt()
    d["body"][0]["clues"][0]["label"] = "2"
    _, p = convert.convert(as_bytes(d), convert.Context("nyt", dt.date(2026, 10, 29), "f"))
    assert "payload publicationDate is 2026-10-28, file dated 2026-10-29" in p.tricky
    assert "clues xd's numbering doesn't give the same squares: 2A" in p.review


def test_not_a_puzzle():
    with pytest.raises(convert.ConvertError):
        converter.convert(b"not json", convert.Context("nyt", YESTERDAY, "f"))
    with pytest.raises(convert.ConvertError):
        converter.convert(b'{"publicationDate": "2026-10-28", "body": []}', convert.Context("nyt", YESTERDAY, "f"))
