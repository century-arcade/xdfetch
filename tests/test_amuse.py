"""The amuse adapter against a mocked player. The puzzle is made up, in the player's shape."""

import base64
import datetime as dt
import json

import pytest
import responses

from xdfetch.adapters import amuse as adapter
from xdfetch.http import FetchError, NotFound

HOST = "https://lat.amuselabs.com/lat"
TOKEN = "eyJ0eXAiOiJKV1QifQ.token.sig"
DAY = dt.date(2026, 10, 28)

PUZZLE = {
    "title": "Tiny Times, Wed, Oct 28, 2026",
    "subtitle": "",
    "description": "A made-up puzzle for the tests.",
    "author": "A. Setter / Ed. B. Editor",
    "copyright": "© 2026 Nobody",
    "id": "tca261028",
    "puzzleType": "CROSSWORD",
    "publishTime": 1793160000000,
    "w": 3,
    "h": 3,
    "box": [["C", "A", "B"], ["A", "\u0000", "O"], ["T", "O", "W"]],
    "cellInfos": [{"x": 0, "y": 0, "isCircled": True}],
    "placedWords": [
        {"clue": {"clue": "Café pet"}, "word": "CAT", "x": 0, "y": 0, "acrossNotDown": True, "clueNum": 1},
        {"clue": {"clue": "Ribbon knot"}, "word": "BOW", "x": 0, "y": 2, "acrossNotDown": True, "clueNum": 3},
        {"clue": {"clue": "Taxi"}, "word": "CAB", "x": 0, "y": 0, "acrossNotDown": False, "clueNum": 1},
        {"clue": {"clue": "Pull a barge"}, "word": "TOW", "x": 2, "y": 0, "acrossNotDown": False, "clueNum": 2},
    ],
}
RAW = json.dumps(PUZZLE, ensure_ascii=False)


def picker_page(puzzles):
    sps = base64.b64encode(json.dumps({"loadToken": TOKEN, "set": "latimes"}).encode()).decode()
    streak = [
        {
            "puzzleDetails": {
                "puzzleId": pid,
                "title": title,
                "publicationTime": ts,
                "publicationTimeZone": "America/New_York",
            },
            "series": "latimes",
        }
        for pid, title, ts in puzzles
    ]
    params = json.dumps({"rawsps": sps, "streakInfo": streak})
    return f'<html><head><script type="application/json" id="params">{params}</script></head></html>'


def puzzle_page(text, key=(5, 7, 3, 11, 2, 9, 4)):
    params = json.dumps({"rawc": adapter.scramble(text, list(key)), "puzzleId": "x"})
    head = f'<title>Tiny Times</title><script type="application/json" id="params">{params}</script>'
    return f"<html><head>{head}</head></html>"


def ms(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt.UTC).timestamp() * 1000)


def test_scramble_roundtrip():
    for key in ([2, 3, 4, 5, 6, 7, 8], [20, 2, 19, 3, 18, 4, 17]):
        rawc = adapter.scramble(RAW, key)
        assert adapter.unscramble_with_key(rawc, key) == RAW
        assert adapter.unscramble(rawc) == RAW
    assert adapter.unscramble("not base64 at all!!") is None


def test_fvlt():
    # 32-bit char sums XORed: with an empty uid it's just set ^ id
    assert adapter.fvlt("latimes", "tca261028", "") == format(
        sum(map(ord, "latimes")) ^ sum(map(ord, "tca261028")), "x"
    )


