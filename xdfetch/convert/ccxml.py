"""Crossword Compiler documents (the `rectangular-puzzle` format, as in a `.jpz`), as XML:
Arkadium's Mini Crossword feed
(`ams.cdn.arkadiumhosted.com/assets/gamesfeed/minicrossword/puzzle_mini_YYMMDD.xml`), and
`.jpz` files from many outlets.

    <crossword-compiler><rectangular-puzzle>
      <metadata><title/><creator/><copyright/><description/></metadata>
      <crossword>
        <grid width="6" height="6"><cell x="1" y="1" solution="C" number="1"/><cell ... type="block"/></grid>
        <word id="1" x="3-5" y="1"/> ...
        <clues><title><b>Across</b></title><clue word="1" number="1">Bed for a baby</clue> ...</clues>
      </crossword>
    </rectangular-puzzle></crossword-compiler>

Cells are 1-based (x, y). A clue's answer is read from the cells of its `word`. Circled cells
(`background-shape="circle"`) become lowercase letters with `Special: circle`; a cell whose
solution is longer than one letter is a rebus square. A bar between two letters can't be
written in xd and is listed as tricky; a bar on the edge of a block or of the grid separates
nothing and is dropped. A numbered slot the file gives no clue is written `[XXX]` and needs
review, naming any clue that ends with that slot's number (where a dropped clue's number
can end up).

Conversion is in two steps, so that the same document can come in another wire format:
read() makes a plain dict of the XML, and build() makes the Puzzle from that dict. The dict's
keys are documented on build(). xdfetch.convert.ccjson reads the JSON form King Features'
puzzles come in into the same dict.

Outlet conventions come from ctx.params:

  title      `date`: the title is the date ("October 9, 2026"), for feeds whose titles are the
             game's name or a batch number (Arkadium). Otherwise the file's title, or the date
             when it has none.
  author     a fixed byline, for files whose creator names only the feature ("Thomas Joseph
             Crossword"). Otherwise the file's creator, with a feature name before " by "
             removed ("Sunday Crossword by A. Setter").
  dash       text to write for an em dash in a clue (`--`).
  endash     text to write for an en dash in a clue (`-`).
  quotes     `repair`: a space after a clue's opening quote mark is removed ('" -- Kapital'),
             and a clue with an odd number of double quotes is listed as tricky: King
             Features' files drop closing marks and cut clues short ('"Auld Lang'), which
             takes a person to mend.

Not done: King Features' data keeps the hyphen that broke a word for a newspaper column
("Appor-tions"), a few clues a year. Telling one from a real compound ("lead-in",
"Swiss-born", far more common) takes a person, so they are kept as they are.
"""

from __future__ import annotations

import datetime as dt
import re

from lxml import etree  # ty: ignore[import-not-found]  (a compiled module ty can't see into)

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, answer_at, clue_text, number_grid, plain
from . import Context, ConvertError

NS_LOCAL = "rectangular-puzzle"
KNOWN_CELL = {"x", "y", "solution", "number", "type", "left-bar", "top-bar", "background-shape"}


def sniff(data: bytes) -> bool:
    head = data[:2000]
    if b"rectangular-puzzle" not in head:
        return False
    return head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<")


# --- reading the XML into a plain dict ---


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _inner(el) -> str:
    """An element's content as HTML-ish text: child tags kept by local name, for clue_text()."""
    out = el.text or ""
    for child in el:
        name = _local(child.tag)
        out += f"<{name}>{_inner(child)}</{name}>" + (child.tail or "")
    return out


