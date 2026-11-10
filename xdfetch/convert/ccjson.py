"""Crossword Compiler documents as JSON: the form King Features' puzzles (Thomas Joseph,
Eugene Sheffer, the Premier Crossword) come in on GameDistribution's crossword feed, as the
`gamedist` adapter saves them.

The document is the XML converted by xml2js (attributes under `$`, text under `_`, every
child element a list), under `data`, with the feed's own record of the puzzle in `metaData`:

    {"metaData": {"author": "Thomas Joseph Crossword", "date": "2026-10-09", "title": ..., ...},
     "data": {"$": {"xmlns": "http://crossword.info/xml/rectangular-puzzle"},
              "metadata": [{"title": ["October 09, 2026"], "creator": [...], "copyright": [...]}],
              "crossword": [{"grid": [{"$": {"width": "4", "height": "4"},
                                       "cell": [{"$": {"x": "1", "y": "1", "solution": "C"}}, ...]}],
                             "word": [{"$": {"id": "1", "x": "1-3", "y": "1"}}, ...],
                             "clues": [{"title": [{"b": ["Across"]}],
                                        "clue": [{"_": "Feline", "$": {"word": "1", "number": "1"}}]}]}]}}

read() makes of it the dict xdfetch.convert.ccxml.build() takes, and the puzzle is built
exactly as from the XML, with the same params (see ccxml). The feed's date for the puzzle
is checked against the date it is filed under. xml2js keeps a clue's inline markup apart
from its text, losing where it was; such a clue is listed as tricky.
"""

from __future__ import annotations

import json

from ..xd import Puzzle
from . import Context, ConvertError, ccxml

WHITESPACE = b"\xef\xbb\xbf \r\n\t"


def sniff(data: bytes) -> bool:
    head = data[:2000]
    return (
        head.lstrip(WHITESPACE).startswith(b"{")
        and b"rectangular-puzzle" in head
        and b'"crossword"' in data
        and b'"$"' in data
    )


def _text(v) -> str:
    """xml2js text: a string, a list of one, or {"_": text, ...} when the element had attributes or children."""
    if isinstance(v, list):
        return "".join(_text(x) for x in v)
    if isinstance(v, dict):
        return _text(v.get("_", "")) + "".join(_text(x) for k, x in v.items() if k not in ("_", "$"))
    return "" if v is None else str(v)


def read(data: bytes) -> dict:
    """The document as the dict ccxml.build() takes, with the feed's record."""
    try:
        doc = json.loads(data.decode("utf-8"))
        body = doc.get("data", doc)
        meta = {k: _text(v) for k, v in (body.get("metadata") or [{}])[0].items()}
        cw = body["crossword"][0]
        grid = cw["grid"][0]
    except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise ConvertError(f"not a Crossword Compiler JSON document: {e}") from e
    groups, lost = [], []
    for g in cw.get("clues") or []:
        title = _text(g.get("title")).strip()
        clues = []
        for c in g.get("clue") or []:
            if isinstance(c, str):
                c = {"_": c}
            attrs = c.get("$", {})
            extra = [k for k in c if k not in ("_", "$")]
            if extra:  # xml2js keeps a child element apart from the text, losing where it was
                lost.append(f"{title[:1]}{attrs.get('number', '?')}: clue markup ({', '.join(extra)}) out of place")
            clues.append((attrs, _text(c)))
        groups.append((title, clues))
    return {
        "meta": meta,
        "size": grid.get("$", {}),
        "cells": [c.get("$", {}) for c in grid.get("cell") or []],
        "words": [w.get("$", {}) for w in cw.get("word") or []],
        "groups": groups,
        "record": doc.get("metaData") or {},
        "lost": lost,
    }


def convert(data: bytes, ctx: Context) -> Puzzle:
    return ccxml.build(read(data), ctx)
