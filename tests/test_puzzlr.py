"""PZLR (The Wall Street Journal): the puzzlr adapter against a mocked API, and the puzzlr
converter. The levels are made up (FIVE, in the API's shape); never use real, published
puzzles here."""

import datetime as dt
import json

import pytest
import responses
from synthetic import FIVE, FIVE_CIRCLE, FIVE_XD_GRID_AND_CLUES, five_value

from xdfetch import convert
from xdfetch.adapters import puzzlr as adapter
from xdfetch.convert import puzzlr as converter
from xdfetch.http import FetchError, NotFound

PRINT_DATE = dt.date(2026, 10, 29)  # a Thursday; PZLR files it under the 28th
LEVEL = "https://api.puzzlr.net/trpc/crossword.getLevel"
PROMPT = "The answer to this week's contest is a bird found in the grid."
EXPLANATION = "The contest answer is DRAKE. It is 1-Across."
CLUES = {
    ("across", 1): "<i>Male</i> duck, with “quotes”",
    ("across", 4): "Fossil resin — café colour",
    ("across", 5): "Handbills",
    ("down", 1): "Small fairy-tale miner",
    ("down", 2): "Monastery",
    ("down", 3): "Mistakes…",
}
ANSWERS = {
    ("across", 1): "DRAKE",
    ("across", 4): "AMBER",
    ("across", 5): "FLYERS",
    ("down", 1): "DWARF",
    ("down", 2): "ABBEY",
    ("down", 3): "ERRORS",
}


def as_json(body: list) -> bytes:
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def level(new: bool = True, contest: bool = True) -> list:
    """A level in the API's shape: the 2026 format (circles, rebus squares) or the older one
    (neither, and the copyright as `description`)."""
    numbers = {(0, 0): 1, (0, 2): 2, (0, 4): 3, (2, 0): 4, (4, 0): 5}
    grid = []
    for r in range(5):
        row = []
        for c in range(5):
            if FIVE[r][c] == "#":
                row.append({"answer": "", "isBlack": True})
                continue
            cell: dict = {"answer": five_value(r, c) if new else five_value(r, c)[0], "isBlack": False}
            if (r, c) in numbers:
                cell["clueNumber"] = numbers[(r, c)]
            if new:
                cell["isCircled"] = (r, c) == FIVE_CIRCLE
            row.append(cell)
        grid.append(row)
    d: dict = {
        "id": "test-level-1",
        "title": "Birds of a Feather",
        "author": "By Ann Setter & Bo Second/Edited by Cy Editor",
        "subtitle": "Thursday",
        "date": "2026-10-28",
        "width": 5,
        "height": 5,
        "grid": grid,
        "clues": {
            dirn: [
                {
                    "number": n,
                    "text": t,
                    "answer": ANSWERS[(dd, n)] if new else ANSWERS[(dd, n)].replace("RS", "R"),
                    "direction": dirn,
                }
                for (dd, n), t in CLUES.items()
                if dd == dirn
            ]
            for dirn in ("across", "down")
        },
    }
    if not new:
        d["description"] = "© The Wall Street Journal"
    if contest:
        d.update(contestMode=True, contestClueText=PROMPT, contestAnswer=EXPLANATION)
    return [{"result": {"data": {"id": 0, "date": "2026-10-28", "shortId": "test0000", "data": d}}}]


RAW = as_json(level())

EXPECTED = (
    """\
Title: Birds of a Feather
Author: Ann Setter and Bo Second
Editor: Cy Editor
Copyright: © The Wall Street Journal
Date: 2026-10-29
Special: circle
Rebus: 1=RS
Meta: The answer to this week's contest is a bird found in the grid. ~ DRAKE


"""
    + FIVE_XD_GRID_AND_CLUES
    + "\n\n"
    + PROMPT
    + "\n"
)


def ctx(registry, date=PRINT_DATE):
    return convert.Context("wsj.daily", date, "f", params=registry["wsj.daily"].params)


# --- the adapter ---


@responses.activate
def test_fetch_by_date_with_offset(registry, http):
    responses.add(responses.GET, LEVEL, body=RAW)
    a = adapter.PuzzlrAdapter(registry["wsj.daily"], http)
    (t,) = a.targets(PRINT_DATE)
    assert t.filename == "wsj.daily-2026-10-29.json"
    assert t.url == (
        LEVEL + "?batch=1&input=%7B%220%22%3A%7B%22tenant%22%3A%22wsj%22%2C%22date%22%3A%222026-10-28%22%7D%7D"
    )
    assert "2026-10-28" in t.note
    assert a.fetch(t).data == RAW
    assert "1 day(s) before" in a.describe()


