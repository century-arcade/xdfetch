"""The Washington Post's games service JSON (the Sunday crossword), served at
https://games-service-prod.site.aws.wapo.pub/crossword/levels/sunday/YYYY/MM/DD:

    {"puzzleId": "sunday/2026/10/25", "title": "Bird Calls", "creator": "Ann Setter",
     "copyright": "© October 25, 2026, The Washington Post", "description": "", "width": 21,
     "cells": [{"answer": "H", "number": 1}, {"type": "locked"}, {"answer": "A", "circle": true}, ...],
     "words": [{"clue": "Male duck", "direction": "across", "indexes": [0, 1, 2]}, ...]}

Cells are row-major; a locked cell is a block. Circled letters are lowercase with Special:
circle; a multi-letter answer is a rebus square. The copyright line is kept as served (gxd's
wapost shelf has it that way), the description goes in the notes, and the puzzleId's date is
checked against the file's.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, clue_text, number_grid, plain
from . import Context, ConvertError


def sniff(data: bytes) -> bool:
    head = data[:200].lstrip()
    return head.startswith(b"{") and b'"puzzleId"' in data[:300] and b'"words"' in data and b'"cells"' in data


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        d = json.loads(data.decode("utf-8"))
        cells = d["cells"]
        w = int(d["width"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise ConvertError(f"not a games-service puzzle: {e}") from e
    if not w or len(cells) % w:
        raise ConvertError(f"{len(cells)} cells is not a multiple of width {w}")
    h = len(cells) // w
    p = Puzzle()

    circled = {i for i, c in enumerate(cells) if c.get("circle")}
    if circled:
        p.set("Special", "circle")
    rebus: dict[str, str] = {}
    plain_keys = iter(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid = []
    for r in range(h):
        row = ""
        for i in range(r * w, (r + 1) * w):
            c = cells[i]
            a = (c.get("answer") or "").strip()
            if c.get("type") == "locked" or (not a and not c.get("number") and "answer" not in c):
                row += BLOCK
            elif not a:
                row += " "
                p.needs_review(f"empty square at row {r} col {i - r * w}")
            elif len(a) == 1 and a.isalpha() and a.isascii():
                row += a.lower() if i in circled else a.upper()
            else:
                value = a.upper() if a.isalpha() else a
                if value not in rebus:
                    try:
                        rebus[value] = next(letters) if i in circled else next(plain_keys)
                    except StopIteration:
                        raise ConvertError("more rebus values than keys") from None
                row += rebus[value]
        grid.append(row)
    p.grid = grid
    if rebus:
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in rebus.items()))

    numbering = number_grid([row.replace(" ", "?") for row in grid])
    for word in d.get("words", []):
        idx = word.get("indexes") or []
        if not idx:
            p.needs_review("a clue with no squares")
            continue
        direction = "A" if word.get("direction") == "across" else "D"
        first = idx[0]
        r, c = divmod(first, w)
        number = cells[first].get("number")
        if number is None:
            number = next((n for (dr, n), pos in numbering.items() if dr == direction and pos == (r, c)), None)
        if number is None:
            p.needs_review(f"{direction} clue at row {r} col {c} has no number")
            continue
        number = int(number)
        if numbering.get((direction, number)) != (r, c):
            p.needs_review(f"{direction}{number}: numbered at row {r} col {c}, standard numbering disagrees")
        answer = "".join((cells[i].get("answer") or "").upper() for i in idx)
        raw = word.get("clue") or ""
        text = clue_text(raw) if re.search(r"<\w+", raw) else plain(raw)
        p.clues.append(Clue(direction, number, text, answer))
    if not p.clues:
        raise ConvertError("no clues")

    p.set("Title", d.get("title") or "")
    p.set("Author", re.sub(r"\s+&\s+", " and ", plain(d.get("creator") or "")))
    p.set("Copyright", d.get("copyright") or "")
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
        m = re.search(r"(\d{4})/(\d{2})/(\d{2})", d.get("puzzleId") or "")
        if m and dt.date(*map(int, m.groups())) != ctx.date:
            p.tricky.append(f"puzzleId is dated {m.group(0)}, file dated {ctx.date}")
    p.notes = plain(d.get("description") or "")
    return p
