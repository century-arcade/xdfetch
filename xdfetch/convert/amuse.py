"""Amuse Labs (PuzzleMe) puzzle JSON, as the `amuse` adapter saves it (the player's `rawc`,
unscrambled).

The fields used:
  title, author, copyright, description, subtitle      headers and notes
  publishTime (ms), publishTimeZone                   checked against the puzzle's date
  w, h, box[col][row]                                 the grid: "\\x00" is a block, "" an empty
                                                      square, several characters a rebus
  cellInfos[{x, y, isCircled, bgColor, fgColor,        circles and shading; bars, voids and
             rightWall, bottomWall, isVoid}]           images are listed as tricky
  placedWords[{x, y, acrossNotDown, clueNum, nBoxes,
               clue: {clue}}]                          the clues; clue text has <i>, <b>, <sup>, <a>
  unlinkGridAndClues, clueSections, puzzleType        anything unusual needs review or is tricky

A byline "A / Ed. B" (or "A, edited by B") splits into Author and Editor; "A & B" becomes
"A and B". Circled letters are lowercase with `Special: circle`, shaded ones lowercase with
`Special: shaded` (both kinds at once is tricky: the shading is kept as circles). A rebus
square gets a digit key, or a lowercase letter key when it is circled or shaded. The
description and subtitle go in the notes; the player's own messages (help, pauseMessage,
endMessage) are not carried. A puzzle with no title is titled by its date ("October 28, 2026").

Outlet conventions come from ctx.params:
  publish_offset  days from the puzzle's date to the payload's publishTime, for an outlet that
                  uploads the evening before (-1); otherwise a publishTime on another day is
                  tricky
  editor          the outlet's editor, for bylines that name none. Left off a puzzle whose
                  author line names the editor.
  title_drop      text to leave out of the title, such as "(Themeless)"
  copyright=year  write "(c)" and a bare year as "© year", and give a line with no year the
                  puzzle's year
"""

from __future__ import annotations

import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, clue_text, number_grid, plain
from . import Context, ConvertError
from .ccxml import date_title

BLOCK_CELL = "\x00"


def sniff(data: bytes) -> bool:
    head = data[:200].lstrip()
    return head.startswith(b"{") and b'"placedWords"' in data and b'"box"' in data


def split_author(author: str) -> tuple[str, str]:
    """'Ann Setter / Ed. Cy Editor' -> ('Ann Setter', 'Cy Editor')."""
    m = re.match(r"^(.*?)\s*/\s*Ed(?:ited|\.)?\s*(?:by\s+)?(.+)$", author, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*?)\s*[,;]\s*edited by\s+(.+)$", author, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return author.strip(), ""