def _read_xml(data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace").lstrip("﻿")
    start = text.find("<")
    text = text[start:]  # some files have a stray character before the declaration
    text = re.sub(r"&(?!#?\w+;)", "&amp;", text)  # a bare & in a clue ("B&O")
    try:
        root = etree.fromstring(text.encode("utf-8"), etree.XMLParser(recover=True, resolve_entities=False))
    except etree.XMLSyntaxError as e:
        raise ConvertError(f"bad XML: {e}") from e
    if root is None:
        raise ConvertError("bad XML")
    rp = root if _local(root.tag) == NS_LOCAL else next((e for e in root.iter() if _local(e.tag) == NS_LOCAL), None)
    if rp is None:
        raise ConvertError("no rectangular-puzzle element")

    def child(el, name):
        return next((c for c in el if _local(c.tag) == name), None)

    def children(el, name):
        return [c for c in el if _local(c.tag) == name]

    md = child(rp, "metadata")
    meta = {_local(m.tag): "".join(m.itertext()) for m in md} if md is not None else {}
    cw = child(rp, "crossword")
    if cw is None:
        raise ConvertError("no crossword element (another kind of Crossword Compiler puzzle)")
    grid = child(cw, "grid")
    if grid is None:
        raise ConvertError("no grid")
    groups = []
    for g in children(cw, "clues"):
        title = child(g, "title")
        groups.append(
            (
                "".join(title.itertext()).strip() if title is not None else "",
                [(dict(c.attrib), _inner(c)) for c in children(g, "clue")],
            )
        )
    return {
        "meta": meta,
        "size": dict(grid.attrib),
        "cells": [dict(c.attrib) for c in children(grid, "cell")],
        "words": [dict(w.attrib) for w in children(cw, "word")],
        "groups": groups,
        "record": {},
        "lost": [],
    }


def read(data: bytes) -> dict:
    """The XML document as the dict build() takes."""
    return _read_xml(data)


# --- writing the puzzle ---


def span(s: str) -> range:
    a, _, b = str(s).partition("-")
    return range(int(a), int(b or a) + 1)


def date_title(d: dt.date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def dashes(text: str, dash: str | None, endash: str | None) -> str:
    """Em and en dashes written as the outlet's params say (`dash`, `endash`)."""
    if dash:
        text = text.replace("—", dash)
    if endash:
        text = text.replace("–", endash)
    return text


def convert(data: bytes, ctx: Context) -> Puzzle:
    return build(read(data), ctx)


def build(doc: dict, ctx: Context) -> Puzzle:
    """The Puzzle for a document read into a dict:

    meta    {"title", "creator", "copyright", "description"}: text
    size    {"width", "height"}
    cells   [{"x", "y", "solution", "number", "type", "background-shape", "left-bar", "top-bar"}]
    words   [{"id", "x", "y"}], x and y a number or a range "3-5"
    groups  [(title, [(attributes, html)])]: each clue group's title ("Across", "Down") and
            its clues, attributes {"word", "number"} and the text with inline tags kept
    record  (optional) the feed's own record of the puzzle; its "date" is checked
    lost    (optional) notes on what reading the document couldn't keep, for puzzle.tricky
    """
    params = ctx.params
    p = Puzzle()
    p.tricky.extend(doc.get("lost") or [])

    try:
        w, h = int(doc["size"]["width"]), int(doc["size"]["height"])
    except (KeyError, ValueError) as e:
        raise ConvertError(f"grid has no size: {e}") from e

    # the grid
    box: dict[tuple[int, int], str] = {}
    circled, rebus_cells, bars = set(), {}, []
    for c in doc["cells"]:
        try:
            xy = int(c["x"]), int(c["y"])
        except (KeyError, ValueError) as e:
            raise ConvertError(f"cell without a position: {c}") from e
        unknown = set(c) - KNOWN_CELL
        if unknown:
            p.tricky.append(f"cell {xy}: attributes xd can't carry ({', '.join(sorted(unknown))})")
        kind = c.get("type")
        if kind == "block":
            box[xy] = BLOCK
            continue
        if kind:
            raise ConvertError(f"cell {xy} is of type {kind!r}")
        sol = (c.get("solution") or "").strip().upper()
        if not sol:
            raise ConvertError(f"cell {xy} has no solution")
        if len(sol) > 1 or not (sol.isascii() and sol.isalnum()):
            rebus_cells[xy] = sol
        box[xy] = sol[:1] if sol.isascii() and sol.isalnum() else "?"
        if c.get("background-shape") == "circle":
            circled.add(xy)
        for attr in ("left-bar", "top-bar"):
            if c.get(attr) == "true":
                bars.append((xy, attr))
    if len(box) != w * h:
        raise ConvertError(f"{len(box)} cells for a {w}x{h} grid")
    for (x, y), attr in bars:
        other = (x - 1, y) if attr == "left-bar" else (x, y - 1)
        if box.get(other, BLOCK) != BLOCK:
            p.tricky.append(f"cell ({x}, {y}): a {attr} between two letters, not carried")

    letters = {xy: ch for xy, ch in box.items()}
    if rebus_cells:
        keys, table = iter(REBUS_KEYS), {}
        for xy in sorted(rebus_cells, key=lambda t: (t[1], t[0])):
            sol = rebus_cells[xy]
            if sol not in table:
                table[sol] = next(keys)
            letters[xy] = table[sol]
        p.set("Rebus", " ".join(f"{k}={v}" for v, k in table.items()))
    for xy in circled:
        if letters[xy].isalpha():
            letters[xy] = letters[xy].lower()
    if circled:
        p.set("Special", "circle")
    p.grid = ["".join(letters[x, y] for x in range(1, w + 1)) for y in range(1, h + 1)]

    # headers
    meta, record = doc["meta"], doc.get("record") or {}
    day = ctx.date
    if record.get("date") and day and record["date"] != day.isoformat():
        p.tricky.append(f"the feed dates this puzzle {record['date']}, filed as {day}")
    title = plain(meta.get("title", ""))
    if params.get("title") == "date" or not title:
        title = date_title(day) if day else title
    p.set("Title", title)
    author = params.get("author") or re.sub(r"^.*?\bby\s+", "", plain(meta.get("creator", "")), flags=re.I)
    p.set("Author", author)
    p.set("Copyright", re.sub(r"^©\s*", "© ", plain(meta.get("copyright", ""))))
    if day:
        p.set("Date", day.isoformat())
    if plain(meta.get("description", "")):
        p.notes = plain(meta["description"])

    # clues
    words = {}
    for wd in doc["words"]:
        try:
            xs, ys = span(wd["x"]), span(wd["y"])
        except (KeyError, ValueError) as e:
            raise ConvertError(f"word without cells: {wd}") from e
        words[str(wd.get("id"))] = ([(x, y) for y in ys for x in xs], len(xs) > 1)
    numbering = number_grid([row.upper() for row in p.grid])
    seen = set()
    for title_, clues in doc["groups"]:
        direction = {"across": "A", "down": "D"}.get(title_.strip().lower())
        if direction is None:
            raise ConvertError(f"clue group {title_!r} is neither Across nor Down")
        for attrs, raw in clues:
            number = int(attrs.get("number") or 0)
            path, across = words.get(str(attrs.get("word")), (None, None))
            if path is None:
                raise ConvertError(f"{direction}{number}: no word {attrs.get('word')!r}")
            if across != (direction == "A"):
                p.needs_review(f"{direction}{number}: its word runs the other way")
            answer = "".join(rebus_cells.get(xy, box[xy]) for xy in path)
            slot = numbering.get((direction, number))
            if slot is None or slot != (path[0][1] - 1, path[0][0] - 1):
                p.needs_review(f"{direction}{number}: the file's numbering differs from the grid's")
            text = clue_text(dashes(raw, params.get("dash"), params.get("endash")))
            if params.get("quotes") == "repair":
                text = re.sub(r'^" (?=\S)', '"', text)  # a space inside the opening mark ('" -- Kapital')
                if text.count('"') % 2:
                    p.tricky.append(f"{direction}{number}: unbalanced quotation marks: {text}")
            p.clues.append(Clue(direction, number, text, answer))
            seen.add((direction, number))
    if not p.clues:
        raise ConvertError("no clues")
    # a slot with no clue: a file can drop a clue and leave its number on the end of the
    # clue before ("Squabble 22")
    for (direction, number), (r, c) in sorted(numbering.items()):
        if (direction, number) in seen:
            continue
        p.clues.append(Clue(direction, number, "", answer_at(p.grid, direction, r, c).upper()))
        stray = [f"{x.direction}{x.number}" for x in p.clues if x.text.endswith(f" {number}")]
        p.needs_review(
            f"{direction}{number}: no clue in the file"
            + (f"; its number is on the end of {', '.join(stray)}" if stray else "")
        )
    return p
