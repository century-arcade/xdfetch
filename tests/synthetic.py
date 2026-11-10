"""Made-up puzzles in each wire format the converters read. Never use real, published
puzzles here: these are invented, and only shaped like what the outlets serve.

Two grids. FIVE, a 5x5 with a circled square (the B at row 2 col 2) and a rebus square
(RS, bottom right):

    D R A K E      A1 Male duck            D1 Small fairy-tale miner ~ DWARF
    W # B # R      A4 Fossil resin         D2 Monastery              ~ ABBEY
    A M b E R      A5 Handbills ~ FLYERS   D3 Mistakes               ~ ERRORS
    R # E # O
    F L Y E [RS]

FOUR, a 4x4 with blocks in two corners:

    # H O P        A1 Small jump   D1 Drag      ~ HAUL
    S A G E        A4 Herb         D2 Eye       ~ OGLE
    P U L P        A5 Mash         D3 Energy    ~ PEP
    A L E #        A6 Pub pour     D4 Resort    ~ SPA
"""

from __future__ import annotations

import json
import struct

FIVE = ["DRAKE", "W#B#R", "AMBER", "R#E#O", "FLYE*"]  # * is the rebus square
FIVE_REBUS = "RS"
FIVE_CIRCLE = (2, 2)
FOUR = ["#HOP", "SAGE", "PULP", "ALE#"]


def five_value(r: int, c: int) -> str:
    ch = FIVE[r][c]
    return FIVE_REBUS if ch == "*" else ch


# --- uclick XML (Universal) ---

UCLICK = """﻿<crossword>
  <Title v="Bird Words" />
  <Author v="By Ann Setter" />
  <Category v="Universal Daily Crosswords" />
  <Copyright v="Andrews McMeel Syndication" />
  <Editor v="Cy Editor" />
  <Width v="5" />
  <Height v="5" />
  <AllAnswer v="DRAKEW-B-RAMBERR-E-OFLYER" />
  <across>
    <a1 a="DRAKE" c="%22Male%22 duck, with an %27apostrophe%27" n="1" cn="1" />
    <a2 a="AMBER" c="Fossil resin &lt;i&gt;italic&lt;/i&gt; and an em dash — here" n="2" cn="4" />
    <a3 a="FLYER" c="Handbill…" n="3" cn="5" />
  </across>
  <down>
    <d1 a="DWARF" c="Small miner" n="1" cn="1" />
    <d2 a="ABBEY" c="Monastery, caf%C3%A9 nearby" n="2" cn="2" />
    <d3 a="ERROR" c="Mistake" n="3" cn="3" />
  </down>
</crossword>
""".encode()

UCLICK_XD = """\
Title: Bird Words
Author: Ann Setter
Editor: Cy Editor
Copyright: Andrews McMeel Syndication
Date: 2026-10-28
Category: Universal Daily Crosswords


DRAKE
W#B#R
AMBER
R#E#O
FLYER


A1. "Male" duck, with an 'apostrophe' ~ DRAKE
A4. Fossil resin {/italic/} and an em dash — here ~ AMBER
A5. Handbill... ~ FLYER

D1. Small miner ~ DWARF
D2. Monastery, café nearby ~ ABBEY
D3. Mistake ~ ERROR

"""

# --- the clues of FIVE, and the .xd most converters write for it ---

FIVE_XD_GRID_AND_CLUES = """\
DRAKE
W#B#R
AMbER
R#E#O
FLYE1


A1. {/Male/} duck, with "quotes" ~ DRAKE
A4. Fossil resin — café colour ~ AMBER
A5. Handbills ~ FLYERS

D1. Small fairy-tale miner ~ DWARF
D2. Monastery ~ ABBEY
D3. Mistakes... ~ ERRORS
"""

# --- Condé Nast service record ---

CONDE_DATA = """\
## Metadata

title: The Crossword: Wednesday, October 28, 2026
author: Ann Setter
date: 2026-10-28
editor: \n\
copyright: \n\
subtitle: Today’s theme: Birds.
rebus: ⓐ=RS

## Grid

DRAKE
W.B.R
AMBER
R.E.O
FLYEⓐ

## Clues

A1. {/Male/} duck, with &quot;quotes&quot; ~ DRAKE
A4. Fossil resin — café colour ~ AMBER
A4 ^refs: A1

A5. Handbills ~ FLYERS

D1. Small fairy-tale miner ~ DWARF
D2. Monastery ~ ABBEY
D3. Mistakes… ~ ERRORS

## Design

<style>
O { background: circle }
</style>

.....
.#.#.
..O..
.#.#.
.....

## End Message

<div class="related_text">More puzzles soon.</div>
"""