@responses.activate
def test_fetch_with_dated_id(registry, http):
    responses.add(
        responses.GET,
        f"{HOST}/date-picker?set=latimes",
        body=picker_page([("tca261028", "t", ms(DAY))]),
    )
    responses.add(
        responses.GET,
        f"{HOST}/crossword",  # a registered query string would have to match exactly
        body=puzzle_page(RAW),
        match=[
            responses.matchers.query_param_matcher(
                {
                    "id": "tca261028",
                    "set": "latimes",
                    "loadToken": TOKEN,
                    "fvlt": adapter.fvlt("latimes", "tca261028", "abc-123"),
                }
            )
        ],
    )
    a = adapter.AmuseAdapter(registry["lat"], http)
    http.session(HOST).cookies.set("uid", "abc-123")  # what the picker's Set-Cookie does live
    targets = a.targets(DAY)
    assert targets[0].url == f"{HOST}/crossword?id=tca261028&set=latimes"
    assert targets[0].filename == "tca261028.json"
    got = a.fetch(targets[0])
    assert got.data == RAW.encode("utf-8")
    assert got.url == targets[0].url  # the URL returned carries no tokens
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_with_picker_lookup(registry, http):
    responses.add(
        responses.GET,
        "https://cdn3.amuselabs.com/tdb/date-picker?set=tdb",
        body=picker_page([("fb57c251", "Thu", ms(DAY + dt.timedelta(days=1))), ("7c58a74a", "Weds", ms(DAY))]),
    )
    a = adapter.AmuseAdapter(registry["db"], http)
    assert a.targets(DAY)[0].filename == "7c58a74a.json"
    with pytest.raises(NotFound):
        a.targets(DAY - dt.timedelta(days=5))
    assert len(responses.calls) == 1  # the picker is fetched once per adapter


@responses.activate
def test_error_page_is_not_found(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", body="<html><head><title>PuzzleMe Error</title></head></html>")
    a = adapter.AmuseAdapter(registry["lat"], http)
    with pytest.raises(NotFound):
        a.fetch(a.targets(DAY)[0])


@responses.activate
def test_redirect_means_token_rejected(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", status=302, headers={"Location": "https://www.latimes.com/games"})
    responses.add(responses.GET, "https://www.latimes.com/games", body="<html>games</html>")
    a = adapter.AmuseAdapter(registry["lat"], http)
    with pytest.raises(FetchError, match="redirected"):
        a.fetch(a.targets(DAY)[0])


def test_registry_rows(registry):
    for pubid in ("lat", "latmidi", "atl", "nw", "db", "cwc", "cwct", "vox", "vult", "wal", "dfctr"):
        o = registry[pubid]
        assert o.adapter == "amuse"
        assert o.param("host").startswith("https://")
        assert o.param("set")
    assert registry["db"].days == frozenset({6, 0, 1, 2, 3})
    assert registry["cwc"].params["id"] == "crossword-club_%Y%m%d"
    assert registry["ucs"].adapter == "url"
    assert registry["ucs"].days == frozenset({6})


EMBED_5DE = (
    '<iframe src="https://cdn3.amuselabs.com/nymag/crossword?id&#x3D;5de50453&amp;set&#x3D;nymag-vulture%2010x10">'
)
EMBED_687 = (
    '<iframe src="https://cdn3.amuselabs.com/nymag/crossword?id&#x3D;687688b3&amp;set&#x3D;nymag-vulture%2010x10">'
)


@responses.activate
def test_id_from_page_and_set_with_space(registry, http):
    page = "https://www.vulture.com/article/daily-crossword-puzzle-october-7-2026.html"
    responses.add(responses.GET, page, body=EMBED_5DE)
    a = adapter.AmuseAdapter(registry["vult"], http)
    (t,) = a.targets(dt.date(2026, 10, 7))
    assert t.url == "https://cdn3.amuselabs.com/nymag/crossword?id=5de50453&set=nymag-vulture%2010x10"
    assert t.filename == "5de50453.json"
    assert responses.calls[0].request.url == page


@responses.activate
def test_undated_fallback_page_only_when_it_names_the_date(registry, http):
    # a puzzle that ran only at the undated address: the page's title dates it
    dated = "https://www.vulture.com/article/daily-crossword-puzzle-october-30-2026.html"
    undated = "https://www.vulture.com/article/daily-crossword-puzzle.html"
    responses.add(responses.GET, dated, status=404)
    responses.add(responses.GET, undated, body=f"<title>The Tiny Puzzle &mdash; October 30</title>{EMBED_687}")
    a = adapter.AmuseAdapter(registry["vult"], http)
    (t,) = a.targets(dt.date(2026, 10, 30))
    assert t.url == "https://cdn3.amuselabs.com/nymag/crossword?id=687688b3&set=nymag-vulture%2010x10"
    assert [c.request.url for c in responses.calls] == [dated, undated]

    # the undated page shows some other day: the date is missing ("October 3" is not October 30)
    responses.replace(responses.GET, undated, body=f"<title>The Other Puzzle &mdash; October 3</title>{EMBED_687}")
    with pytest.raises(NotFound, match="isn't titled October 30"):
        a.targets(dt.date(2026, 10, 30))
