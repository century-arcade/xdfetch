"""PZLR's crossword level (The Wall Street Journal), as the `puzzlr` adapter saves it: a
one-element tRPC batch.

    [{"result": {"data": {"date": "2026-10-28", "shortId": "...", "data": {
        "title": "Birds of a Feather", "author": "By Ann Setter/Edited by Cy Editor",
        "subtitle": "Thursday",                (the print weekday)
        "date": "2026-10-28", "width": 15, "height": 15,
        "description": "© The Wall Street Journal",      (older payloads)
        "grid": [[{"answer": "R", "clueNumber": 1, "isBlack": false, "isCircled": true}, ...]],
        "clues": {"across": [{"number": 1, "text": "...", "answer": "RPM", "direction": "across"}], "down": [...]},
        "contestMode": true, "contestClueText": "...", "contestAnswer": "The contest answer is DECIDE. ..."}}}}]

Payloads from before PZLR's 2026 format change carry no circles or rebus squares, and
carry the copyright as `description`.

Conventions: "By A/Edited by B" splits into Author and Editor; Copyright is the payload's
description when it is one, else the row's `copyright` param; circled letters are lowercase
with Special: circle; a square holding more than a letter is a rebus square. A contest
puzzle gets a `Meta: <prompt> ~ <ANSWER>` header with the prompt also in the notes, and the
explanation (which names the answer) is listed as tricky, not written.

A contest puzzle is served without its answers until the contest closes (Friday's, through
Sunday night). It is written with every white square an X, a placeholder that a re-fetch
replaces once the answers are out, and the prompt as the notes.

The payload's own date is checked against the date the file is filed under, moved by the
row's `offset` param (days added to that date to get PZLR's; see the adapter), and its
weekday subtitle against the filed date's weekday.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, answer_at, clue_text, number_grid, plain
from . import Context, ConvertError

WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def sniff(data: bytes) -> bool:
    head = data[:120].lstrip()
    return (head.startswith(b"[{") or head.startswith(b"{")) and b'"result"' in data[:200] and b'"grid"' in data


def split_author(author: str) -> tuple[str, str]:
    author = re.sub(r"^\s*by\s+", "", author.strip(), flags=re.I)
    m = re.match(r"^(.*?)\s*/\s*(?:edited\s+by|ed\.)\s*(.+)$", author, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return author, ""


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        body = json.loads(data.decode("utf-8"))
        result = (body[0] if isinstance(body, list) else body)["result"]["data"]
        d = result["data"]
        grid_in = d["grid"]
        w, h = int(d["width"]), int(d["height"])
    except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError) as e:
        raise ConvertError(f"not a PZLR level: {e}") from e
    if len(grid_in) != h or any(len(row) != w for row in grid_in):
        raise ConvertError(f"grid is not {w}x{h}")
    p = Puzzle()
    withheld = not any((cell.get("answer") or "").strip() for row in grid_in for cell in row if not cell.get("isBlack"))
    if withheld:
        until = d.get("contestDeadlineAt") or "the source publishes them"
        p.tricky.append(f"answers withheld until {until}: X placeholders until a re-fetch has them")

    circled = {(r, c) for r, row in enumerate(grid_in) for c, cell in enumerate(row) if cell.get("isCircled")}
    if circled:
        p.set("Special", "circle")
    rebus: dict[str, str] = {}
    plain_keys = iter(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid = []
    for r, row in enumerate(grid_in):
        out = ""
        for c, cell in enumerate(row):
            a = (cell.get("answer") or "").strip()
            if cell.get("isBlack"):
                out += BLOCK
            elif not a and withheld:
                out += "X"
            elif not a:
                out += " "
                p.needs_review(f"empty square at row {r} col {c}")
            elif len(a) == 1 and a.isalpha() and a.isascii():
                out += a.lower() if (r, c) in circled else a.upper()
            else:
                value = a.upper() if a.isalpha() else a
                if value not in rebus:
                    try:
                        rebus[value] = next(letters) if (r, c) in circled else next(plain_keys)
                    except StopIteration:
                        raise ConvertError("more rebus values than keys") from None
                out += rebus[value]
        grid.append(out)
    p.grid = grid
    if rebus:
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in rebus.items()))

    numbering = number_grid([row.replace(" ", "?") for row in grid])
    for dirn in ("across", "down"):
        for cl in d.get("clues", {}).get(dirn, []):
            direction = "A" if dirn == "across" else "D"
            number = int(cl["number"])
            pos = numbering.get((direction, number))
            answer = (cl.get("answer") or "").strip().upper()
            if pos is None:
                p.needs_review(f"{direction}{number}: clue has no slot in the grid")
            else:
                from_grid = answer_at(grid, direction, *pos)
                expanded = "".join(next((v for v, k in rebus.items() if k == ch), ch.upper()) for ch in from_grid)
                if answer and answer != expanded:
                    p.needs_review(f"{direction}{number}: clue answer {answer} differs from grid {expanded}")
                answer = answer or expanded
            text = cl.get("text") or ""
            text = clue_text(text) if re.search(r"<\w+", text) else plain(text)
            p.clues.append(Clue(direction, number, text, answer))
    if not p.clues:
        raise ConvertError("no clues")

    p.set("Title", d.get("title") or "")
    author, editor = split_author(plain(d.get("author") or ""))
    p.set("Author", re.sub(r"\s+&\s+", " and ", author))
    if editor:
        p.set("Editor", editor)
    description = plain(d.get("description") or "")
    if description.startswith("©"):
        p.set("Copyright", description)
    elif ctx.params.get("copyright"):
        p.set("Copyright", ctx.params["copyright"])
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
        subtitle = plain(d.get("subtitle") or "").lower()
        if subtitle in WEEKDAYS and subtitle != ctx.date.strftime("%A").lower():
            p.tricky.append(f"payload says {subtitle.title()}, file dated {ctx.date:%A} {ctx.date}")
        offset = int(ctx.params.get("offset", "0"))
        theirs = d.get("date") or result.get("date")
        if theirs and dt.date.fromisoformat(theirs) != ctx.date + dt.timedelta(days=offset):
            p.tricky.append(f"payload date is {theirs}, file dated {ctx.date} (offset {offset})")

    notes = []
    if d.get("contestMode"):
        prompt = plain(d.get("contestClueText") or "")
        explanation = plain(d.get("contestAnswer") or "")
        m = re.search(r"contest answer is ([A-Z][A-Z0-9' ,\-]*?)[.!]", explanation)
        if prompt and m:
            p.set("Meta", f"{prompt} ~ {m.group(1).strip()}")
            notes.append(prompt)
        elif prompt:  # the answer comes after the deadline (withheld); the prompt is kept as the notes
            notes.append(prompt)
            if not withheld:
                p.tricky.append("contest puzzle: no answer found in the payload")
        else:
            p.tricky.append("contest puzzle: no prompt in the payload")
        if explanation:
            p.tricky.append(f"contest explanation not carried (it names the answer): {explanation[:100]}")
    p.notes = "\n".join(notes)
    return p
