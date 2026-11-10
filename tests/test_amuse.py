"""The amuse adapter against a mocked Amuse Labs player, and the amuse converter. The
player's pages and the puzzle are made up (synthetic.amuse)."""

import base64
import datetime as dt
import io
import json
import zipfile

import pytest
import responses
from conftest import NOW, YESTERDAY, present
from synthetic import AMUSE_XD, amuse, amuse_ms, as_bytes

from xdfetch import adapters, convert, fetch
from xdfetch import registry as reg
from xdfetch.adapters import amuse as adapter
from xdfetch.convert import amuse as converter
from xdfetch.http import FetchError, NotFound
from xdfetch.ledger import Ledger
from xdfetch.store import LocalStore

RAW = as_bytes(amuse())
HOST = "https://lat.amuselabs.com/lat"
TOKEN = "eyJ0eXAiOiJKV1QifQ.token.sig"
LAT = "latimes.daily"


def picker_page(puzzles, set_name="latimes"):
    """A date picker: its params carry the load token and the recent puzzles (id, title, publishTime)."""
    sps = base64.b64encode(json.dumps({"loadToken": TOKEN, "set": set_name}).encode()).decode()
    streak = [
        {
            "puzzleDetails": {
                "puzzleId": pid,
                "title": title,
                "publicationTime": ts,
                "publicationTimeZone": "America/New_York",
            },
            "series": set_name,
        }
        for pid, title, ts in puzzles
    ]
    params = json.dumps({"rawsps": sps, "streakInfo": streak})
    return f'<html><head><script type="application/json" id="params">{params}</script></head></html>'


def puzzle_page(text, key=(5, 7, 3, 11, 2, 9, 4)):
    """A crossword page: its params carry the puzzle as rawc, scrambled with the key."""
    params = json.dumps({"rawc": adapter.scramble(text, list(key)), "puzzleId": "x"})
    head = f'<title>Crossword</title><script type="application/json" id="params">{params}</script>'
    return f"<html><head>{head}</head></html>"


# --- the scrambled payload ---


def test_scramble_roundtrip():
    text = RAW.decode()
    for key in ([2, 3, 4, 5, 6, 7, 8], [20, 2, 19, 3, 18, 4, 17]):
        rawc = adapter.scramble(text, key)
        assert rawc != base64.b64encode(RAW).decode()
        assert adapter.unscramble_with_key(rawc, key) == text
        assert adapter.unscramble(rawc) == text
    assert adapter.unscramble("not base64 at all!!") is None
    assert adapter.unscramble("") is None


def test_fvlt():
    # 32-bit character sums XORed: with an empty uid it's just set ^ id
    assert adapter.fvlt("latimes", "tca261028", "") == format(
        sum(map(ord, "latimes")) ^ sum(map(ord, "tca261028")), "x"
    )
    assert adapter.fvlt("latimes", "tca261028", "abc-123") == format(
        sum(map(ord, "latimes")) ^ sum(map(ord, "tca261028")) ^ sum(map(ord, "abc-123")), "x"
    )


# --- the adapter ---


def test_registered_as_builtin():
    assert adapters.get("amuse") is adapter.AmuseAdapter


