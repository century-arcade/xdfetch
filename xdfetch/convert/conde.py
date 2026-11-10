"""Condé Nast's puzzle service record (The New Yorker), as the `conde` adapter saves it:
a JSON record whose `data` is the puzzle as xd-like text:

    ## Metadata
    title: The Crossword: Wednesday, October 28, 2026
    author: Ann Setter
    date: 2026-10-28          (the day it was made for; can differ from the day it ran)
    editor:
    copyright:
    subtitle: Today's theme: Birds.
    rebus: ⓐ=RS

    ## Grid
    DRAKE                     ('.' or '#' is a block; a rebus square is its key)
    W.B.R

    ## Clues
    A1. Male duck ~ DRAKE
    A5 ^refs: A1              (cross-references; not carried)

    ## Design                 (optional: a <style> naming letters, then a mask of the grid)
    <style> O { background: circle } </style>
    .....
    .#.#.
    ..O..

    ## Help, ## Pause Message, ## End Message   (player chrome)

Conventions, as the gxd corpus's New Yorker puzzles have them: the title keeps
the series prefix ("The Crossword: Wednesday, October 28, 2026") and gets " - <theme>" when
the subtitle names one; the Mini's title is the bare date. Circles are lowercase letters
with Special: circle; any other styled square is shading. Rebus keys are reassigned in
puz2xd's order. Clue text already uses xd markup; entities are decoded and typography
flattened. Refs are dropped; Help text is listed as tricky, since once in a while it is part
of the puzzle.
"""

from __future__ import annotations

import html
import json
import re

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, number_grid, plain
from . import Context, ConvertError

SECTION = re.compile(r"^## (.+?)\r?\n(.*?)(?=^## |\Z)", re.S | re.M)
CLUE = re.compile(r"^([AD])(\d+)\.\s*(.*?)\s*~\s*(.*)$")
STYLE = re.compile(r"(\S+)\s*\{([^}]*)\}")
MINI_TITLE = re.compile(r"^The Mini Crossword:\s*", re.I)


def sniff(data: bytes) -> bool:
    head = data[:200].lstrip()
    # Condé's record starts with its id, never with "data"
    return (
        head.startswith(b"{")
        and not head.startswith(b'{"data"')
        and b'"data"' in data
        and b"## Grid" in data
        and b"## Clues" in data
    )


def sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in SECTION.finditer(text):
        out[m.group(1).strip()] = out.get(m.group(1).strip(), "") + m.group(2)
    return out


def theme_of(subtitle: str) -> str:
    m = re.fullmatch(r"Today.s theme:\s*(.+)", plain(subtitle))
    if not m:
        return ""
    theme = m.group(1)
    if theme.endswith(".") and not theme.endswith("..."):
        theme = theme[:-1]
    return theme


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        record = json.loads(data.decode("utf-8"))
        text = record["data"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise ConvertError(f"not a service record with data: {e}") from e
    sec = sections(text)
    if "Grid" not in sec or "Clues" not in sec:
        raise ConvertError("data has no Grid or Clues section")
    meta: dict[str, str] = {}
    for line in sec.get("Metadata", "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    p = Puzzle()

    # marks from the Design section
    circled: set[tuple[int, int]] = set()
    shaded: set[tuple[int, int]] = set()
    design = sec.get("Design", "")
    if design.strip():
        styles = {}
        for name, body in STYLE.findall(re.sub(r"</?style>", "", design)):
            styles[name] = "circle" if "circle" in body else "shaded"
        mask = re.sub(r"<style>.*?</style>", "", design, flags=re.S).strip().splitlines()
        for r, row in enumerate(mask):
            for c, ch in enumerate(row.strip()):
                if ch in ".#":
                    continue
                if styles.get(ch, "shaded") == "circle":
                    circled.add((r, c))
                else:
                    shaded.add((r, c))
    if circled and shaded:
        p.tricky.append("both circled and shaded squares; the shading is kept as circles")
    marked = circled | shaded
    if circled:
        p.set("Special", "circle")
    elif shaded:
        p.set("Special", "shaded")

    # grid, reassigning the payload's rebus keys
    fills = dict(x.split("=", 1) for x in meta.get("rebus", "").split() if "=" in x)
    keys: dict[tuple[str, bool], str] = {}  # (value, marked) -> our key
    plain_keys = list(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid = []
    for r, row in enumerate(sec["Grid"].strip().splitlines()):
        out = ""
        for c, ch in enumerate(row.strip()):
            if ch in ".#":
                out += BLOCK
            elif ch in fills or not ch.isalpha() or not ch.isascii():
                value = plain(fills.get(ch, ch))
                k = (value, (r, c) in marked)
                if k not in keys:
                    try:
                        keys[k] = next(letters) if k[1] else plain_keys.pop(0)
                    except (StopIteration, IndexError):
                        raise ConvertError("more rebus values than keys") from None
                out += keys[k]
            else:
                out += ch.lower() if (r, c) in marked else ch.upper()
        grid.append(out)
    if not grid or len({len(x) for x in grid}) != 1:
        raise ConvertError("grid rows differ in length")
    p.grid = grid
    if keys:
        p.set("Rebus", " ".join(f"{k}={v[0]}" for v, k in keys.items()))

    # clues
    numbering = number_grid(grid)
    from ..xd import answer_at

    for line in sec["Clues"].splitlines():
        line = line.strip()
        if not line or "^refs:" in line:
            continue
        m = CLUE.match(line)
        if not m:
            p.needs_review(f"clue line not understood: {line[:60]}")
            continue
        direction, number, text_, answer = m.group(1), int(m.group(2)), m.group(3), m.group(4).strip()
        text_ = plain(html.unescape(text_))
        pos = numbering.get((direction, number))
        if pos is None:
            p.needs_review(f"{direction}{number}: clue has no slot in the grid")
            from_grid = ""
        else:
            from_grid = answer_at(grid, direction, *pos)
            expanded = "".join(next((v[0] for v, k in keys.items() if k == ch), ch.upper()) for ch in from_grid)
            if answer and answer.upper() != expanded.upper():
                p.needs_review(f"{direction}{number}: clue answer {answer} differs from grid {expanded}")
            answer = answer or expanded
        p.clues.append(Clue(direction, number, text_, answer.upper()))
    if not p.clues:
        raise ConvertError("no clues")

    # headers
    title = plain(meta.get("title", ""))
    theme = theme_of(meta.get("subtitle", ""))
    if MINI_TITLE.match(title):
        title = theme or MINI_TITLE.sub("", title)
    elif theme:
        title = f"{title} - {theme}"
    p.set("Title", title)
    p.set("Author", re.sub(r"\s+&\s+", " and ", plain(meta.get("author", ""))))
    p.set("Editor", meta.get("editor", ""))
    p.set("Copyright", meta.get("copyright", ""))
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
    help_text = plain(re.sub(r"<[^>]+>", "", re.sub(r"</?(?:div|p|br)[^>]*>", " ", sec.get("Help", ""))))
    if help_text:
        p.tricky.append(f"Help text not carried: {help_text[:120]}")
    return p
