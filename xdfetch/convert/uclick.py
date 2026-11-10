"""uclick XML: Andrews McMeel's feed for Universal (fcx), USA Today (usaon), Universal
Sunday (usun) and others.

    <crossword>
      <Title v="On the Road" />
      <Author v="By A. Setter" />
      <Category v="Universal Daily Crosswords" />
      <Copyright v="Andrews McMeel Syndication" />
      <Editor v="B. Editor" />
      <Width v="15" /> <Height v="15" />
      <AllAnswer v="DRAKE-HOP-..." />               (- is a block)
      <across> <a1 a="DRAKE" c="Male duck" n="1" cn="1" /> ... </across>
      <down> ... </down>
    </crossword>

Text is URL-encoded (%22, %27); the byline starts "By ". The feed carries no circles,
shading or rebus. After xd's xdfile/uxml2xd.py.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from lxml import etree  # ty: ignore[import-not-found]  (a compiled module ty can't see into)

from ..xd import BLOCK, Clue, Puzzle, answer_at, clue_text, number_grid
from . import Context, ConvertError

HEADERS = ["Title", "Author", "Editor", "Copyright", "Category"]


def sniff(data: bytes) -> bool:
    head = data[:400].lstrip(b"\xef\xbb\xbf \r\n\t")
    # the root element is <crossword>: not <crossword-compiler>, whose <crossword> is nested (ccxml)
    return bool(re.match(rb"(<\?xml[^>]*>\s*)?<crossword[\s/>]", head))


def decode(value: str) -> str:
    return unquote(value)


def convert(data: bytes, ctx: Context) -> Puzzle:
    text = data.decode("utf-8", errors="replace").lstrip("﻿")
    # the feed sometimes doubles quotes inside attributes: c="He said ""hi"""
    text = re.sub(r'(=["]{2}([^"]+?)["]{2})+', r'="&quot;\2&quot;"', text)
    try:
        root = etree.fromstring(text.encode("utf-8"), etree.XMLParser(recover=True))
    except etree.XMLSyntaxError as e:
        raise ConvertError(f"bad XML: {e}") from e
    if root is None or root.tag != "crossword":
        raise ConvertError("not a uclick <crossword> document")

    def attr(tag: str) -> str:
        el = root.find(tag)
        return decode(el.get("v", "")) if el is not None else ""

    p = Puzzle()
    values = {h: attr(h) for h in HEADERS}
    author = re.sub(r"^\s*by\s+", "", values["Author"], flags=re.IGNORECASE)
    m = re.search(r",?\s*edited\s+by\s+(.+)$", author, flags=re.IGNORECASE)
    if m:  # the byline names the editor: it beats the feed's Editor field, which can be another series' editor
        values["Editor"] = m.group(1).strip()
        author = author[: m.start()].strip()
    elif re.search(r",\s*edited\s*$", author, flags=re.IGNORECASE):
        author = re.sub(r",\s*edited\s*$", "", author, flags=re.IGNORECASE)
        p.tricky.append(
            f"byline truncated by the feed ({values['Author']!r}); the Editor header is the feed's, which may be wrong"
        )
    values["Author"] = author
    for h in HEADERS:
        if values[h]:
            p.set(h, values[h])
    if ctx.date:
        p.set("Date", ctx.date.isoformat())

    width = int(attr("Width") or 0)
    height = int(attr("Height") or 0)
    answers = attr("AllAnswer").replace("-", BLOCK)
    if not width or not height:
        raise ConvertError("no Width/Height")
    if len(answers) != width * height:
        raise ConvertError(f"AllAnswer has {len(answers)} cells, expected {width}x{height}")
    p.grid = [answers[i * width : (i + 1) * width] for i in range(height)]

    numbering = number_grid(p.grid)
    for direction, tag in (("A", "across"), ("D", "down")):
        section = root.find(tag)
        if section is None:
            continue
        for el in section:
            number = int(el.get("cn") or el.get("n") or 0)
            answer = (el.get("a") or "").strip()
            # the feed encodes an apostrophe as %27; once (USA Today 2026-10-29) it also kept
            # the cp1252 quote in front of it, giving '' after flattening. The corpus has no ''.
            text_ = clue_text(decode(el.get("c") or "")).replace("''", "'")
            pos = numbering.get((direction, number))
            if pos is None:
                p.needs_review(f"{direction}{number}: clue has no slot in the grid")
            else:
                from_grid = answer_at(p.grid, direction, *pos)
                if answer and answer != from_grid:
                    p.needs_review(f"{direction}{number}: clue answer {answer} differs from grid {from_grid}")
                answer = answer or from_grid
            p.clues.append(Clue(direction, number, text_, answer))
    if not p.clues:
        raise ConvertError("no clues")
    return p
