"""The Daily Princetonian's crossword API, as the `princetonian` adapter keeps it: three of the
site's answers in one object.

    {"crossword": {"id": "...", "title": "Small Hours", "date": "2026-10-30T00:00:00+00:00",
                   "mini": true, "author_ids": ["..."], "description": null, ...},
     "clues": [{"answer": "HOP", "clue": "Small jump", "is_across": true,
                "x": 1, "y": 0, ...}, ...],
     "authors": [{"id": "...", "first_name": "Ann", "last_name": "Setter"}]}

There is no grid in the data: it is drawn from the clues, each answer laid from its x, y
(column, row of its first square), and a square no answer covers is a block. A lowercase
letter in an answer is a circled square (Special: circle, lowercase in the grid). Numbers
aren't in the data either; they are standard numbering of the grid that results.

Headers: Title, Author (the constructors in the record's order, "A, B and C"), Date. The
record's description ("Difficulty Level: 5/5") is not carried.

A person has to look (a review note) when the two answers through a square disagree, an
answer holds something other than a letter or digit, a clue doesn't start where a numbered
slot does or its answer is not the whole slot, or a numbered slot has no clue.
"""

from __future__ import annotations

import json

from ..xd import BLOCK, Clue, Puzzle, answer_at, clue_text, number_grid, plain
from . import Context, ConvertError


def sniff(data: bytes) -> bool:
    head = data[:400].lstrip()
    return head.startswith(b'{"crossword":') and b'"author_ids"' in head and b'"clues":' in data


def author_line(record: dict, authors: list[dict]) -> str:
    """The constructors' names in the record's author_ids order: "A", "A and B", "A, B and C"."""
    by_id = {a.get("id"): a for a in authors}
    ordered = [by_id.pop(i) for i in record.get("author_ids") or [] if i in by_id]
    ordered += by_id.values()  # anyone /authors names that the record doesn't
    names = [plain(f"{a.get('first_name') or ''} {a.get('last_name') or ''}") for a in ordered]
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        d = json.loads(data.decode("utf-8"))
        record = d["crossword"]
        clues = d["clues"]
        authors = d.get("authors") or []
        slots = [(c["is_across"], int(c["x"]), int(c["y"]), c["answer"] or "", c.get("clue") or "") for c in clues]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise ConvertError(f"not a Daily Princetonian puzzle: {e}") from e
    if not slots:
        raise ConvertError("no clues")
    if any(x < 0 or y < 0 for _, x, y, _, _ in slots):
        raise ConvertError("a clue starts off the grid")
    p = Puzzle()

    w = max(x + (len(a) if across else 1) for across, x, y, a, _ in slots)
    h = max(y + (1 if across else len(a)) for across, x, y, a, _ in slots)
    cells: dict[tuple[int, int], str] = {}  # (row, col) -> the letter as served
    for across, x, y, answer, _ in slots:
        for i, ch in enumerate(answer):
            r, c = (y, x + i) if across else (y + i, x)
            if not (ch.isascii() and ch.isalnum()):
                p.needs_review(f"answer {answer!r} has {ch!r} at row {r} col {c}")
            was = cells.get((r, c))
            if was is None:
                cells[r, c] = ch
            elif was.upper() != ch.upper():
                p.needs_review(f"square at row {r} col {c} is {was.upper()} one way and {ch.upper()} the other")
            elif ch.islower():
                cells[r, c] = ch  # circled, whichever answer says so
    if any(ch.islower() for ch in cells.values()):
        p.set("Special", "circle")
    p.grid = ["".join(cells.get((r, c), BLOCK) for c in range(w)) for r in range(h)]

    numbering = number_grid(p.grid)
    at = {(direction, pos): n for (direction, n), pos in numbering.items()}
    clued = set()
    for across, x, y, answer, text in slots:
        direction = "A" if across else "D"
        number = at.get((direction, (y, x)))
        if number is None:
            p.needs_review(f"{direction} clue {text!r} at row {y} col {x} doesn't start a numbered slot")
            continue
        clued.add((direction, number))
        if len(answer_at(p.grid, direction, y, x)) != len(answer):
            p.needs_review(f"{direction}{number}: answer {answer.upper()} is not the whole slot")
        p.clues.append(Clue(direction, number, clue_text(text), answer.upper()))
    for direction, number in sorted(set(numbering) - clued):
        p.needs_review(f"{direction}{number} has no clue")
    if not p.clues:
        raise ConvertError("no clue starts a numbered slot")

    p.set("Title", record.get("title") or "")
    author = author_line(record, authors)
    p.set("Author", author)
    if not author:
        p.tricky.append("no author")
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
        served = (record.get("date") or "")[:10]
        if served and served != ctx.date.isoformat():
            p.tricky.append(f"the record is dated {served}, file dated {ctx.date}")
    return p
