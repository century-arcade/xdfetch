"""King Features on GameDistribution's feed: the gamedist adapter against a mocked feed, the
ccjson converter, and the King params of ccxml. The puzzle is made up (FOUR, in the shape the
feed serves); never use real, published puzzles here."""

import datetime as dt

import pytest
import responses
from synthetic import CCXML, CCXML_XD, FOUR, as_bytes

from xdfetch import convert
from xdfetch.adapters import gamedist as adapter
from xdfetch.convert import ccjson, ccxml
from xdfetch.http import FetchError, NotFound

DAY = dt.date(2026, 10, 9)
FEED = "https://crosswords-sgweb.gamedistribution.com/feed/hearst_thomas-joseph-crossword"
LISTING = f"{FEED}/year/2026/month/10"
STORAGE = "https://crosswords-sgweb.gamedistribution.com/storage/hearst_thomas-joseph-crossword/"
JOSEPH = "kingfeatures.thomas-joseph"

CLUES = {
    "Across": [
        ("1", "1", "Small jump — or a bunny’s move"),
        ("5", "4", "“ Wise” herb"),  # a space after the opening quote mark, as King's files have
        ("7", "5", "Mash"),
        ("8", "6", "Pub pour"),
    ],
    "Down": [
        ("2", "1", "Drag"),
        ("3", "2", "Eye – stare"),
        ("4", "3", "Energy"),
        ("6", "4", "Resort"),
    ],
}
WORDS = [("1", "2-4", "1"), ("2", "2", "1-4"), ("3", "3", "1-4"), ("4", "4", "1-3")]
WORDS += [("5", "1-4", "2"), ("6", "1", "2-4"), ("7", "1-4", "3"), ("8", "1-3", "4")]


