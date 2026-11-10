"""Puzzmo: the puzzmo adapter against a mocked team API and GraphQL, and the puzzmo
converter. The puzzles are made up (FIVE and FOUR, in Puzzmo's xd dialect and its answers'
shapes); never use real, published puzzles here."""

import datetime as dt
import json

import pytest
import responses

from xdfetch import convert
from xdfetch.adapters import puzzmo as adapter
from xdfetch.convert import puzzmo as converter
from xdfetch.http import FetchError, NotFound
from xdfetch.xd import Puzzle

SUNDAY = dt.date(2026, 10, 25)
NOV9 = dt.date(2026, 11, 9)
LIST = "https://api.puzzmo.com/team/v1/boston-globe-amlaj/queues/crossword/puzzles"
MINI_LIST = "https://api.puzzmo.com/team/v1/boston-globe-amlaj/queues/crossword-mini/puzzles"

# FIVE in Puzzmo's dialect, as a team queue serves it: a ❶ rebus key, a circle in the Design
# section, backticks around a title, curly quotes, an em dash and an ellipsis
FIVE_TEXT = """\
## Metadata

title: Bird Words
author: Ann Setter
copyright: ©2026
rebus: ❶=RS

## Grid

DRAKE
W#B#R
AMBER
R#E#O
FLYE❶


## Clues

A1. `Male` duck, with “quotes” ~ DRAKE
A4. Fossil resin — café colour ~ AMBER
A5. Handbills ~ FLYERS

D1. Small fairy-tale miner ~ DWARF
D2. Monastery ~ ABBEY
D2 ^refs: A1
D3. Mistakes… ~ ERRORS

## Design

<style>O { background: circle }</style>

.....
.#.#.
..O..
.#.#.
.....
"""

FIVE_XD = """\
Title: Bird Words
Author: Ann Setter
Copyright: © 2026 Ann Setter
Date: 2026-10-25
Special: circle
Rebus: 1=RS


DRAKE
W#B#R
AMbER
R#E#O
FLYE1


A1. "Male" duck, with "quotes" ~ DRAKE
A4. Fossil resin — café colour ~ AMBER
A5. Handbills ~ FLYERS

D1. Small fairy-tale miner ~ DWARF
D2. Monastery ~ ABBEY
D3. Mistakes... ~ ERRORS

"""

# FOUR as the Globe's mini: no Design section, named by its date
MINI_TEXT = """\
## Metadata

title: Sat, Jun 6, 2026
author: Ann Setter
copyright: © 2026

## Grid

#HOP
SAGE
PULP
ALE#

## Clues

A1. Small jump ~ HOP
A4. Herb ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. Drag ~ HAUL
D2. Eye ~ OGLE
D3. Energy ~ PEP
D4. Resort ~ SPA
"""

MINI_XD = """\
Title: Saturday, June 6, 2026
Author: Ann Setter
Copyright: © 2026 Ann Setter
Date: 2026-06-06


#HOP
SAGE
PULP
ALE#


A1. Small jump ~ HOP
A4. Herb ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. Drag ~ HAUL
D2. Eye ~ OGLE
D3. Energy ~ PEP
D4. Resort ~ SPA

"""

# FOUR as Puzzmo's own daily crossword: a split character, a hint under every clue, refs, a
# clue with a tilde of its own, a circle, a Line Breaks section, and a leftover author line
DAILY_TEXT = """\
## Metadata

title: Small Hours
author: as
date: Not set
editor: Cy Editor
copyright: © 2026
width: 4
height: 4
splitcharacter: |
hinteditor: Hy Editor

## Grid

#HOP
SAGE
PULP
ALE#

## Clues

A1. Small jump ~ HOP
A1 ^hint: Like a bunny

A4. Herb, after a ¬, ~, or ! ~ SA|GE
A4 ^hint: Wise one
A4 ^refs: D4

A5. Mash ~ PULP
A5 ^hint: Juice bits

A6. Pub pour ~ ALE
A6 ^hint: Beer

D1. Drag ~ HA|UL
D1 ^hint: Pull

D2. Eye ~ OGLE
D2 ^hint: Stare at

D3. Energy ~ PEP
D3 ^hint: Zip

D4. Resort ~ SPA
D4 ^hint: Hot springs
D4 ^refs: A4

## Design

<style>
O { background: circle }
</style>

#...
O...
....
...#

## Line Breaks

A1. nbsp:3
A4. nbsp:5 wbr:9
D4.
"""

AUTHORS = [
    {"publishingName": "settername", "username": "settername", "name": "settername", "id": "test:user1"},
    {"publishingName": "Bo Second", "username": "bo", "name": "Bo Second", "id": "test:user2"},
]