@responses.activate
def test_fetch_with_dated_id(registry, http):
    responses.add(
        responses.GET,
        f"{HOST}/date-picker?set=latimes",
        body=picker_page([("tca261028", "t", amuse_ms(YESTERDAY))]),
    )
    responses.add(
        responses.GET,
        f"{HOST}/crossword",  # a registered query string would have to match exactly
        body=puzzle_page(RAW.decode()),
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
    a = adapter.AmuseAdapter(registry[LAT], http)
    http.session(HOST).cookies.set("uid", "abc-123")  # what the picker's Set-Cookie does live
    (t,) = a.targets(YESTERDAY)
    assert t.url == f"{HOST}/crossword?id=tca261028&set=latimes"
    assert t.filename == "tca261028.json"
    got = a.fetch(t)
    assert got.data == RAW
    assert got.url == t.url  # the recorded URL carries no tokens
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_without_uid_sends_no_fvlt(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(
        responses.GET,
        f"{HOST}/crossword",
        body=puzzle_page(RAW.decode()),
        match=[responses.matchers.query_param_matcher({"id": "tca261028", "set": "latimes", "loadToken": TOKEN})],
    )
    a = adapter.AmuseAdapter(registry[LAT], http)
    assert a.fetch(a.targets(YESTERDAY)[0]).data == RAW


@responses.activate
def test_rawc_as_a_script_variable(registry, http):
    """Some player pages set window.rawc in a script instead of carrying it in params."""
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    rawc = adapter.scramble(RAW.decode(), [3, 4, 5, 6, 7, 8, 9])
    body = f"<script id=\"params\">{{}}</script><script>window.rawc = '{rawc}';</script>"
    responses.add(responses.GET, f"{HOST}/crossword", body=body)
    a = adapter.AmuseAdapter(registry[LAT], http)
    assert a.fetch(a.targets(YESTERDAY)[0]).data == RAW


@responses.activate
def test_fetch_with_picker_lookup(registry, http):
    day = dt.date(2026, 10, 28)
    responses.add(
        responses.GET,
        "https://cdn3.amuselabs.com/tdb/date-picker?set=tdb",
        body=picker_page(
            [("1111aaaa", "Thu", amuse_ms(day + dt.timedelta(days=1))), ("2222bbbb", "Wed", amuse_ms(day))], "tdb"
        ),
    )
    a = adapter.AmuseAdapter(registry["dailybeast.daily"], http)
    assert a.targets(day)[0].filename == "2222bbbb.json"
    with pytest.raises(NotFound, match="2026-10-28 to 2026-10-29"):
        a.targets(day - dt.timedelta(days=5))
    assert len(responses.calls) == 1  # the picker is fetched once per adapter


@responses.activate
def test_picker_with_two_puzzles_on_a_date_takes_the_first(registry, http, caplog):
    day = dt.date(2026, 10, 28)
    responses.add(
        responses.GET,
        "https://cdn3.amuselabs.com/tdb/date-picker?set=tdb",
        body=picker_page([("aaaa1111", "One", amuse_ms(day)), ("bbbb2222", "Two", amuse_ms(day))], "tdb"),
    )
    a = adapter.AmuseAdapter(registry["dailybeast.daily"], http)
    assert a.targets(day)[0].filename == "aaaa1111.json"
    assert "2 puzzles dated 2026-10-28" in caplog.text


@responses.activate
def test_picker_without_token_is_an_error(registry, http):
    responses.add(
        responses.GET,
        f"{HOST}/date-picker?set=latimes",
        body='<script id="params">{"streakInfo": []}</script>',
    )
    a = adapter.AmuseAdapter(registry[LAT], http)
    with pytest.raises(FetchError, match="no rawsps"):
        a.fetch(a.targets(YESTERDAY)[0])


@responses.activate
def test_page_without_params_is_an_error(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body="<html>no params</html>")
    a = adapter.AmuseAdapter(registry[LAT], http)
    with pytest.raises(FetchError, match='no <script id="params">'):
        a.fetch(a.targets(YESTERDAY)[0])


@responses.activate
def test_error_page_is_not_found(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", body="<html><head><title>PuzzleMe Error</title></head></html>")
    a = adapter.AmuseAdapter(registry[LAT], http)
    with pytest.raises(NotFound):
        a.fetch(a.targets(YESTERDAY)[0])


@responses.activate
def test_page_without_rawc_and_garbage_rawc_are_errors(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", body='<script id="params">{"puzzleId": "x"}</script>')
    a = adapter.AmuseAdapter(registry[LAT], http)
    (t,) = a.targets(YESTERDAY)
    with pytest.raises(FetchError, match="no rawc"):
        a.fetch(t)
    responses.replace(responses.GET, f"{HOST}/crossword", body='<script id="params">{"rawc": "!!!"}</script>')
    with pytest.raises(FetchError, match="could not unscramble"):
        a.fetch(t)


@responses.activate
def test_redirect_means_token_rejected(registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", status=302, headers={"Location": "https://www.example.com/games"})
    responses.add(responses.GET, "https://www.example.com/games", body="<html>games</html>")
    a = adapter.AmuseAdapter(registry[LAT], http)
    with pytest.raises(FetchError, match="redirected"):
        a.fetch(a.targets(YESTERDAY)[0])


@responses.activate
def test_id_from_page_and_set_with_space(registry, http):
    page = "https://www.vulture.com/article/daily-crossword-puzzle-october-7-2026.html"
    responses.add(
        responses.GET,
        page,
        body='<iframe src="https://cdn3.amuselabs.com/nymag/crossword?id&#x3D;0a1b2c3d&amp;set&#x3D;nymag-vulture%2010x10">',
    )
    a = adapter.AmuseAdapter(registry["vulture.daily"], http)
    (t,) = a.targets(dt.date(2026, 10, 7))
    assert t.url == "https://cdn3.amuselabs.com/nymag/crossword?id=0a1b2c3d&set=nymag-vulture%2010x10"
    assert t.filename == "0a1b2c3d.json"
    assert responses.calls[0].request.url == page


@responses.activate
def test_page_without_the_sets_embed_is_an_error(registry, http):
    page = "https://www.vulture.com/article/daily-crossword-puzzle-october-7-2026.html"
    responses.add(
        responses.GET, page, body='<iframe src="https://cdn3.amuselabs.com/nymag/crossword?id=0a1b2c3d&set=other">'
    )
    a = adapter.AmuseAdapter(registry["vulture.daily"], http)
    with pytest.raises(FetchError, match="no nymag-vulture 10x10 embed"):
        a.targets(dt.date(2026, 10, 7))


@responses.activate
def test_undated_fallback_page_only_when_it_names_the_date(registry, http):
    dated = "https://www.vulture.com/article/daily-crossword-puzzle-october-30-2026.html"
    undated = "https://www.vulture.com/article/daily-crossword-puzzle.html"
    embed = (
        '<iframe src="https://cdn3.amuselabs.com/nymag/crossword?id&#x3D;4e5f6a7b&amp;set&#x3D;nymag-vulture%2010x10">'
    )
    responses.add(responses.GET, dated, status=404)
    responses.add(responses.GET, undated, body=f"<title>A Made-Up Puzzle &mdash; October 30</title>{embed}")
    a = adapter.AmuseAdapter(registry["vulture.daily"], http)
    (t,) = a.targets(dt.date(2026, 10, 30))
    assert t.url == "https://cdn3.amuselabs.com/nymag/crossword?id=4e5f6a7b&set=nymag-vulture%2010x10"
    assert [c.request.url for c in responses.calls] == [dated, undated]

    # the undated page shows some other day: the date is missing ("October 3" is not October 30)
    responses.replace(responses.GET, undated, body=f"<title>Another Puzzle &mdash; October 3</title>{embed}")
    with pytest.raises(NotFound, match="isn't titled October 30"):
        a.targets(dt.date(2026, 10, 30))


@responses.activate
def test_missing_page_without_fallback_is_not_found(tmp_path, http):
    f = tmp_path / "o.tsv"
    f.write_text(
        "id\tadapter\tparams\n"
        "example.daily\tamuse\thost=https://cdn.example.com/x set=ex page=https://example.com/%Y/%m/%d/\n",
        encoding="utf-8",
    )
    outlet = reg.from_files([f])["example.daily"]
    responses.add(responses.GET, "https://example.com/2026/10/28/", status=404)
    with pytest.raises(NotFound):
        adapter.AmuseAdapter(outlet, http).targets(YESTERDAY)


@responses.activate
def test_run_end_to_end(tmp_path, registry, http):
    responses.add(responses.GET, f"{HOST}/date-picker?set=latimes", body=picker_page([]))
    responses.add(responses.GET, f"{HOST}/crossword", body=puzzle_page(RAW.decode()))
    store = LocalStore(tmp_path)
    report = fetch.run(registry, store, YESTERDAY, YESTERDAY, [LAT], http=http, now=NOW)
    assert [r.status for r in report.results] == ["ok"]
    e = Ledger.load(store).entries[0]
    assert e.filename == f"{LAT}/tca261028.json"
    assert e.source_url == f"{HOST}/crossword?id=tca261028&set=latimes"
    with zipfile.ZipFile(io.BytesIO(present(store.get(f"downloads/2026/{report.archive_name}")))) as z:
        notes = z.read("NOTES.md").decode()
        assert z.read(f"{LAT}/tca261028.json") == RAW
    assert "set `latimes` on `lat.amuselabs.com`" in notes
    assert "unscrambled" in notes


def test_rows(registry):
    rows = [o for o in registry.outlets if o.adapter == "amuse"]
    assert len(rows) == 11
    for o in rows:
        assert o.param("host").startswith("https://")
        assert o.param("set")
    assert registry["dailybeast.daily"].days == reg.parse_days("sun-thu")
    assert registry["crosswordclub.daily"].params["id"] == "crossword-club_%Y%m%d"
    assert registry["walrus.weekly"].tz == "America/Toronto"


# --- the converter ---


def test_sniff_and_convert():
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "amuse"
    fmt, p = convert.convert(RAW, convert.Context(LAT, YESTERDAY, "tca261028.json"))
    assert fmt == "amuse"
    assert p.check() == []
    assert p.tricky == []
    assert p.to_xd() == AMUSE_XD


def test_split_author():
    assert converter.split_author("Ann Setter / Ed. Cy Editor") == ("Ann Setter", "Cy Editor")
    assert converter.split_author("Ann Setter / Edited by Cy Editor") == ("Ann Setter", "Cy Editor")
    assert converter.split_author("Ann Setter, edited by Cy Editor") == ("Ann Setter", "Cy Editor")
    assert converter.split_author("Ann Setter") == ("Ann Setter", "")
    assert converter.normalise_author("By A & B") == "A and B"


def test_tricky_cases():
    d = amuse()
    d["cellInfos"].append({"x": 0, "y": 0, "bgColor": "#ccc"})
    d["cellInfos"].append({"x": 1, "y": 1, "rightWall": True})
    d["cellInfos"].append({"x": 3, "y": 0, "isVoid": True})
    d["box"][1][2] = ""
    d["placedWords"][0]["clue"]["clue"] = 'See <a href="https://example.com/">this</a>'
    d["publishTime"] = amuse_ms(YESTERDAY + dt.timedelta(days=3))
    _, p = convert.convert(as_bytes(d), convert.Context(LAT, YESTERDAY, "f"))
    joined = "\n".join(p.tricky)
    assert "both circled and shaded" in joined
    assert "bar at row 1 col 1" in joined
    assert "void cell at row 0 col 3" in joined
    assert "empty square at row 2 col 1" in joined
    assert "A1: link in clue" in joined
    assert "publishTime is 2026-10-31" in joined
    assert p.clues[0].text == "See this"
    assert p.grid[2][1] == " "
    assert p.grid[0][0] == "d"  # the shaded square, kept as a circle


def test_shaded_only_and_a_marked_rebus():
    d = amuse()
    d["cellInfos"] = [{"x": 4, "y": 4, "bgColor": "#ccc"}]  # the rebus square
    _, p = convert.convert(as_bytes(d), convert.Context(LAT, YESTERDAY, "f"))
    assert p.headers["Special"] == "shaded"
    assert p.headers["Rebus"] == "a=RS"
    assert p.grid[4] == "FLYEa"
    assert p.grid[2] == "AMBER"
    assert p.tricky == []


def test_unusual_puzzles_need_review():
    d = amuse()
    d["puzzleType"] = "ACROSTIC"
    d["unlinkGridAndClues"] = True
    d["placedWords"][1]["clueSection"] = "Bonus"
    _, p = convert.convert(as_bytes(d), convert.Context(LAT, YESTERDAY, "f"))
    joined = "\n".join(p.tricky)
    assert "puzzleType is ACROSTIC" in joined
    assert "unlinkGridAndClues" in joined
    assert "clue sections: Bonus" in joined


def test_not_amuse():
    with pytest.raises(convert.ConvertError):
        converter.convert(b'{"box": [], "placedWords": []}', convert.Context(LAT, YESTERDAY, "f"))
    with pytest.raises(convert.ConvertError, match="not JSON"):
        converter.convert(b'{"box": "placedWords"', convert.Context())
    assert not converter.sniff(b"<crossword/>")


def test_untitled_puzzle_is_titled_by_date_and_block_marks_are_styling():
    d = amuse()
    d["title"] = ""
    d["cellInfos"] = [{"x": 1, "y": 1, "bgColor": "#000"}, {"x": 0, "y": 0, "fgColor": "#151515"}]
    _, p = convert.convert(as_bytes(d), convert.Context("vox.daily", YESTERDAY, "f"))
    assert p.headers["Title"] == "October 28, 2026"
    assert "Special" not in p.headers
    assert p.tricky == []


def test_no_author_is_tricky_not_an_error():
    d = amuse()
    d["title"] = d["author"] = d["copyright"] = ""
    _, p = convert.convert(as_bytes(d), convert.Context("vox.daily", YESTERDAY, "f"))
    assert p.check() == []
    assert "Author" not in p.headers
    assert "Copyright" not in p.headers
    assert p.tricky == ["no author in the source"]
    assert "Author:" not in p.to_xd()


def test_publish_offset():
    d = amuse()
    d["publishTime"] = amuse_ms(YESTERDAY - dt.timedelta(days=1))
    _, p = convert.convert(as_bytes(d), convert.Context("vulture.daily", YESTERDAY, "f"))
    assert any("publishTime" in t for t in p.tricky)
    ctx = convert.Context("vulture.daily", YESTERDAY, "f", params={"publish_offset": "-1"})
    _, p = convert.convert(as_bytes(d), ctx)
    assert p.tricky == []


def test_row_params_editor_title_drop_and_copyright_year(registry):
    params = registry["defector.weekly"].params
    editor = params["editor"]
    monday = dt.date(2026, 10, 19)
    base = {
        **amuse(),
        "title": "Bird Words",
        "author": "Ann Setter & Bo Builder",
        "copyright": "2026",
        "description": "",
        "publishTime": amuse_ms(monday),
        "publishTimeZone": "UTC",
    }

    def headers(**changes):
        ctx = convert.Context("defector.weekly", monday, "f", params=params)
        _, p = convert.convert(as_bytes({**base, **changes}), ctx)
        assert p.tricky == []
        return p.headers

    h = headers()
    assert h["Editor"] == editor
    assert h["Copyright"] == "© 2026"
    assert h["Author"] == "Ann Setter and Bo Builder"
    assert headers(title="Bird Words (Themeless)")["Title"] == "Bird Words"
    # the editor's own puzzle has no editor; a byline that names one keeps it
    assert "Editor" not in headers(author=f"{editor} & Ann Setter")
    assert headers(author="Ann Setter / Ed. Cy Editor")["Editor"] == "Cy Editor"
    assert headers(copyright="(c) 2025")["Copyright"] == "© 2025"
    assert headers(copyright="© 2026 Ann Setter")["Copyright"] == "© 2026 Ann Setter"
    assert headers(copyright="© Ann Setter")["Copyright"] == "© 2026 Ann Setter"
    assert "Copyright" not in headers(copyright="")
    # without the params the payload's line is kept as served
    _, p = convert.convert(as_bytes(base), convert.Context(LAT, monday, "f"))
    assert p.headers["Copyright"] == "2026"
    assert "Editor" not in p.headers
