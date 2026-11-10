"""The princetonian converter (the Daily Princetonian's crossword API)."""

import datetime as dt

import pytest
from synthetic import PRINCETONIAN_XD, as_bytes, princetonian

from xdfetch import convert
from xdfetch.convert import princetonian as converter

DAY = dt.date(2026, 10, 30)
RAW = as_bytes(princetonian())


def ctx(id="prncmini"):
    return convert.Context(id, DAY, f"{id}-2026-10-30.json")


def changed(**parts):
    return as_bytes({**princetonian(), **parts})


def test_sniff_and_fixture():
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "princetonian"
    fmt, p = convert.convert(RAW, ctx())
    assert fmt == "princetonian"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == PRINCETONIAN_XD


def test_authors_in_the_records_order():
    three = [*princetonian()["authors"], {"first_name": "Third", "id": "x", "last_name": "Person"}]
    _, p = convert.convert(changed(authors=three), ctx())
    assert p.headers["Author"] == "Bo Second, Ann Setter and Third Person"
    _, p = convert.convert(changed(authors=[]), ctx())
    assert "Author" not in p.headers
    assert p.tricky == ["no author"]
    assert p.review == []


def test_crossing_answers_that_disagree_need_review():
    clues = princetonian()["clues"]
    clues[4]["answer"] = "HOUL"  # D1, crossing A4's circled A
    _, p = convert.convert(changed(clues=clues), ctx())
    assert p.review == ["square at row 1 col 1 is A one way and O the other"]


def test_a_short_answer_and_a_slot_without_a_clue_need_review():
    clues = princetonian()["clues"]
    clues[2]["answer"] = "PUL"  # A5 stops short of the P that D3 puts there
    del clues[4]  # D1, whose squares the across answers still fill
    _, p = convert.convert(changed(clues=clues), ctx())
    assert p.review == ["A5: answer PUL is not the whole slot", "D1 has no clue"]


def test_odd_characters_and_a_clue_off_the_numbering():
    clues = princetonian()["clues"]
    clues[3]["answer"] = "AL!"
    clues.append({"answer": "UL", "clue": "Stray", "is_across": True, "x": 1, "y": 2})
    _, p = convert.convert(changed(clues=clues), ctx())
    assert p.review == [
        "answer 'AL!' has '!' at row 3 col 2",
        "square at row 3 col 2 is ! one way and E the other",
        "A clue 'Stray' at row 2 col 1 doesn't start a numbered slot",
    ]


def test_a_date_mismatch_is_tricky_not_review():
    _, p = convert.convert(RAW, convert.Context("prncmini", dt.date(2026, 10, 31), "f"))
    assert p.tricky == ["the record is dated 2026-10-30, file dated 2026-10-31"]
    assert p.review == []


def test_not_a_puzzle():
    with pytest.raises(convert.ConvertError):
        convert.convert(changed(clues=[]), ctx())
    with pytest.raises(convert.ConvertError):
        converter.convert(b'{"crossword": {}}', ctx())