def king(creator: str = "Thomas Joseph Crossword", date: str = "2026-10-09") -> dict:
    """A King Features puzzle as GameDistribution's feed serves it: the feed's record in
    `metaData`, and the Crossword Compiler document as xml2js makes it under `data`. Its title
    is King's own, the date; its creator names only the feature."""
    numbers = {(1, 2): 1, (1, 3): 2, (1, 4): 3, (2, 1): 4, (3, 1): 5, (4, 1): 6}  # (y, x), 1-based
    cells = []
    for x in range(1, 5):
        for y in range(1, 5):
            ch = FOUR[y - 1][x - 1]
            attrs = {"x": str(x), "y": str(y)}
            if ch == "#":
                attrs["type"] = "block"
            else:
                attrs["solution"] = ch
                if (y, x) in numbers:
                    attrs["number"] = str(numbers[(y, x)])
            cells.append({"$": attrs})
    return {
        "metaData": {
            "author": creator,
            "title": "October 09, 2026",
            "date": date,
            "feedSlug": "hearst_thomas-joseph-crossword",
            "format": "HEARST",
            "id": "00000000-0000-4000-8000-000000000001",
        },
        "data": {
            "$": {"xmlns": "http://crossword.info/xml/rectangular-puzzle", "alphabet": "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
            "metadata": [
                {
                    "title": ["October 09, 2026"],
                    "creator": [creator],
                    "copyright": ["© 2026 King Features Syndicate, Inc."],
                    "description": [""],
                }
            ],
            "crossword": [
                {
                    "grid": [
                        {
                            "$": {"width": "4", "height": "4"},
                            "grid-look": [{"$": {"numbering-scheme": "normal"}}],
                            "cell": cells,
                        }
                    ],
                    "word": [{"$": {"id": i, "x": x, "y": y}} for i, x, y in WORDS],
                    "clues": [
                        {
                            "$": {"ordering": "normal"},
                            "title": [{"b": [title]}],
                            "clue": [{"_": text, "$": {"word": w, "number": n}} for w, n, text in clues],
                        }
                        for title, clues in CLUES.items()
                    ],
                }
            ],
        },
    }


RAW = as_bytes(king())

# what the converter writes for king() with kingfeatures.thomas-joseph's params
EXPECTED = """\
Title: October 09, 2026
Author: Thomas Joseph
Copyright: © 2026 King Features Syndicate, Inc.
Date: 2026-10-09


#HOP
SAGE
PULP
ALE#


A1. Small jump -- or a bunny's move ~ HOP
A4. "Wise" herb ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. Drag ~ HAUL
D2. Eye - stare ~ OGLE
D3. Energy ~ PEP
D4. Resort ~ SPA

"""


def ctx(registry, oid=JOSEPH, day=DAY):
    return convert.Context(oid, day, "f", params=registry[oid].params)


# --- the gamedist adapter ---


def listing(*days):
    return [{"author": "Thomas Joseph Crossword", "date": d, "feedUrl": f"{STORAGE}{d}.json"} for d in days]


@responses.activate
def test_listing_then_file(registry, http):
    responses.add(responses.GET, LISTING, json=listing("2026-10-08", "2026-10-09"))
    responses.add(responses.GET, f"{STORAGE}2026-10-09.json", body=RAW)
    a = adapter.GameDistAdapter(registry[JOSEPH], http)
    (t,) = a.targets(DAY)
    assert t.filename == "kingfeatures.thomas-joseph-2026-10-09.json"
    assert t.url == f"{STORAGE}2026-10-09.json"
    assert a.fetch(t).data == RAW
    a.targets(dt.date(2026, 10, 8))  # the month's listing is read once
    assert len(responses.calls) == 2
    assert "month/<M>" in a.describe()


@responses.activate
def test_date_not_listed_is_a_miss(registry, http):
    responses.add(responses.GET, LISTING, json=listing("2026-10-08"))
    with pytest.raises(NotFound):
        adapter.GameDistAdapter(registry[JOSEPH], http).targets(DAY)


@responses.activate
def test_listing_not_as_expected(registry, http):
    responses.add(responses.GET, LISTING, body="<html>")
    with pytest.raises(FetchError, match="not JSON"):
        adapter.GameDistAdapter(registry[JOSEPH], http).targets(DAY)
    responses.replace(responses.GET, LISTING, json={"error": "x"})
    with pytest.raises(FetchError, match="not a list"):
        adapter.GameDistAdapter(registry[JOSEPH], http).targets(DAY)


def test_registry_rows(registry):
    joseph, sheffer, premier = (
        registry[f"kingfeatures.{s}"] for s in ("thomas-joseph", "eugene-sheffer", "premier-sunday")
    )
    assert joseph.adapter == sheffer.adapter == premier.adapter == "gamedist"
    assert joseph.params == {
        "feed": "hearst_thomas-joseph-crossword",
        "author": "Thomas Joseph",
        "dash": "--",
        "endash": "-",
        "quotes": "repair",
    }
    assert sheffer.params["author"] == "Eugene Sheffer"
    assert sheffer.params["feed"] == "hearst_eugene-sheffer-crossword"
    assert "author" not in premier.params
    assert "endash" not in premier.params
    assert joseph.days == sheffer.days == frozenset(range(6))
    assert premier.days == frozenset({6})


# --- sniffing ---


def test_sniff():
    assert ccjson.sniff(RAW)
    assert not ccxml.sniff(RAW)
    assert ccxml.sniff(CCXML)
    assert not ccjson.sniff(CCXML)
    assert convert.detect(RAW) == "ccjson"
    assert convert.detect(CCXML) == "ccxml"


# --- the JSON form, through ccxml.build() ---


def test_fixture(registry):
    fmt, p = convert.convert(RAW, ctx(registry))
    assert fmt == "ccjson"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == EXPECTED


def test_same_puzzle_as_the_xml():
    """Without params, the JSON form gives what the same document as XML gives."""
    p = convert.convert(RAW, convert.Context("x", DAY, "f"))[1]
    assert p.grid == FOUR
    assert p.headers["Author"] == "Thomas Joseph Crossword"
    assert p.headers["Title"] == "October 09, 2026"
    assert [c.answer for c in p.clues] == ["HOP", "SAGE", "PULP", "ALE", "HAUL", "OGLE", "PEP", "SPA"]
    assert next(c.text for c in p.clues if c.number == 2) == "Eye – stare"


def test_dropped_clue_is_tricky_and_placeholdered(registry):
    """King's file drops a clue beginning "Down" and leaves its number on the clue before."""
    d = king()
    across = d["data"]["crossword"][0]["clues"][0]["clue"]
    dropped = across.pop(1)  # A4
    across[0]["_"] += " " + dropped["$"]["number"]
    _, p = convert.convert(as_bytes(d), ctx(registry))
    assert p.tricky == ["A4: no clue in the file; its number is on the end of A1"]
    assert "A4. [XXX] ~ SAGE" in p.to_xd()


def test_unbalanced_quotes_are_tricky(registry):
    raw = RAW.replace("“ Wise” herb".encode(), "“Didn’t I tell you?".encode())
    _, p = convert.convert(raw, ctx(registry))
    assert p.tricky == ["A4: unbalanced quotation marks: \"Didn't I tell you?"]
    assert p.review == []


def test_feed_date_differs(registry):
    _, p = convert.convert(RAW, ctx(registry, day=dt.date(2026, 10, 10)))
    assert p.tricky == ["the feed dates this puzzle 2026-10-09, filed as 2026-10-10"]


def test_byline_from_creator_line(registry):
    raw = as_bytes(king(creator="Premier Crossword by Ann Setter"))
    _, p = convert.convert(raw, ctx(registry, "kingfeatures.premier-sunday"))
    assert p.headers["Author"] == "Ann Setter"
    assert p.headers["Title"] == "October 09, 2026"  # King's own title, the date
    assert "A1. Small jump -- or a bunny's move ~ HOP" in p.to_xd()
    assert "D2. Eye – stare ~ OGLE" in p.to_xd()  # premier-sunday keeps the en dash


def test_markup_xml2js_kept_apart_is_tricky():
    d = king()
    d["data"]["crossword"][0]["clues"][0]["clue"][2] = {
        "_": "Mash, ",
        "i": ["perhaps"],
        "$": {"word": "7", "number": "5"},
    }
    _, p = convert.convert(as_bytes(d), convert.Context("x", DAY, "f"))
    assert p.tricky == ["A5: clue markup (i) out of place"]
    assert next(c.text for c in p.clues if (c.direction, c.number) == ("A", 5)) == "Mash, perhaps"


@pytest.mark.parametrize(
    "data", [b"{", b'{"data": {"crossword": [], "rectangular-puzzle": 1, "$": 1}}', b'{"data": [], "$": 1}']
)
def test_not_a_document(data):
    with pytest.raises(convert.ConvertError):
        ccjson.convert(data, convert.Context("x", DAY, "f"))


@pytest.mark.parametrize("review", [False, True])
def test_quote_notes_keep_their_place_among_review_notes(review):
    """An unbalanced-quote note comes right after its own clue's review notes, before the next clue's."""
    d = king()
    across = d["data"]["crossword"][0]["clues"][0]["clue"]
    across[0]["_"] = "“ Unbalanced"
    across[1]["_"] = "“Also unbalanced"
    if review:
        across[1]["$"]["number"] = "9"  # the file's numbering differs from the grid's
    _, p = convert.convert(as_bytes(d), convert.Context("x", DAY, "f", params={"quotes": "repair"}))
    expected = ['A1: unbalanced quotation marks: "Unbalanced']
    if review:
        expected.append("A9: the file's numbering differs from the grid's")
    expected.append(f'A{9 if review else 4}: unbalanced quotation marks: "Also unbalanced')
    assert p.tricky[: len(expected)] == expected
    assert p.clues[0].text == '"Unbalanced'


# --- the King params on the XML form, and the Arkadium rows untouched ---


def test_params_on_xml():
    raw = CCXML.replace(b">Mash<", "> Cat — or kitten – <".encode())
    params = {"dash": "--", "endash": "-", "author": "A. Byline"}
    _, p = convert.convert(raw, convert.Context("x", DAY, "f", params=params))
    assert "A5. Cat -- or kitten - ~ PULP" in p.to_xd()
    assert p.headers["Author"] == "A. Byline"


def test_arkadium_rows_unchanged(registry):
    _, p = convert.convert(CCXML, convert.Context("arkadium.mini", DAY, "f", params=registry["arkadium.mini"].params))
    assert p.to_xd() == CCXML_XD