def normalise_author(author: str) -> str:
    author = re.sub(r"^\s*by\s+", "", author, flags=re.I)
    return re.sub(r"\s+&\s+", " and ", author)


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        d = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ConvertError(f"not JSON: {e}") from e
    if not isinstance(d, dict) or "box" not in d or "placedWords" not in d:
        raise ConvertError("not an Amuse Labs puzzle (no box/placedWords)")
    p = Puzzle()
    params = ctx.params
    w, h = int(d.get("w") or 0), int(d.get("h") or 0)
    box = d["box"]
    if not w or not h or len(box) != w or any(len(col) != h for col in box):
        raise ConvertError(f"box is not {w}x{h}")
    if d.get("puzzleType", "CROSSWORD") != "CROSSWORD":
        p.needs_review(f"puzzleType is {d.get('puzzleType')}")
    if d.get("unlinkGridAndClues"):
        p.needs_review("unlinkGridAndClues: clues are not tied to grid slots")

    # headers
    title = plain(d.get("title") or "")
    if params.get("title_drop"):
        title = plain(title.replace(params["title_drop"], " "))
    if ctx.date and not title:
        title = date_title(ctx.date)
    p.set("Title", title)
    author, editor = split_author(plain(d.get("author") or ""))
    p.set("Author", normalise_author(author))
    if "Author" not in p.headers:
        p.tricky.append("no author in the source")
    outlet_editor = params.get("editor", "")
    if not editor and outlet_editor and outlet_editor not in p.headers.get("Author", ""):
        editor = outlet_editor
    if editor:
        p.set("Editor", editor)
    p.set("Copyright", copyright_line(d.get("copyright") or "", ctx))
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
    published = publish_date(d)
    offset = int(params.get("publish_offset", "0"))
    if ctx.date and published and published != ctx.date + dt.timedelta(days=offset):
        p.tricky.append(f"payload publishTime is {published}, file dated {ctx.date}")

    # cell marks
    circled: set[tuple[int, int]] = set()
    shaded: set[tuple[int, int]] = set()
    for ci in d.get("cellInfos") or []:
        x, y = int(ci.get("x", -1)), int(ci.get("y", -1))
        is_block = 0 <= x < w and 0 <= y < h and box[x][y] == BLOCK_CELL
        if ci.get("isCircled"):
            circled.add((y, x))
        if ci.get("bgColor") and not is_block:  # fgColor is the text's colour; a bgColor on a block is styling
            shaded.add((y, x))
        if ci.get("isVoid"):
            p.tricky.append(f"void cell at row {y} col {x}")
        if ci.get("rightWall") or ci.get("bottomWall"):
            p.tricky.append(f"bar at row {y} col {x}")
        if ci.get("bgImage") or ci.get("image"):
            p.tricky.append(f"image in cell at row {y} col {x}")
    if circled and shaded:
        p.tricky.append("both circled and shaded squares; xd marks only one kind (shading kept as circles)")
    marked = circled | shaded
    if circled:
        p.set("Special", "circle")
    elif shaded:
        p.set("Special", "shaded")

    # grid, with rebus keys
    rebus: dict[str, str] = {}  # value -> key
    plain_keys = iter(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid: list[str] = []
    for r in range(h):
        row = []
        for c in range(w):
            cell = box[c][r]
            if cell == BLOCK_CELL:
                row.append(BLOCK)
            elif cell == "":
                row.append(" ")
                p.needs_review(f"empty square at row {r} col {c}")
            elif len(cell) == 1 and cell.isalpha() and cell.isascii():
                row.append(cell.lower() if (r, c) in marked else cell.upper())
            else:
                value = cell.upper() if cell.isalpha() else cell
                key = rebus.get(value)
                if key is None:
                    try:
                        key = next(letters) if (r, c) in marked else next(plain_keys)
                    except StopIteration:
                        raise ConvertError("more rebus values than keys") from None
                    rebus[value] = key
                row.append(key)
        grid.append("".join(row))
    p.grid = grid
    if rebus:
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in rebus.items()))
    for r, c in sorted(circled):
        if not (0 <= r < h and 0 <= c < w) or grid[r][c] == BLOCK:
            p.tricky.append(f"circle on a block at row {r} col {c}")

    # clues
    numbering = number_grid([row.replace(" ", "?") for row in grid])
    sections = {pw.get("clueSection") for pw in d["placedWords"] if pw.get("clueSection")}
    if sections - {"Across", "Down", ""}:
        p.tricky.append(f"clue sections: {', '.join(sorted(s for s in sections if s))}")
    for pw in d["placedWords"]:
        across = pw.get("acrossNotDown", pw.get("direction") == "E")
        direction = "A" if across else "D"
        try:
            number = int(pw.get("clueNum"))
        except (TypeError, ValueError):
            p.needs_review(f"clue with no number at row {pw.get('y')} col {pw.get('x')}")
            continue
        x, y, n = int(pw["x"]), int(pw["y"]), int(pw.get("nBoxes") or 0)
        cells = [box[x + i][y] if across else box[x][y + i] for i in range(n)]
        answer = "".join(cell.upper() if cell.isalpha() else cell for cell in cells if cell != BLOCK_CELL)
        clue = pw.get("clue")
        raw = clue.get("clue", "") if isinstance(clue, dict) else str(clue or "")
        if re.search(r"<a\s", raw, flags=re.I):
            p.tricky.append(f"{direction}{number}: link in clue; the words are kept, the URL is not")
        if re.search(r"<img\s", raw, flags=re.I):
            p.tricky.append(f"{direction}{number}: image in clue")
        if numbering.get((direction, number)) != (y, x):
            p.needs_review(f"{direction}{number}: numbered at row {y} col {x}, standard numbering disagrees")
        p.clues.append(Clue(direction, number, clue_text(raw), answer))
    if not p.clues:
        raise ConvertError("no clues")

    notes = [plain(d.get(k) or "") for k in ("subtitle", "description")]
    p.notes = "\n".join(n for n in notes if n)
    return p


def copyright_line(text: str, ctx: Context) -> str:
    """The payload's copyright, as served unless the row says `copyright=year`: then "(c)"
    and a bare year are written "© year", and a line with no year takes the puzzle's."""
    text = plain(text)
    if ctx.params.get("copyright") != "year" or not text:
        return text
    text = re.sub(r"^\(c\)\s*", "© ", text, flags=re.I)
    if re.fullmatch(r"\d{4}", text):
        return f"© {text}"
    if ctx.date and not re.search(r"\d{4}", text):
        return f"© {ctx.date.year} {text.removeprefix('©').strip()}"
    return text


def publish_date(d: dict) -> dt.date | None:
    ts = d.get("publishTime")
    if not ts:
        return None
    tz = d.get("publishTimeZone") or "America/New_York"
    try:
        return dt.datetime.fromtimestamp(int(ts) / 1000, ZoneInfo(tz)).date()
    except (ValueError, TypeError, OverflowError, OSError, KeyError):
        return None
