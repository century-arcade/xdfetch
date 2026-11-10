"""Tiny puzzles made up for the tests (more, one per wire format, in synthetic.py). Never
use real, published puzzles here.

C A T      1A Café pet       1D Taxi
A # O      3A Ribbon knot    2D Pull a barge
B O W
"""

import json

import pytest
from synthetic import puz, puz_section

SOLUTION = ["CAT", "A#O", "BOW"]
TITLE, AUTHOR, COPYRIGHT = "Tiny", "A. Setter", "© 2026 Nobody"

EXPECTED_CLUES = [
    "A1. Café pet ~ CAT",
    "A3. Ribbon knot ~ BOW",
    "D1. Taxi ~ CAB",
    "D2. Pull a barge ~ TOW",
]


def make_puz(circle_first: bool = False) -> bytes:
    clues = ["Café pet", "Taxi", "Pull a barge", "Ribbon knot"]  # .puz order: by number, across first
    gext = puz_section(b"GEXT", bytes([0x80] + [0] * 8)) if circle_first else b""
    return puz(SOLUTION, clues, TITLE, AUTHOR, COPYRIGHT, extra=gext)


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


@pytest.fixture
def registry():
    """xdfetch's own outlets.tsv, with no plugin registries."""
    from xdfetch import registry as reg

    return reg.builtin()


@pytest.fixture
def http():
    """An Http that never sleeps."""
    from xdfetch.http import Http

    return Http(interval=0, retries=2, sleep=lambda s: None)


class FakeEntryPoint:
    """Stands in for importlib.metadata.EntryPoint: `obj` is what load() returns, or raises."""

    def __init__(self, group: str, name: str, obj: object, value: str = ""):
        self.group, self.name, self.obj = group, name, obj
        self.value = value or f"fakepkg.module:{name}"

    def load(self):
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


@pytest.fixture
def plugins(monkeypatch):
    """Installs fake entry points: plugins(group, name, obj). Nothing real is installed."""
    import importlib.metadata

    installed: list[FakeEntryPoint] = []

    def entry_points(**selection):
        group = selection.get("group")
        return [ep for ep in installed if group is None or ep.group == group]

    monkeypatch.setattr(importlib.metadata, "entry_points", entry_points)

    def add(group: str, name: str, obj: object, value: str = "") -> None:
        installed.append(FakeEntryPoint(group, name, obj, value))

    return add