def conde() -> dict:
    return {
        "id": "00000000-0000-4000-8000-00000000c0de",
        "name": "Test_Wed_10_2026",
        "createdAt": "2026-10-06T12:00:00.000Z",
        "updatedAt": "2026-10-20T12:00:00.000Z",
        "data": CONDE_DATA,
    }


CONDE_XD = (
    """\
Title: The Crossword: Wednesday, October 28, 2026 - Birds
Author: Ann Setter
Date: 2026-10-28
Special: circle
Rebus: 1=RS


"""
    + FIVE_XD_GRID_AND_CLUES
    + "\n"
)

# --- New York Times v6 JSON ---


def nyt() -> dict:
    clue_cells = {
        ("A", 1): [(0, c) for c in range(5)],
        ("A", 4): [(2, c) for c in range(5)],
        ("A", 5): [(4, c) for c in range(5)],
        ("D", 1): [(r, 0) for r in range(5)],
        ("D", 2): [(r, 2) for r in range(5)],
        ("D", 3): [(r, 4) for r in range(5)],
    }
    texts = {
        ("A", 1): {"plain": 'Male duck, with "quotes"', "formatted": "<i>Male</i> duck, with &quot;quotes&quot;"},
        ("A", 4): {"plain": "Fossil resin — café colour"},
        ("A", 5): {"plain": "E=mc2 handbills", "formatted": "E=mc<sup>2</sup> handbills"},
        ("D", 1): {"plain": "Small fairy-tale miner"},
        ("D", 2): {"plain": "Monastery"},
        ("D", 3): {"plain": "Mistakes…"},
    }
    order = list(clue_cells)
    labels = {pos[0]: n for (_, n), pos in clue_cells.items()}
    cells = []
    for r in range(5):
        for c in range(5):
            if FIVE[r][c] == "#":
                cells.append({})
                continue
            cell = {
                "answer": five_value(r, c),
                "clues": [i for i, k in enumerate(order) if (r, c) in clue_cells[k]],
                "type": 2 if (r, c) == FIVE_CIRCLE else 1,
            }
            if (r, c) in labels:
                cell["label"] = str(labels[(r, c)])
            cells.append(cell)
    return {
        "publicationDate": "2026-10-28",
        "constructors": ["Ann Setter", "Bo Second"],
        "editor": "Cy Editor",
        "copyright": "2026",
        "id": 1,
        "lastUpdated": "2026-10-28 02:00:00 UTC",
        "notes": [
            {"text": "A note shown on the web.", "platforms": {"web": True}},
            {"text": "A phone-only note.", "platforms": {"ios": True}},
        ],
        "body": [
            {
                "dimensions": {"width": 5, "height": 5},
                "cells": cells,
                "clues": [
                    {
                        "cells": [r * 5 + c for r, c in clue_cells[k]],
                        "direction": "Across" if k[0] == "A" else "Down",
                        "label": str(k[1]),
                        "text": [texts[k]],
                    }
                    for k in order
                ],
            }
        ],
    }


NYT_XD = """\
Title: Wednesday, October 28, 2026
Author: Ann Setter and Bo Second
Editor: Cy Editor
Copyright: © 2026, The New York Times
Date: 2026-10-28
Special: circle
Rebus: 1=RS


DRAKE
W#B#R
AMbER
R#E#O
FLYE1


A1. {/Male/} duck, with "quotes" ~ DRAKE
A4. Fossil resin — café colour ~ AMBER
A5. E=mc{^2^} handbills ~ FLYERS

D1. Small fairy-tale miner ~ DWARF
D2. Monastery ~ ABBEY
D3. Mistakes... ~ ERRORS


A note shown on the web.
"""

# --- Washington Post games service JSON ---


