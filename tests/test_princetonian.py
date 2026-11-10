"""The princetonian adapter against a mocked site. The records are made up, in the API's shape."""

import datetime as dt
import json

import pytest
import responses

from xdfetch.adapters import princetonian as adapter
from xdfetch.http import FetchError, NotFound

DAY = dt.date(2026, 10, 30)
ID = "test-mini-1"
RECORD = {
    "id": ID,
    "title": "Test Mini",
    "date": "2026-10-30T00:00:00+00:00",
    "author_ids": ["a1"],
    "description": "",
}
CLUES = [
    {"answer": "CAT", "clue": "Café pet", "direction": "across", "x": 0, "y": 0},
    {"answer": "BOW", "clue": "Ribbon knot", "direction": "across", "x": 0, "y": 2},
    {"answer": "CAB", "clue": "Taxi", "direction": "down", "x": 0, "y": 0},
    {"answer": "TOW", "clue": "Pull a barge", "direction": "down", "x": 2, "y": 0},
]
AUTHORS = [{"id": "a1", "first_name": "Test", "last_name": "Constructor"}]
LIST = f"{adapter.BASE}/api/crosswords"
PUZZLE = f"{adapter.BASE}/api/crosswords/{ID}"


def mock_puzzle():
    responses.add(responses.GET, PUZZLE, json=RECORD)
    responses.add(responses.GET, PUZZLE + "/clues", json=CLUES)
    responses.add(responses.GET, PUZZLE + "/authors", json=AUTHORS)


@responses.activate
def test_list_then_three_answers_in_one_file(registry, http):
    older = {**RECORD, "id": "older", "date": "2026-10-29T00:00:00+00:00"}
    responses.add(
        responses.GET,
        LIST,
        json=[RECORD, older],
        match=[responses.matchers.query_param_matcher({"mini": "true"})],
    )
    mock_puzzle()
    a = adapter.PrincetonianAdapter(registry["dailyprincetonian.mini"], http)
    (t,) = a.targets(DAY)
    assert t.filename == "dailyprincetonian.mini-2026-10-30.json"
    assert t.url == PUZZLE
    assert "Test Mini" in t.note
    got = a.fetch(t)
    assert got.url == PUZZLE
    assert json.loads(got.data) == {"crossword": RECORD, "clues": CLUES, "authors": AUTHORS}
    assert list(json.loads(got.data)) == ["crossword", "clues", "authors"]
    # the list is read once per run
    assert a.targets(dt.date(2026, 10, 29))[0].url.endswith("/older")
    assert len(responses.calls) == 4


@responses.activate
def test_full_size_asks_for_mini_false(registry, http):
    responses.add(responses.GET, LIST, json=[], match=[responses.matchers.query_param_matcher({"mini": "false"})])
    a = adapter.PrincetonianAdapter(registry["dailyprincetonian.daily"], http)
    with pytest.raises(NotFound):
        a.targets(DAY)


@responses.activate
def test_a_list_that_is_not_a_list_is_an_error(registry, http):
    responses.add(responses.GET, LIST, json={"error": "down for maintenance"})
    a = adapter.PrincetonianAdapter(registry["dailyprincetonian.mini"], http)
    with pytest.raises(FetchError) as e:
        a.targets(DAY)
    assert not isinstance(e.value, NotFound)


@responses.activate
def test_a_part_that_is_not_json_is_an_error(registry, http):
    responses.add(responses.GET, PUZZLE, json=RECORD)
    responses.add(responses.GET, PUZZLE + "/clues", body="<html>oops</html>")
    a = adapter.PrincetonianAdapter(registry["dailyprincetonian.mini"], http)
    with pytest.raises(FetchError, match="not JSON"):
        a.fetch(adapter.Target(url=PUZZLE, filename="dailyprincetonian.mini-2026-10-30.json"))
