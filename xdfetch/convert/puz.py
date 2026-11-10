"""Across Lite `.puz`, as many outlets serve it (Arkadium's feed of its 2 Minute Mini, for one:
`ams.cdn.arkadiumhosted.com/assets/gamesfeed/.../mini/puzzle_YYMMDD.puz`). Read, never written.

The layout (the reverse-engineered format, as puz.py and xd's puz2xd read it): a 0x34-byte
header (magic `ACROSS&DOWN\\0` at 0x02, width at 0x2C, height at 0x2D, clue count at 0x2E,
scrambled flag at 0x32), the solution and the solver's grid (width x height bytes each, `.` a
block), then NUL-terminated strings in Latin-1: title, author, copyright, the clues in grid
order (for each numbered square, its across clue before its down), notes. After them, tagged
sections: GRBS + RTBL (rebus squares), GEXT (0x80 = circled).

Checksums are not checked: feeds serve some files whose stored checksums are wrong but
whose content is sound. Text goes through xd's mojibake repair,
as puz2xd does. A doubled apostrophe (`''Pet'' annoyance`) is a double quote: the corpus never
has `''`.

params: `title=date` (the title is the date, "October 9, 2026"), as in ccxml.
"""

from __future__ import annotations

import struct

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, clue_text, number_grid, plain
from . import Context, ConvertError
from .ccxml import date_title

MAGIC = b"ACROSS&DOWN\0"


def sniff(data: bytes) -> bool:
    return data[2:14] == MAGIC


def _sections(data: bytes, pos: int) -> dict[bytes, bytes]:
    out = {}
    while pos + 8 <= len(data):
        tag = data[pos : pos + 4]
        (length,) = struct.unpack_from("<H", data, pos + 4)
        body = data[pos + 8 : pos + 8 + length]
        if len(body) < length:
            break
        out[tag] = body
        pos += 8 + length + 1  # each section ends with a NUL
    return out


def convert(data: bytes, ctx: Context) -> Puzzle:
    if not sniff(data) or len(data) < 0x34:
        raise ConvertError("not an Across Lite file")
    w, h = data[0x2C], data[0x2D]
    (nclues,) = struct.unpack_from("<H", data, 0x2E)
    (scrambled,) = struct.unpack_from("<H", data, 0x32)
    if scrambled:
        raise ConvertError("the solution is scrambled")
    n = w * h
    solution = data[0x34 : 0x34 + n].decode("latin-1")
    pos = 0x34 + 2 * n
    strings = []
    for _ in range(3 + nclues + 1):
        end = data.find(b"\0", pos)
        if end < 0:
            raise ConvertError("the file ends inside its strings")
        strings.append(data[pos:end].decode("latin-1"))
        pos = end + 1
    title, author, copyright_, *clues = strings
    notes = clues.pop()
    sections = _sections(data, pos)

    p = Puzzle()
    rows = [solution[r * w : (r + 1) * w].replace(".", BLOCK) for r in range(h)]
    if any(ch != BLOCK and not ch.isalnum() for row in rows for ch in row):
        raise ConvertError("a square of the solution is neither a letter nor a block")
    numbering = number_grid(rows)
    grid = [list(row) for row in rows]
    answers_override = {}
    if b"GRBS" in sections and b"RTBL" in sections:
        table = {}
        for item in sections[b"RTBL"].decode("latin-1").split(";"):
            if ":" in item:
                k, v = item.split(":", 1)
                table[int(k.strip())] = v
        keys, assigned = iter(REBUS_KEYS), {}
        for i, b in enumerate(sections[b"GRBS"][:n]):
            if b:
                sol = table.get(b - 1)
                if sol is None:
                    raise ConvertError(f"rebus square {i} has no entry in RTBL")
                if sol not in assigned:
                    assigned[sol] = next(keys)
                grid[i // w][i % w] = assigned[sol]
                answers_override[(i // w, i % w)] = sol
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in assigned.items()))
    if b"GEXT" in sections:
        circled = [i for i, b in enumerate(sections[b"GEXT"][:n]) if b & 0x80]
        for i in circled:
            ch = grid[i // w][i % w]
            if ch.isalpha():
                grid[i // w][i % w] = ch.lower()
        if circled:
            p.set("Special", "circle")
        if any(b & ~0x80 & 0xFF for b in sections[b"GEXT"][:n]):
            p.tricky.append("GEXT square flags other than circles, not carried")
    p.grid = ["".join(r) for r in grid]

    if ctx.params.get("title") == "date" and ctx.date:
        title = date_title(ctx.date)
    p.set("Title", title or (date_title(ctx.date) if ctx.date else ""))
    p.set("Author", author)
    p.set("Copyright", copyright_)
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
    if plain(notes):
        p.notes = plain(notes)

    slots = sorted(numbering.items(), key=lambda kv: (kv[1], kv[0][0]))
    if len(slots) != len(clues):
        raise ConvertError(f"{len(clues)} clues for {len(slots)} slots")
    for ((direction, number), (r, c)), raw in zip(slots, clues, strict=True):
        dr, dc = (0, 1) if direction == "A" else (1, 0)
        answer, rr, cc = "", r, c
        while rr < h and cc < w and rows[rr][cc] != BLOCK:
            answer += answers_override.get((rr, cc), rows[rr][cc])
            rr, cc = rr + dr, cc + dc
        p.clues.append(Clue(direction, number, clue_text(raw.replace("''", '"')), answer))
    return p