def wapo() -> dict:
    numbers = {(0, 0): 1, (0, 2): 2, (0, 4): 3, (2, 0): 4, (4, 0): 5}
    cells = []
    for r in range(5):
        for c in range(5):
            if FIVE[r][c] == "#":
                cells.append({"type": "locked"})
                continue
            cell: dict = {"answer": five_value(r, c)}
            if (r, c) in numbers:
                cell["number"] = numbers[(r, c)]
            if (r, c) == FIVE_CIRCLE:
                cell["circle"] = True
            cells.append(cell)
    words = [
        ("“Male” duck ", "across", [0, 1, 2, 3, 4]),
        ("Fossil resin — café colour", "across", [10, 11, 12, 13, 14]),
        ("Handbills", "across", [20, 21, 22, 23, 24]),
        ("Small fairy-tale miner", "down", [0, 5, 10, 15, 20]),
        ("Monastery", "down", [2, 7, 12, 17, 22]),
        ("Mistakes…", "down", [4, 9, 14, 19, 24]),
    ]
    return {
        "puzzleId": "sunday/2026/10/25",
        "creator": "Ann Setter",
        "width": 5,
        "cells": cells,
        "copyright": "© October 25, 2026, The Washington Post",
        "description": "Made up for the tests.",
        "words": [{"clue": t, "direction": d, "indexes": i} for t, d, i in words],
        "title": "Bird Calls",
    }


WAPO_XD = (
    """\
Title: Bird Calls
Author: Ann Setter
Copyright: © October 25, 2026, The Washington Post
Date: 2026-10-25
Special: circle
Rebus: 1=RS


"""
    + FIVE_XD_GRID_AND_CLUES.replace('{/Male/} duck, with "quotes"', '"Male" duck')
    + """

Made up for the tests.
"""
)

# --- The Daily Princetonian (FOUR, with the A of SAGE circled) ---

AUTHOR_1 = "00000000-0000-4000-8000-0000000000a1"
AUTHOR_2 = "00000000-0000-4000-8000-0000000000a2"
PRINCETONIAN_ID = "00000000-0000-4000-8000-000000000001"


def princetonian() -> dict:
    clues = [
        ("HOP", "Small jump", True, 1, 0),
        ("SaGE", "Herb with “fuzzy” leaves", True, 0, 1),
        ("PULP", "Mash", True, 0, 2),
        ("ALE", "Pub pour", True, 0, 3),
        ("HaUL", "Drag, as a trailer’s load", False, 1, 0),
        ("OGLE", "Eye", False, 2, 0),
        ("PEP", "Energy × enthusiasm", False, 3, 0),
        ("SPA", "Resort", False, 0, 1),
    ]
    return {
        "crossword": {
            "author_ids": [AUTHOR_2, AUTHOR_1],
            "commentary_link": None,
            "date": "2026-10-30T00:00:00+00:00",
            "description": "Difficulty Level: 1/5",
            "id": PRINCETONIAN_ID,
            "legacy_id": None,
            "mini": True,
            "title": "Small Hours",
        },
        "clues": [
            {
                "answer": answer,
                "clue": clue,
                "crossword_id": PRINCETONIAN_ID,
                "id": f"00000000-0000-4000-8000-0000000000c{i}",
                "is_across": across,
                "x": x,
                "y": y,
            }
            for i, (answer, clue, across, x, y) in enumerate(clues)
        ],
        "authors": [
            {"first_name": "Ann", "id": AUTHOR_1, "last_name": "Setter"},
            {"first_name": "Bo", "id": AUTHOR_2, "last_name": "Second"},
        ],
    }


PRINCETONIAN_XD = """\
Title: Small Hours
Author: Bo Second and Ann Setter
Date: 2026-10-30
Special: circle


#HOP
SaGE
PULP
ALE#


A1. Small jump ~ HOP
A4. Herb with "fuzzy" leaves ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. Drag, as a trailer's load ~ HAUL
D2. Eye ~ OGLE
D3. Energy × enthusiasm ~ PEP
D4. Resort ~ SPA

"""

# --- Crossword Compiler XML (FOUR, in the shape of Arkadium's feed) ---


def _ccxml_cells() -> str:
    numbers = {(1, 2): 1, (1, 3): 2, (1, 4): 3, (2, 1): 4, (3, 1): 5, (4, 1): 6}  # (y, x), 1-based
    out = []
    for x in range(1, 5):
        for y in range(1, 5):
            ch = FOUR[y - 1][x - 1]
            if ch == "#":
                out.append(f'<cell x="{x}" y="{y}" type="block"/>')
                continue
            number = f' number="{numbers[(y, x)]}"' if (y, x) in numbers else ""
            bar = ' left-bar="true"' if (x, y) == (1, 2) else ""  # on the grid's edge: dropped
            out.append(f'<cell x="{x}" y="{y}" solution="{ch}"{number}{bar}/>')
    return "".join(out)