@responses.activate
def test_unscheduled_is_a_miss(registry, http):
    responses.add(responses.GET, LEVEL, json=[{"result": {"data": {"unavailable": True, "reason": "not_scheduled"}}}])
    a = adapter.PuzzlrAdapter(registry["wsj.daily"], http)
    with pytest.raises(NotFound, match="not_scheduled"):
        a.fetch(a.targets(PRINT_DATE)[0])


@responses.activate
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<html>", "not a tRPC level"),
        ('{"error": "x"}', "not a tRPC level"),
        ('[{"result": {"data": {"data": {"title": "no grid"}}}}]', "no grid"),
    ],
)
def test_other_answers_are_errors(registry, http, body, message):
    responses.add(responses.GET, LEVEL, body=body)
    a = adapter.PuzzlrAdapter(registry["wsj.daily"], http)
    with pytest.raises(FetchError, match=message):
        a.fetch(a.targets(PRINT_DATE)[0])


def test_registry_row(registry):
    o = registry["wsj.daily"]
    assert o.adapter == "puzzlr"
    assert o.params == {"tenant": "wsj", "offset": "-1", "copyright": "© The Wall Street Journal"}
    assert o.days == frozenset(range(6))


# --- the converter ---


def test_sniff_and_fixture(registry):
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "puzzlr"
    fmt, p = convert.convert(RAW, ctx(registry))
    assert fmt == "puzzlr"
    assert p.tricky == [f"contest explanation not carried (it names the answer): {EXPLANATION}"]
    assert p.check() == []
    assert p.to_xd() == EXPECTED


def test_old_payload_copyright_and_date_checks(registry):
    raw = as_json(level(new=False, contest=False))
    _, p = convert.convert(raw, ctx(registry, dt.date(2026, 10, 30)))
    assert p.headers["Copyright"] == "© The Wall Street Journal"
    assert "Meta" not in p.headers
    assert "Special" not in p.headers
    assert "Rebus" not in p.headers
    assert p.grid[4] == "FLYER"
    assert p.tricky == [
        "payload says Thursday, file dated Friday 2026-10-30",
        "payload date is 2026-10-28, file dated 2026-10-30 (offset -1)",
    ]


def test_copyright_from_the_row_when_the_payload_has_none():
    _, p = convert.convert(RAW, convert.Context("x", None, "f", params={"copyright": "© Example"}))
    assert p.headers["Copyright"] == "© Example"
    _, p = convert.convert(RAW, convert.Context("x", None, "f"))
    assert "Copyright" not in p.headers


def test_contest_without_answers_is_an_x_placeholder(registry):
    body = level()
    d = body[0]["result"]["data"]["data"]
    for row in d["grid"]:
        for cell in row:
            cell["answer"] = ""
    for cl in d["clues"]["across"] + d["clues"]["down"]:
        cl["answer"] = ""
    d["contestDeadlineAt"] = "2026-11-01T23:59"
    d.pop("contestAnswer")  # the explanation comes with the answers, after the deadline
    _, p = convert.convert(as_json(body), ctx(registry))
    assert all(set(row) <= {"X", "#"} for row in p.grid)
    assert "X" in p.grid[0]
    assert all(set(c.answer) == {"X"} for c in p.clues)
    assert p.check() == []
    assert "Meta" not in p.headers
    assert p.tricky == ["answers withheld until 2026-11-01T23:59: X placeholders until a re-fetch has them"]
    assert p.notes == PROMPT


def test_contest_oddities():
    body = level()
    d = body[0]["result"]["data"]["data"]
    d["contestAnswer"] = "Congratulations to the winners."
    _, p = convert.convert(as_json(body), convert.Context("x", None, "f"))
    assert "contest puzzle: no answer found in the payload" in p.tricky
    d["contestClueText"] = ""
    _, p = convert.convert(as_json(body), convert.Context("x", None, "f"))
    assert "contest puzzle: no prompt in the payload" in p.tricky


def test_answer_mismatch_and_empty_square():
    body = level(contest=False)
    d = body[0]["result"]["data"]["data"]
    d["clues"]["down"][0]["answer"] = "DWARX"
    d["grid"][2][2]["answer"] = ""
    _, p = convert.convert(as_json(body), convert.Context("x", None, "f"))
    assert "D1: clue answer DWARX differs from grid DWARF" in p.review
    assert "empty square at row 2 col 2" in p.review


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b'[{"result": {"data": {}}}]',
        json.dumps([{"result": {"data": {"data": {"grid": [[]], "width": 5, "height": 5}}}}]).encode(),
    ],
)
def test_not_a_level(data):
    with pytest.raises(convert.ConvertError):
        converter.convert(data, convert.Context("x", None, "f"))


def test_split_author():
    assert converter.split_author("By Ann Setter/Edited by Cy Editor") == ("Ann Setter", "Cy Editor")
    assert converter.split_author("by Di Setter/Ed. Cy Editor") == ("Di Setter", "Cy Editor")
    assert converter.split_author("Solo Setter") == ("Solo Setter", "")
