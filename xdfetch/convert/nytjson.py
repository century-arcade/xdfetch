"""The New York Times's v6 puzzle JSON, as the `nyt` adapter saves it.

    {"publicationDate": "2026-01-01", "title": ..., "constructors": [...], "editor": ...,
     "copyright": "2026", "notes": [{"text": ..., "platforms": {...}}], "assets": ...,
     "body": [{"dimensions": {"width", "height"},
               "cells": [{} | {"answer": "T", "type": 1|2|3, "label": "1", "clues": [..],
                               "moreAnswers": {"valid": [...]}}],
               "clues": [{"label": "1", "direction": "Across", "cells": [...],
                          "text": [{"plain": ..., "formatted": ...}]}],
               "overlays": {...}}]}

Cell type 1 is plain, 2 circled, 3 shaded. The conventions are those of the gxd corpus's
New York Times puzzles:

- Title is the Times's where it has one (Sundays), else the weekday and date with the
  day zero-padded ("Thursday, January 01, 2026"), as gxd's earlier years have it.
- Author joins constructors with "and"; Editor; Copyright is "© <year>, The New York Times".
- Clue text is `formatted` where there is one (italics, bold, superscripts as xd markup),
  else `plain`; a picture clue becomes its description in brackets.
- Circled letters are lowercase with Special: circle; shaded with Special: shaded; both at
  once keeps the circles and lists the shading as tricky.
- Rebus squares get keys in puz2xd's order (1234567890*?@$%&+), a digit answer keeps its own
  digit, and a circled rebus gets a lowercase letter key.
- A square the answer leaves empty is a Rebus key with no value, listed as tricky; the clue
  sheet spells in what the Times also accepts there when that is one thing.
- Overlays, assets, squares with two readings and second clue texts are listed as tricky.
- Notes shown on the web or in print go in the notes section.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import string

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, number_grid, plain
from . import Context, ConvertError

SPECIAL = {2: "circle", 3: "shaded"}
MARKUP = {"i": "{/%s/}", "em": "{/%s/}", "b": "{*%s*}", "strong": "{*%s*}", "sup": "{^%s^}", "sub": "{~%s~}"}


def sniff(data: bytes) -> bool:
    head = data[:300].lstrip()
    return head.startswith(b"{") and b'"publicationDate"' in data and b'"cells"' in data


def tidy(text: str) -> str:
    text = re.sub("[\x80-\x9f]", "", text)  # stray bytes of a mis-encoded character
    return plain(text)


def _marked(m: re.Match) -> str:
    """xd markup around the words, with any space at the edges moved outside it."""
    inner = m.group(2)
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return lead + MARKUP[m.group(1).lower()] % core + trail


def clue_text(t: dict) -> tuple[str, bool]:
    """(the clue in xd's text and markup, whether it has a picture)."""
    fm = t.get("formatted")
    if fm is None:
        return tidy(t.get("plain", "")), False
    fm = re.sub(r"<!--.*?-->", "", fm, flags=re.S)
    fm = re.sub(r"</?(?:span|div|p)\b[^>]*>", "", fm)
    fm = re.sub(r"<br\s*/?>", " ", fm)
    pictures = re.findall(r"<img\b[^>]*>", fm)
    for tag in pictures:
        alt = re.search(r'\balt="([^"]*)"', tag)
        alt_text = alt.group(1).strip() if alt else ""
        if not alt_text or re.fullmatch(r"(?i)[tk]{4,}", alt_text):  # no description, or a placeholder
            alt_text = t.get("plain") or "picture"
        fm = fm.replace(tag, f"[{alt_text}]")
    for _ in range(3):  # nested markup, innermost first
        fm = re.sub(r"<(i|em|b|strong|sup|sub)>((?:(?!<\1>).)*?)</\1>", _marked, fm, flags=re.I | re.S)
    fm = re.sub(r"<[^>]+>", "", fm)  # any other tag: its text stays
    return tidy(html.unescape(fm)), bool(pictures)


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        p = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ConvertError(f"not JSON: {e}") from e
    if not isinstance(p, dict) or not p.get("body"):
        raise ConvertError("no body")
    b = p["body"][0]
    w, h = b["dimensions"]["width"], b["dimensions"]["height"]
    cells = b["cells"]
    if len(cells) != w * h:
        raise ConvertError(f"{len(cells)} cells for {w}x{h}")
    puz = Puzzle()
    tricky = puz.tricky
    review = puz.needs_review
    if len(p["body"]) > 1:
        review(f"{len(p['body'])} boards; only the first is here")

    def is_open(c) -> bool:
        return bool(c) and c.get("type", 1) != 0 and "clues" in c

    def mark(c) -> str | None:
        return SPECIAL.get(c.get("type"))

    kinds = {mark(c) for c in cells if is_open(c) and mark(c)}
    special = "circle" if "circle" in kinds else ("shaded" if kinds else None)

    def marked(c) -> bool:
        return special is not None and mark(c) == special

    if len(kinds) > 1:
        n = sum(mark(c) == "shaded" for c in cells if is_open(c))
        tricky.append(f"circles and shading together: {n} shaded squares kept as plain ones, the circles lowercase")

    def value(c) -> str:
        """The square's letters, or "" for a square the answer leaves empty. A symbol the
        Times also takes as a word is that word."""
        a = (c.get("answer") or "").strip()
        if a and not re.fullmatch(r"[A-Z0-9]+", a):
            word = next(
                (x for x in (c.get("moreAnswers") or {}).get("valid", []) if re.fullmatch(r"[A-Z]{2,}", x)), None
            )
            return word or a
        return a

    def spelled(c) -> str:
        """What the square adds to the clue-sheet answer: an empty square takes what the
        Times also accepts there, if that's one thing."""
        v = value(c)
        if v:
            return v
        valid = [x.strip() for x in (c.get("moreAnswers") or {}).get("valid", [])]
        letters = [x for x in valid if re.fullmatch(r"[A-Z]", x)]
        words = [x for x in valid if re.fullmatch(r"[A-Z]{2,}", x)]
        if not words:
            return letters[0] if len(letters) == 1 else ""
        return words[0] if len(words) == 1 and all(x == words[0][0] for x in letters) else ""

    def is_rebus(c) -> bool:
        return not re.fullmatch(r"[A-Z]", value(c))

    used_lower = {value(c).lower() for c in cells if is_open(c) and marked(c) and not is_rebus(c)}
    lower_keys = [k for k in string.ascii_lowercase if k not in used_lower]
    rebus: dict[tuple[str, bool], str] = {}  # (value, marked) -> key
    values = [(value(c), marked(c)) for c in cells if is_open(c) and is_rebus(c)]
    for v, m in values:  # a digit is its own key (gxd: 2=2)
        if re.fullmatch(r"\d", v) and not m and v not in rebus.values():
            rebus[(v, m)] = v
    plain_keys = [k for k in REBUS_KEYS if k not in rebus.values()]
    for v, m in values:
        if (v, m) not in rebus:
            try:
                rebus[(v, m)] = (lower_keys if m else plain_keys).pop(0)
            except IndexError:
                raise ConvertError("more rebus values than keys") from None

    rows = []
    for r in range(h):
        s = ""
        for c in cells[r * w : (r + 1) * w]:
            if not is_open(c):
                s += BLOCK
            elif is_rebus(c):
                s += rebus[(value(c), marked(c))]
            else:
                s += value(c).lower() if marked(c) else value(c)
        rows.append(s)
    puz.grid = rows

    empty = [i for i, c in enumerate(cells) if is_open(c) and not value(c)]
    if empty:
        took = sorted({spelled(cells[i]) for i in empty} - {""})
        msg = f"{len(empty)} squares the answer leaves empty (Rebus key with no value)"
        if took:
            msg += f"; the clue sheet spells in what the Times also accepts there ({', '.join(took)})"
        review(msg)
    readings = {
        value(c): next(x for x in c["moreAnswers"]["valid"] if "/" in x)
        for c in cells
        if is_open(c) and any("/" in x for x in (c.get("moreAnswers") or {}).get("valid", []))
    }
    if readings:
        review(
            "squares with two readings: the Times also takes "
            + ", ".join(f"{v} for {k}" for k, v in sorted(readings.items()))
            + "; here each square is read the same both ways"
        )
    odd = sorted({value(c) for c in cells if is_open(c) and not re.fullmatch(r"[A-Z]*", value(c))})
    if odd:
        tricky.append(f"symbol squares {' '.join(odd)} as Rebus keys")

    pictures = []
    for cl in b["clues"]:
        texts = cl["text"]
        text, picture = clue_text(texts[0])
        label = cl["label"] + cl["direction"][0]
        if picture:
            pictures.append(label)
        answer = "".join(spelled(cells[i]) for i in cl["cells"])
        if not answer:  # all empty squares: the word the Times takes for them
            first = cells[cl["cells"][0]]
            answer = next(
                (x for x in (first.get("moreAnswers") or {}).get("valid", []) if re.fullmatch(r"[A-Z]{2,}", x)), ""
            )
        try:
            number = int(cl["label"])
        except ValueError:
            review(f"{label}: clue label is not a number")
            continue
        puz.clues.append(Clue(cl["direction"][0], number, text, answer))
        if len(texts) > 1:
            review(f"{label}: more than one clue text; only the first is here")
    if pictures:
        tricky.append(f"picture clues {', '.join(pictures)}: the picture's description, in brackets")
    if not puz.clues:
        raise ConvertError("no clues")

    # the Times's numbering against xd's: each clue must start where xd numbers it
    numbering = number_grid(rows)
    off = []
    for cl in b["clues"]:
        if not cl["label"].isdigit():
            continue
        r, c = divmod(cl["cells"][0], w)
        if numbering.get((cl["direction"][0], int(cl["label"]))) != (r, c):
            off.append(cl["label"] + cl["direction"][0])
    if off:
        review("clues xd's numbering doesn't give the same squares: " + ", ".join(off))
    elif len(puz.clues) != len(numbering):
        review("an entry with no clue, or a clue with no entry")

    if b.get("overlays") or p.get("assets"):
        when = ", ".join(k for k, v in (b.get("overlays") or {}).items() if v) or "assets"
        tricky.append(f"a picture or animation over the grid ({when}), not in the .xd")

    d = p.get("publicationDate") or (ctx.date.isoformat() if ctx.date else "")
    if ctx.date and p.get("publicationDate") and p["publicationDate"] != ctx.date.isoformat():
        tricky.append(f"payload publicationDate is {p['publicationDate']}, file dated {ctx.date}")
    day = dt.date.fromisoformat(d) if d else ctx.date
    title = tidy(p.get("title") or "")
    if not title and day:
        title = f"{day:%A}, {day:%B %d, %Y}"  # gxd's NYT zero-pads the day
    puz.set("Title", title)
    puz.set("Author", " and ".join(tidy(a) for a in p.get("constructors") or []))
    puz.set("Editor", p.get("editor") or "")
    puz.set("Copyright", f"© {p.get('copyright') or (d[:4] if d else '')}, The New York Times")
    if d:
        puz.set("Date", d)
    if rebus:
        puz.set("Rebus", " ".join(f"{k}={v[0]}" for v, k in rebus.items()))
    if special and any(marked(c) for c in cells if is_open(c)):
        puz.set("Special", special)
    notes = [
        tidy(n["text"])
        for n in p.get("notes") or []
        if n.get("text", "").strip()
        and (not n.get("platforms") or n["platforms"].get("web") or n["platforms"].get("pdf"))
    ]
    puz.notes = "\n".join(notes)
    return puz