CCXML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<crossword-compiler xmlns="http://crossword.info/xml/crossword-compiler">'
    '<rectangular-puzzle xmlns="http://crossword.info/xml/rectangular-puzzle" alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ">'
    "<metadata><title>Mini Crossword</title><creator>Ann Setter</creator><copyright>©Arkadium</copyright>"
    "<description></description></metadata>"
    '<crossword><grid width="4" height="4"><grid-look numbering-scheme="normal"/>' + _ccxml_cells() + "</grid>"
    '<word id="1" x="2-4" y="1"/><word id="2" x="2" y="1-4"/><word id="3" x="3" y="1-4"/><word id="4" x="4" y="1-3"/>'
    '<word id="5" x="1-4" y="2"/><word id="6" x="1" y="2-4"/><word id="7" x="1-4" y="3"/><word id="8" x="1-3" y="4"/>'
    '<clues ordering="normal"><title><b>Across</b></title>'
    '<clue word="1" number="1" format="3">Small jump</clue>'
    '<clue word="5" number="4" format="4">Herb <i>sometimes</i> dried</clue>'
    '<clue word="7" number="5" format="4">Mash</clue>'
    '<clue word="8" number="6" format="3">Pub pour</clue></clues>'
    '<clues ordering="normal"><title><b>Down</b></title>'
    '<clue word="2" number="1" format="4">“Drag” a trailer’s load</clue>'
    '<clue word="3" number="2" format="4">Eye</clue>'
    '<clue word="4" number="3" format="3">Energy…</clue>'
    '<clue word="6" number="4" format="3">Resort</clue></clues>'
    "</crossword></rectangular-puzzle></crossword-compiler>"
).encode()

CCXML_XD = """\
Title: October 9, 2026
Author: Ann Setter
Copyright: © Arkadium
Date: 2026-10-09


#HOP
SAGE
PULP
ALE#


A1. Small jump ~ HOP
A4. Herb {/sometimes/} dried ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. "Drag" a trailer's load ~ HAUL
D2. Eye ~ OGLE
D3. Energy... ~ PEP
D4. Resort ~ SPA

"""

# --- Across Lite .puz ---


def puz(
    rows: list[str],
    clues: list[str],
    title: str = "",
    author: str = "",
    copyright: str = "",
    notes: str = "",
    extra: bytes = b"",
) -> bytes:
    """A .puz file: `rows` with # for blocks, `clues` in .puz order (by number, across before
    down), Latin-1 text, checksums left at zero (the converter doesn't check them), and
    `extra` (tagged sections) appended."""
    w, h = len(rows[0]), len(rows)
    solution = "".join(rows).replace("#", ".").encode("latin-1")
    fill = bytes(ord(".") if ch == ord(".") else ord("-") for ch in solution)
    header = bytearray(0x34)
    header[0x02:0x0E] = b"ACROSS&DOWN\0"
    header[0x18:0x1C] = b"1.3\0"
    header[0x2C], header[0x2D] = w, h
    struct.pack_into("<HHH", header, 0x2E, len(clues), 1, 0)
    strings = b"".join(s.encode("latin-1") + b"\0" for s in [title, author, copyright, *clues, notes])
    return bytes(header) + solution + fill + strings + extra


def puz_section(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack("<HH", len(body), 0) + body + b"\0"


FOUR_PUZ_CLUES = ["Small jump", "Drag", "Eye", "Energy", "''Herb'' of the kitchen", "Resort", "Mash", "Pub pour"]


def four_puz(extra: bytes = b"") -> bytes:
    return puz(FOUR, FOUR_PUZ_CLUES, "Mini 101", "Ann Setter", "Arkadium", extra=extra)


FOUR_PUZ_XD = """\
Title: October 9, 2026
Author: Ann Setter
Copyright: Arkadium
Date: 2026-10-09


#HOP
SAGE
PULP
ALE#


A1. Small jump ~ HOP
A4. "Herb" of the kitchen ~ SAGE
A5. Mash ~ PULP
A6. Pub pour ~ ALE

D1. Drag ~ HAUL
D2. Eye ~ OGLE
D3. Energy ~ PEP
D4. Resort ~ SPA

"""


def as_bytes(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False).encode("utf-8")
