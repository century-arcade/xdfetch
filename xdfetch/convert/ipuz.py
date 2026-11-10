"""ipuz crosswords (http://ipuz.org, v1 and v2), as many outlets export them from Crossword
Compiler and other tools.

    {"version": "http://ipuz.org/v2", "kind": ["http://ipuz.org/crossword#1"],
     "title": ..., "author": ..., "copyright": "© 2026", "intro": ..., "notes": ...,
     "dimensions": {"width": 5, "height": 5}, "block": "#", "empty": 0,
     "puzzle": [[1, 0, "#", {"cell": 4, "style": {"shapebg": "circle"}}, ...], ...],
     "solution": [["A", "B", "#", {"value": "C"}, ...], ...],
     "clues": {"Across": [{"number": 1, "clue": "<I>Italic</I> clue"}, [2, "or a pair"]], "Down": [...]}}

Some sites serve it as JSONP, wrapped in `ipuz(...)`; the wrapper (and a byte-order mark)
is taken off first.

Circles (style shapebg circle) are lowercase letters with Special: circle; a bar
(style barred) is listed as tricky; a square with more than one letter is a rebus square.
Clue text with <i>/<b> becomes xd markup. The title, author and notes are the file's; the
editor comes from an intro that says "Edited by ..."; the copyright is the file's line
unless it is a bare "©".

An outlet whose files need more than this (a title kept in a record beside the file, say)
can supply it from a converter plugin that calls convert() here and adjusts the result:
see xdfetch.convert.
"""

from __future__ import annotations

import html
import json
import re

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, clue_text, number_grid, plain
from . import Context, ConvertError


def unwrap(data: bytes) -> bytes:
    """The JSON, without a byte-order mark or a JSONP `ipuz(...)` wrapper around it."""
    data = data.lstrip(b"\xef\xbb\xbf").strip()
    if data.startswith(b"ipuz(") and data.endswith(b")"):
        data = data[5:-1].strip()
    return data


def sniff(data: bytes) -> bool:
    # a big puzzle's file can put its grid first, so "ipuz.org" can be deep in the file
    data = unwrap(data)
    return data.startswith(b"{") and b"ipuz.org" in data and b'"puzzle"' in data and b'"solution"' in data


def cell_number(cell) -> int | None:
    if isinstance(cell, dict):
        cell = cell.get("cell")
    return cell if isinstance(cell, int) else None


def cell_style(cell) -> dict:
    return (cell.get("style") or {}) if isinstance(cell, dict) else {}


def cell_value(cell) -> str | None:
    if isinstance(cell, dict):
        cell = cell.get("value")
    return cell if isinstance(cell, str) else None


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        d = json.loads(unwrap(data).decode("utf-8"))
        h, w = int(d["dimensions"]["height"]), int(d["dimensions"]["width"])
        puzzle, solution = d["puzzle"], d["solution"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise ConvertError(f"not an ipuz crossword: {e}") from e
    block = d.get("block", "#")
    if len(puzzle) != h or len(solution) != h or any(len(r) != w for r in puzzle) or any(len(r) != w for r in solution):
        raise ConvertError(f"grid is not {w}x{h}")
    p = Puzzle()

    circled: set[tuple[int, int]] = set()
    for r in range(h):
        for c in range(w):
            style = cell_style(puzzle[r][c])
            for k, v in style.items():
                if (k, v) == ("shapebg", "circle"):
                    circled.add((r, c))
                elif k == "barred":
                    p.tricky.append(f"bar {v} at row {r} col {c}")
                elif k in ("color", "colortext", "highlight"):
                    p.tricky.append(f"{k} {v} at row {r} col {c}")
    if circled:
        p.set("Special", "circle")

    rebus: dict[str, str] = {}
    plain_keys = iter(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid = []
    for r in range(h):
        row = ""
        for c in range(w):
            v = cell_value(solution[r][c])
            is_block = v == block or (cell_number(puzzle[r][c]) is None and puzzle[r][c] == block)
            if is_block or (v is None and puzzle[r][c] == block):
                row += BLOCK
            elif not v:
                row += " "
                p.needs_review(f"empty square at row {r} col {c}")
            elif len(v) == 1 and v.isalpha() and v.isascii():
                row += v.lower() if (r, c) in circled else v.upper()
            else:
                value = v.upper() if v.isalpha() else v
                if value not in rebus:
                    try:
                        rebus[value] = next(letters) if (r, c) in circled else next(plain_keys)
                    except StopIteration:
                        raise ConvertError("more rebus values than keys") from None
                row += rebus[value]
        grid.append(row)
    p.grid = grid
    if rebus:
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in rebus.items()))

    numbering = number_grid([row.replace(" ", "?") for row in grid])
    from ..xd import answer_at

    theirs = {(r, c): cell_number(puzzle[r][c]) for r in range(h) for c in range(w) if cell_number(puzzle[r][c])}
    ours = {pos: n for (_, n), pos in numbering.items()}
    off = sorted(pos for pos in set(theirs) | set(ours) if theirs.get(pos) != ours.get(pos))
    if off:
        p.needs_review(
            "the outlet's cell numbers differ from standard numbering at "
            + ", ".join(f"row {r} col {c}" for r, c in off[:6])
            + ("..." if len(off) > 6 else "")
        )

    for direction, key in (("A", "Across"), ("D", "Down")):
        for item in d.get("clues", {}).get(key, []):
            if isinstance(item, dict):
                number, raw = item.get("number"), item.get("clue", "")
            elif isinstance(item, list) and len(item) >= 2:
                number, raw = item[0], item[1]
            else:
                continue
            try:
                number = int(number)
            except (TypeError, ValueError):
                p.needs_review(f"{direction} clue with no number: {str(raw)[:40]}")
                continue
            pos = numbering.get((direction, number))
            if pos is None:
                p.needs_review(f"{direction}{number}: clue has no slot in the grid")
                answer = ""
            else:
                from_grid = answer_at(grid, direction, *pos)
                answer = "".join(next((v for v, k in rebus.items() if k == ch), ch.upper()) for ch in from_grid)
            p.clues.append(Clue(direction, number, clue_text(html.unescape(str(raw))), answer))
    if not p.clues:
        raise ConvertError("no clues")
    for item in d.get("clues", {}).get("Across", []) + d.get("clues", {}).get("Down", []):
        if isinstance(item, dict) and item.get("answer"):
            p.tricky.append("a clue carries its own answer key; the grid's is used")
            break

    # headers
    title = plain(str(d.get("title") or ""))
    author = plain(str(d.get("author") or ""))
    editor = ""
    intro = plain(str(d.get("intro") or ""))
    if intro and not intro.isdigit() and re.search(r"edited by", intro, re.I):
        editor = re.sub(r"^.*edited by\s*", "", intro, flags=re.I)
    p.set("Title", title)
    p.set("Author", re.sub(r"\s+&\s+", " and ", author))
    p.set("Editor", editor)
    copyright_ = plain(str(d.get("copyright") or ""))
    if copyright_ and copyright_ != "©":
        p.set("Copyright", copyright_)
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
    p.notes = plain(str(d.get("notes") or ""))
    return p
