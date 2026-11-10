"""Tiny puzzles made up for the tests. Never use real, published puzzles here.

C A T      1A Café pet       1D Taxi
A # O      3A Ribbon knot    2D Pull a barge
B O W
"""

import json

import puz
import pytest

SOLUTION = ["CAT", "A#O", "BOW"]
TITLE, AUTHOR, COPYRIGHT = "Tiny", "A. Setter", "© 2026 Nobody"

EXPECTED_CLUES = [
    "A1. Café pet ~ CAT",
    "A3. Ribbon knot ~ BOW",
    "D1. Taxi ~ CAB",
    "D2. Pull a barge ~ TOW",
]


def make_puz(circle_first: bool = False) -> bytes:
    p = puz.Puzzle()
    p.width = p.height = 3
    p.solution = "".join(SOLUTION).replace("#", ".")
    p.fill = "".join("." if c == "." else "-" for c in p.solution)
    p.title, p.author, p.copyright = TITLE, AUTHOR, COPYRIGHT
    p.clues = ["Café pet", "Taxi", "Pull a barge", "Ribbon knot"]  # .puz order: by number, across first
    if circle_first:
        p.extensions[b"GEXT"] = bytes([0x80] + [0] * 8)
        p._extensions_order.append(b"GEXT")
    return p.tobytes()


def make_ipuz() -> dict:
    return {
        "version": "http://ipuz.org/v2",
        "kind": ["http://ipuz.org/crossword#1"],
        "dimensions": {"width": 3, "height": 3},
        "title": TITLE,
        "author": AUTHOR,
        "copyright": COPYRIGHT,
        "puzzle": [[1, 0, 2], [0, "#", 0], [3, 0, 0]],
        "solution": [list(row) for row in SOLUTION],
        "clues": {"Across": [[1, "Café pet"], [3, "Ribbon knot"]], "Down": [[1, "Taxi"], [2, "Pull a barge"]]},
    }


@pytest.fixture
def puz_bytes() -> bytes:
    return make_puz()


@pytest.fixture
def ipuz_bytes() -> bytes:
    return json.dumps(make_ipuz(), ensure_ascii=False).encode("utf-8")
