"""Tiny puzzles made up for the tests (more, one per wire format, in synthetic.py). Never
use real, published puzzles here.

C A T      1A Café pet       1D Taxi
A # O      3A Ribbon knot    2D Pull a barge
B O W
"""

import datetime as dt
import json
from typing import TypeVar

import pytest
from synthetic import UCLICK, puz, puz_section

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


# Made-up outlets for the run engine's tests (plan, run, ledger, availability), on example
# hosts. Times: NOW is 08:00 Eastern on 2026-10-29, so with available_after 3 the 28th is up.
ENGINE_REGISTRY = """\
id\tadapter\tparams\tdays\tsince\ttz\tavailable_after\trefetch\thomepage\tauth\tenabled\tnotes
example.daily\turl\turl=https://example.com/feed/ex%y%m%d.xml\tdaily\t\tAmerica/New_York\t3\t1,2\thttps://example.com/daily/\t\tyes\tA made-up daily feed.
example.other\turl\turl=https://example.com/other/oth%y%m%d.xml\tdaily\t\tAmerica/New_York\t3\t\thttps://example.com/other/\t\tyes\t
example.late\turl\turl=https://example.net/late/%Y%m%d.puz\tdaily\t\tAmerica/New_York\t6\t\thttps://example.net/\t\tyes\t
example.early\turl\turl=https://example.org/early/%Y-%m-%d.json\tdaily\t\tAmerica/New_York\t-2\t\t\t\tyes\tPosted the evening before.
example.off\turl\turl=https://example.org/off/%Y%m%d.puz\tsun\t\tAmerica/New_York\t0\t\t\t\tno\tNo longer fetched.
"""  # noqa: E501
NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
YESTERDAY = dt.date(2026, 10, 28)
RAW = UCLICK  # any bytes would do: a run keeps files as served and never converts them


T = TypeVar("T")


def present(x: T | None) -> T:
    """x, which the test expects not to be None."""
    assert x is not None
    return x


@pytest.fixture
def engine_registry(tmp_path):
    """The made-up outlets above, on their own (no built-in rows)."""
    from xdfetch import registry as reg

    f = tmp_path / "engine-outlets.tsv"
    f.write_text(ENGINE_REGISTRY, encoding="utf-8")
    return reg.from_files([f])


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