def team_answer(text: str = FIVE_TEXT, name: str = "Bird Words") -> bytes:
    """The GraphQL answer to puzzle(id:) for a team queue's puzzle."""
    rec = {"id": "test-0001:puzzle", "name": name, "puzzle": text}
    return json.dumps({"data": {"puzzle": rec}}, ensure_ascii=False).encode("utf-8")


def gameplay(text: str = DAILY_TEXT, authors=AUTHORS, name: str = "Small Hours", **more) -> bytes:
    """The play screen's answer (startOrFindGameplay) around xd text."""
    rec = {"name": name, "emoji": "🐦", "puzzle": text, "dailyTitle": "Nov 9, 2026", "author": "as"}
    rec.update(authors=list(authors), id="test-0002:puzzle", **more)
    body = {"data": {"startOrFindGameplay": {"__typename": "HasGamePlayed", "gamePlayed": {"puzzle": rec}}}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


RAW = team_answer()
DAILY = gameplay()


def queue(*days):
    return {
        "puzzles": [
            {"id": f"id-{d}:puzzle", "name": "Bird Words", "publishDate": d, "authors": [{"name": "Ann Setter"}]}
            for d in days
        ]
    }


def posted(request) -> dict:
    """The JSON body of a request the adapter made."""
    body = request.body
    assert isinstance(body, (bytes, str))
    return json.loads(body)


def ctx(oid, day, params=None):
    return convert.Context(oid, day, "f", params=params or {})


# --- team queues ---


@responses.activate
def test_list_then_graphql(registry, http):
    responses.add(
        responses.GET,
        LIST,
        json=queue("2026-10-25", "2026-10-24"),
        match=[responses.matchers.query_param_matcher({"startDate": "2026-10-25", "days": "10"})],
    )
    responses.add(responses.POST, adapter.GRAPHQL, body=RAW)
    a = adapter.PuzzmoAdapter(registry["bostonglobe.sunday"], http)
    (t,) = a.targets(SUNDAY)
    assert t.filename == "bostonglobe.sunday-2026-10-25.json"
    assert t.url == adapter.GRAPHQL
    assert "Bird Words" in t.note
    assert a.fetch(t).data == RAW
    sent = posted(responses.calls[1].request)
    assert sent["query"] == '{ puzzle(id: "id-2026-10-25:puzzle") { id name puzzle } }'
    # a date the list already covers needs no second list request
    a.targets(dt.date(2026, 10, 24))
    assert len(responses.calls) == 2
    assert "queues/crossword/puzzles" in a.describe()


@responses.activate
def test_date_not_in_queue_is_a_miss(registry, http):
    responses.add(responses.GET, LIST, json=queue("2026-10-24"))
    a = adapter.PuzzmoAdapter(registry["bostonglobe.sunday"], http)
    with pytest.raises(NotFound):
        a.targets(SUNDAY)


@responses.activate
def test_queue_and_graphql_errors(registry, http):
    responses.add(responses.GET, LIST, json={"errors": ["FORBIDDEN_TEAM"]})
    a = adapter.PuzzmoAdapter(registry["bostonglobe.sunday"], http)
    with pytest.raises(FetchError, match="queue list is not as expected"):
        a.targets(SUNDAY)
    t = adapter.Target(url=adapter.GRAPHQL, filename="f", headers={"X-Puzzle-Id": "x:puzzle"})
    responses.add(responses.POST, adapter.GRAPHQL, json={"data": {"puzzle": None}})
    with pytest.raises(NotFound, match="no puzzle text"):
        a.fetch(t)
    responses.replace(responses.POST, adapter.GRAPHQL, body="<html>")
    with pytest.raises(FetchError, match="not a puzzle"):
        a.fetch(t)


@responses.activate
def test_mini_lists_its_own_queue(registry, http):
    responses.add(responses.GET, MINI_LIST, json=queue("2026-11-04"))
    a = adapter.PuzzmoAdapter(registry["bostonglobe.mini"], http)
    (t,) = a.targets(dt.date(2026, 11, 4))
    assert t.filename == "bostonglobe.mini-2026-11-04.json"
    assert t.headers["X-Puzzle-Id"] == "id-2026-11-04:puzzle"


def test_team_registry_rows(registry):
    o = registry["bostonglobe.sunday"]
    assert o.adapter == "puzzmo"
    assert o.param("team") == "boston-globe-amlaj"
    assert o.days == frozenset({6})
    mini = registry["bostonglobe.mini"]
    assert mini.params == {"team": "boston-globe-amlaj", "queue": "crossword-mini"}
    assert mini.days == frozenset(range(7))
    assert mini.since == dt.date(2026, 6, 1)


# --- Puzzmo's own series, by date ---


def test_own_series_registry_rows(registry):
    assert registry["puzzmo.daily"].params == {"finder": "crossword"}
    assert registry["puzzmo.daily"].since == dt.date(2023, 10, 16)
    assert registry["puzzmo.mini"].params == {"finder": "crossword/mini"}
    assert registry["puzzmo.mini"].since == dt.date(2025, 10, 1)
    assert registry["puzzmo.big"].params == {"finder": "crossword/big"}
    assert registry["puzzmo.big"].days == frozenset({0})


@responses.activate
def test_gameplay_by_date(registry, http):
    responses.add(responses.POST, adapter.PLAY, body=DAILY)
    a = adapter.PuzzmoAdapter(registry["puzzmo.mini"], http)
    (t,) = a.targets(NOV9)
    assert t.filename == "puzzmo.mini-2026-11-09.json"
    assert t.url == adapter.PLAY
    assert a.fetch(t).data == DAILY
    req = responses.calls[0].request
    sent = posted(req)
    assert sent["variables"]["finderKey"] == "today:/2026-11-09/crossword/mini"
    assert "startOrFindGameplay" in sent["query"]
    assert req.headers["Puzzmo-Gameplay-Id"]
    assert "startOrFindGameplay" in a.describe()


@responses.activate
def test_gameplay_id_is_one_per_run(registry, http):
    responses.add(responses.POST, adapter.PLAY, body=DAILY)
    a = adapter.PuzzmoAdapter(registry["puzzmo.daily"], http)
    for day in (NOV9, NOV9 - dt.timedelta(days=1)):
        a.fetch(a.targets(day)[0])
    ids = {c.request.headers["Puzzmo-Gameplay-Id"] for c in responses.calls}
    assert len(ids) == 1
    assert adapter.PuzzmoAdapter(registry["puzzmo.daily"], http)._gameplay_id not in ids


@responses.activate
def test_gameplay_no_puzzle_is_a_miss(registry, http):
    answer = {"data": {"startOrFindGameplay": {"__typename": "ErrorableResponse", "message": "No puzzle found"}}}
    responses.add(responses.POST, adapter.PLAY, json=answer)
    a = adapter.PuzzmoAdapter(registry["puzzmo.big"], http)
    (t,) = a.targets(NOV9)
    with pytest.raises(NotFound, match="today:/2026-11-09/crossword/big"):
        a.fetch(t)


@responses.activate
def test_gameplay_other_errors(registry, http):
    a = adapter.PuzzmoAdapter(registry["puzzmo.daily"], http)
    (t,) = a.targets(NOV9)
    answer = {"data": {"startOrFindGameplay": {"__typename": "ErrorableResponse", "message": "Slow down"}}}
    responses.add(responses.POST, adapter.PLAY, json=answer)
    with pytest.raises(FetchError, match="Slow down"):
        a.fetch(t)
    responses.replace(responses.POST, adapter.PLAY, json={"errors": [{"message": "bad"}], "data": None})
    with pytest.raises(FetchError, match="bad"):
        a.fetch(t)
    responses.replace(responses.POST, adapter.PLAY, body="<html>")
    with pytest.raises(FetchError, match="not JSON"):
        a.fetch(t)
    empty = {"data": {"startOrFindGameplay": {"__typename": "HasGamePlayed", "gamePlayed": {"puzzle": {}}}}}
    responses.replace(responses.POST, adapter.PLAY, json=empty)
    with pytest.raises(FetchError, match="no puzzle text"):
        a.fetch(t)


# --- the converter: a team queue's answer ---


def test_sniff_and_fixture():
    assert converter.sniff(RAW)
    assert converter.sniff(DAILY)
    assert convert.detect(RAW) == "puzzmo"
    assert convert.detect(DAILY) == "puzzmo"
    fmt, p = convert.convert(RAW, ctx("bostonglobe.sunday", SUNDAY))
    assert fmt == "puzzmo"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == FIVE_XD


def test_shaded_mask_and_copyright_forms():
    text = FIVE_TEXT.replace("O { background: circle }", "O { background-light: #CCCCCC; background-dark: #444444 }")
    _, p = convert.convert(team_answer(text.replace("©2026", "© 2025 Ann Setter")), ctx("x", SUNDAY))
    assert p.headers["Special"] == "shaded"
    assert p.headers["Copyright"] == "© 2025 Ann Setter"
    assert p.grid[2] == "AMbER"
    _, p = convert.convert(team_answer(FIVE_TEXT.replace("©2026", "Puzzmo")), ctx("x", SUNDAY))
    assert p.headers["Copyright"] == "Puzzmo"


def test_date_name_is_written_out():
    raw = team_answer(MINI_TEXT, name="Sat, Jun 6, 2026")
    _, p = convert.convert(raw, ctx("bostonglobe.mini", dt.date(2026, 6, 6)))
    assert p.tricky == []
    assert p.to_xd() == MINI_XD
    # a name that is a different date from the file's is kept, and noted
    _, p = convert.convert(raw, ctx("bostonglobe.mini", dt.date(2026, 6, 7)))
    assert p.headers["Title"] == "Saturday, June 6, 2026"
    assert p.tricky == ["named 'Sat, Jun 6, 2026', file dated 2026-06-07"]
    # a real name is left alone
    assert converter.title_for("Bird Words", ctx("x", SUNDAY), Puzzle()) == "Bird Words"


@pytest.mark.parametrize(
    "data",
    [
        b'{"data": {"puzzle": {"puzzle": "## Grid"}}',
        b'{"data": {"puzzle": {"name": "no text"}}}',
        team_answer("## Metadata\n\ntitle: x\n\n## Grid\n\nAB\nC\n\n## Clues\n\nA1. x ~ AB\n"),
        team_answer("## Metadata\n\ntitle: x\n\n## Grid\n\nAB\n"),
    ],
)
def test_not_a_puzzle(data):
    with pytest.raises(convert.ConvertError):
        converter.convert(data, ctx("x", SUNDAY))


def test_clue_lines_that_dont_fit():
    text = FIVE_TEXT.replace("A5. Handbills ~ FLYERS", "A5. Handbills ~ FLYERS\nA9. No such slot ~ X\nnonsense")
    text = text.replace("~ DWARF", "~ DWARX")
    _, p = convert.convert(team_answer(text), ctx("x", SUNDAY))
    assert p.review == [
        "clue line not understood: nonsense",
        "A9: clue has no slot in the grid",
        "D1: clue answer DWARX differs from grid DWARF",
    ]


# --- the converter: Puzzmo's own series ---


def test_gameplay_answer_converts():
    _, p = convert.convert(gameplay(MINI_TEXT, name="A Test Mini"), ctx("puzzmo.mini", NOV9))
    assert p.headers["Title"] == "A Test Mini"
    assert p.tricky == []


def test_daily_crossword_split_character_hints_and_tilde():
    _, p = convert.convert(DAILY, ctx("puzzmo.daily", NOV9))
    by = {(c.direction, c.number): c for c in p.clues}
    assert by["A", 4].answer == "SAGE"
    assert by["D", 1].answer == "HAUL"
    assert by["A", 4].text == "Herb, after a ¬, ~, or !"
    assert p.tricky == ["8 clues have a ^hint: line, not carried"]
    assert p.review == []
    assert p.headers["Author"] == "settername and Bo Second"  # the answer's authors, not `author: as`
    assert p.headers["Editor"] == "Cy Editor"
    assert p.headers["Copyright"] == "© 2026 settername and Bo Second"
    assert p.grid == ["#HOP", "sAGE", "PULP", "ALE#"]
    assert p.headers["Special"] == "circle"
    # a clue's own " ~ " would start the answer in .xd, so it's written as literal markup
    _, p = convert.convert(gameplay(DAILY_TEXT.replace("after a ¬, ~, or !", "or ~ a sage")), ctx("x", NOV9))
    assert next(c.text for c in p.clues if (c.direction, c.number) == ("A", 4)) == "Herb, or {\\~\\} a sage"
    assert p.review == []
    assert "A4. Herb, or {\\~\\} a sage ~ SAGE" in p.to_xd()


# Schrödinger squares: '*' in the grid, the other answer on an ^alt: line, sometimes under the
# wrong clue. The middle square is R or W: ORE/OWE across, ARE/AWE down.
SCHRODINGER = """\
## Metadata

title: x
author: as
copyright: © 2025
splitcharacter: |

## Grid

CAT
O*E
WEE

## Clues

A1. Pet ~ CAT
A4. Mine find ~ ORE
A5. Tiny ~ WEE
A5 ^alt: OWE
A4 ^hint: Two answers work

D1. Farm animal ~ COW
D2. Exist ~ ARE
D2 ^alt: AWE
D3. Golf peg ~ TEE
"""


def test_schrodinger_squares():
    _, p = convert.convert(gameplay(SCHRODINGER), ctx("puzzmo.mini", NOV9))
    assert p.grid[1] == "O1E"
    assert p.headers["Rebus"] == "1=R|W"
    readings = [(c.direction, c.number, c.answer) for c in p.clues if c.number in (2, 4)]
    assert readings == [("A", 4, "ORE"), ("D", 2, "ARE"), ("D", 2, "AWE")]
    # the misplaced ^alt: is held for a person, who moves it to A4
    assert p.review == ["A5: ^alt: OWE doesn't fit the slot"]
    fixed = SCHRODINGER.replace("A5 ^alt: OWE", "A4 ^alt: OWE")
    _, p = convert.convert(gameplay(fixed), ctx("puzzmo.mini", NOV9))
    assert p.review == []
    assert [c.answer for c in p.clues if (c.direction, c.number) == ("A", 4)] == ["ORE", "OWE"]
    # a third reading comes on ^alt1:
    third = fixed.replace("D2 ^alt: AWE", "D2 ^alt: AWE\nD2 ^alt1: AXE")
    _, p = convert.convert(gameplay(third), ctx("puzzmo.mini", NOV9))
    assert p.headers["Rebus"] == "1=R|W|X"
    assert [c.answer for c in p.clues if (c.direction, c.number) == ("D", 2)] == ["ARE", "AWE", "AXE"]
    # an ^alt: for a clue that isn't there, and a square with only one reading
    lone = SCHRODINGER.replace("A5 ^alt: OWE", "A7 ^alt: OWE").replace("D2 ^alt: AWE\n", "")
    _, p = convert.convert(gameplay(lone), ctx("puzzmo.mini", NOV9))
    assert p.review == [
        "Schrödinger square at row 2, column 2 has R reading",
        "A7: ^alt: OWE for a clue that isn't there",
    ]


def test_rebus_answer_keyed_then_expanded():
    text = """\
## Metadata

title: x
author: as
rebus: 0=CTO
splitcharacter: |

## Grid

O0BER

## Clues

A1. Month ~ O0B|ER # O[CTO]BER
"""
    _, p = convert.convert(gameplay(text), ctx("x", NOV9))
    assert p.clues[0].answer == "OCTOBER"
    assert p.review == []
    assert p.headers["Rebus"] == "1=CTO"


def test_links_and_images_in_xd_form():
    assert converter.xd_markup("Texts {@ example.com/7a|https://www.example.com/7a @} now") == (
        "Texts {@example.com/7a | href: https://www.example.com/7a@} now"
    )
    assert converter.xd_markup("{@ @handle.example|https://example.org/profile/x @}") == (
        "{@@handle.example | href: https://example.org/profile/x@}"
    )
    assert converter.xd_markup("{@a|https://x.org/?a=1;b=2@}") == "{@a | href: 'https://x.org/?a=1;b=2'@}"
    assert converter.xd_markup("{! https://example.com/bear.svg|a bear|50px!} Tree ~") == (
        "{!a bear | src: https://example.com/bear.svg; width: 50px!} Tree ~"
    )
    assert converter.xd_markup("{@ no url @} {! alone !}") == "{@ no url @} {! alone !}"


def test_byline_is_what_puzzmo_shows():
    rec = {"authors": [{"publishingName": "sethandle", "name": "Ann Setter"}]}
    assert converter.byline(rec, {"author": "Ann Setter"}) == "sethandle"
    three = {"authors": [{"publishingName": "a"}, {"name": "b"}, {"publishingName": "c"}]}
    assert converter.byline(three, {}) == "a, b and c"
    assert converter.byline({}, {"author": "X & Y"}) == "X and Y"  # a team queue's answer has no authors


def test_editor_line_only_when_it_names_someone():
    assert converter.editor_of("Cy Editor") == "Cy Editor"
    assert converter.editor_of("cy") == "cy"
    for leftover in ["Not set", "", 'January 30, 2023 - "A Title" - Ann Setter,', "Ann Setter - 3/5"]:
        assert converter.editor_of(leftover) == ""


def test_editor_from_the_answer_when_it_has_one():
    text = DAILY_TEXT.replace("editor: Cy Editor", "editor: Not set")
    _, p = convert.convert(gameplay(text), ctx("x", NOV9))
    assert "Editor" not in p.headers
    _, p = convert.convert(
        gameplay(text, editors=[{"publishingName": "Ed Itor", "name": "editorhandle"}]), ctx("x", NOV9)
    )
    assert p.headers["Editor"] == "Ed Itor"
    _, p = convert.convert(gameplay(text, editors=[{"publishingName": None, "name": "ed"}]), ctx("x", NOV9))
    assert p.headers["Editor"] == "ed"
