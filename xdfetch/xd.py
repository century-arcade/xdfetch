"""A puzzle, and how it's written as .xd.

Converters build a Puzzle; this module writes it in xdfetch's house style, which follows
the conventions of the public xd corpus (https://xd.saul.pw):

- UTF-8; curly quotes, ellipses and no-break spaces flattened to ASCII; whitespace
  collapsed; accents and em dashes kept; mojibake repaired as xd's own tools repair it.
- Markup only in clues, as {/i/}, {*b*}, {_u_}, {-s-}, {^sup^}, {~sub~}.
- Headers in the order Title, Author, Editor, Copyright, Number, Date, Relation, Special,
  Rebus, Cluegroup, Description, Notes, then any others; empty ones left out.
- Circled squares as lowercase letters with `Special: circle` (shaded: `Special: shaded`).
- Rebus keys handed out as xd's puz2xd does (1234567890*?@$%&+ and on); a circled rebus
  square takes a lowercase letter key.
- Where an outlet's titles say nothing (the `title=date` param), the title is the date,
  written "October 9, 2026" (date_title() in xdfetch.convert.ccxml).
- A clue with no text is written [XXX]; a file without notes ends with a blank line.

The result passes xdlint.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

BLOCK = "#"
GRID_CHARS = re.compile(r"[^A-Za-z0-9#._]")  # what xdlint (XD002) accepts in a grid row, plus declared rebus keys
# Keys for rebus squares that aren't circled, in the order they're handed out: xd's puz2xd
# order (some puzzles need over 30). Circled rebus squares take
# lowercase letters instead. Any single printable character is a valid key (spec: "digits,
# most symbols, and printable unicode characters"); xdlint accepts whatever the header declares.
REBUS_KEYS = "1234567890*?@$%&+♠♥♦♣⚀⚁⚂⚃⚄⚅♟♞♝♜♛♚⅕⅖⅗⅘♳♴♵♶♷♸♹☿♀♁♂♃♄⛢♆♇⚳⚷"

HEADER_ORDER = [
    "title",
    "author",
    "editor",
    "copyright",
    "number",
    "date",
    "relation",
    "special",
    "rebus",
    "cluegroup",
    "description",
    "notes",
]

FLAT = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "…": "...",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        "\u200b": "",  # zero-width space
        "﻿": "",
    }
)

MARKUP = [
    (re.compile(r"<\s*(b|strong)\s*>", re.IGNORECASE), "{*"),
    (re.compile(r"<\s*/\s*(b|strong)\s*>", re.IGNORECASE), "*}"),
    (re.compile(r"<\s*(i|em)\s*>", re.IGNORECASE), "{/"),
    (re.compile(r"<\s*/\s*(i|em)\s*>", re.IGNORECASE), "/}"),
    (re.compile(r"<\s*u\s*>", re.IGNORECASE), "{_"),
    (re.compile(r"<\s*/\s*u\s*>", re.IGNORECASE), "_}"),
    (re.compile(r"<\s*(s|strike|del)\s*>", re.IGNORECASE), "{-"),
    (re.compile(r"<\s*/\s*(s|strike|del)\s*>", re.IGNORECASE), "-}"),
    (re.compile(r"<\s*sup\s*>", re.IGNORECASE), "{^"),
    (re.compile(r"<\s*/\s*sup\s*>", re.IGNORECASE), "^}"),
    (re.compile(r"<\s*sub\s*>", re.IGNORECASE), "{~"),
    (re.compile(r"<\s*/\s*sub\s*>", re.IGNORECASE), "~}"),
    (re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE), " "),
]
TAG = re.compile(r"<[^>]+>")


# Mojibake repair, ported from xd's xdfile/utils.py (clean_latin1_utf8_mojibake,
# clean_c1_controls) and the first steps of xdfile/puz2xd.py decode(), which is what every
# .puz file in the xd corpus went through; doc/character-encoding.md in
# https://github.com/century-arcade/xd explains each pass.
# Keep in lockstep with those: a change there is a change here.
_C1_RE = re.compile(r"[\x80-\x9f]")
_UTF8_TRAILER_RE = re.compile(r"â?\x80[\x80-\x9f]")
_ORPHAN_QUOTE_TRAILER_RE = re.compile(r'["\x93\x94“”][\x9c\x9d]')
_LATIN1_UTF8_RE = re.compile(r"[\xc2\xc3][\x80-\xbf]")
_CP1252_OVERRIDES = {"\x8e": "é"}  # cp1252's 'Ž' is wrong in the corpus (Mac Roman é)
_CP1252_SKIP_SINGLE = {"\x80", "\x98"}  # too ambiguous to auto-decide (€ / ˜ are usually wrong)


def clean_latin1_utf8_mojibake(s: str) -> str:
    """Re-decode UTF-8 byte pairs misread as latin-1: 'Ã©' -> 'é', 'Ãª' -> 'ê'."""

    def repl(m: re.Match) -> str:
        try:
            return m.group(0).encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return m.group(0)

    return _LATIN1_UTF8_RE.sub(repl, s)


def clean_c1_controls(s: str) -> str:
    """C1 controls (U+0080-U+009F) are never meant. Four passes: a UTF-8 trailer (optional
    'â' + U+0080 + C1) is rebuilt into the smart quote or dash it was; a U+009C/D right after
    a quote is a stray trailer, dropped; U+008E is é (Mac Roman); the rest is cp1252, except
    U+0080/U+0098 and the five bytes cp1252 leaves undefined, which survive for a human
    (Puzzle.check() rejects them)."""

    def utf8_repl(m: re.Match) -> str:
        bs = m.group(0).encode("latin-1")
        if not bs.startswith(b"\xe2"):
            bs = b"\xe2" + bs
        try:
            return bs.decode("utf-8")
        except UnicodeDecodeError:
            return m.group(0)

    s = _UTF8_TRAILER_RE.sub(utf8_repl, s)
    s = _ORPHAN_QUOTE_TRAILER_RE.sub(lambda m: m.group(0)[0], s)

    def repl(m: re.Match) -> str:
        ch = m.group(0)
        if ch in _CP1252_OVERRIDES:
            return _CP1252_OVERRIDES[ch]
        if ch in _CP1252_SKIP_SINGLE:
            return ch
        try:
            return ch.encode("latin-1").decode("cp1252")
        except UnicodeDecodeError:
            return ch

    return _C1_RE.sub(repl, s)


def repair(text: str) -> str:
    """puz2xd.decode()'s mojibake steps, in its order."""
    text = re.sub(r"Â([\x80-\x9f])", r"\1", text)  # UTF-8 C1 read as latin-1: 'Â' + trailer
    text = text.replace("Ã\x82", "")  # a known stray artifact, never real text
    text = clean_latin1_utf8_mojibake(text)
    return clean_c1_controls(text)


def plain(text: str) -> str:
    """Header/notes text: entities decoded, mojibake repaired, typography flattened,
    whitespace collapsed (house style; xdlint XD009, XD010, XD208)."""
    text = repair(html.unescape(text))
    text = unicodedata.normalize("NFC", text).translate(FLAT)
    return re.sub(r"\s+", " ", text).strip()


def clue_text(text: str, keep_markup: bool = True) -> str:
    """Clue text: HTML inline markup to xd markup, the rest as plain()."""
    for pattern, rep in MARKUP:
        text = pattern.sub(rep, text)
    text = TAG.sub("", text)  # any other tag is dropped, its text kept
    text = plain(text)
    # markup around nothing but space is the space ('"Big"<i> </i>top')
    text = re.sub(r"\{([/*_\-^~])(\s*)\1\}", lambda m: " " if m.group(2) else "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # tidy spaces that markup conversion can leave inside the braces
    text = re.sub(r"\{([/*_\-^~])\s+", r"{\1", text)
    text = re.sub(r"\s+([/*_\-^~])\}", r"\1}", text)
    return text


@dataclass
class Clue:
    direction: str  # "A" or "D"
    number: int
    text: str
    answer: str


@dataclass
class Puzzle:
    headers: dict[str, str] = field(default_factory=dict)
    grid: list[str] = field(default_factory=list)
    clues: list[Clue] = field(default_factory=list)
    notes: str = ""
    # notes on what the source had that xd can't carry, instead of dropping it silently
    tricky: list[str] = field(default_factory=list)
    # the tricky notes that mean the .xd is probably wrong and a person should look at it
    review: list[str] = field(default_factory=list)

    def needs_review(self, note: str) -> None:
        """A tricky note a person has to look at before the puzzle goes in."""
        self.tricky.append(note)
        self.review.append(note)

    def set(self, key: str, value: str) -> None:
        value = plain(value)
        if value:
            self.headers[key] = value

    @property
    def width(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    @property
    def height(self) -> int:
        return len(self.grid)

    def ordered_headers(self) -> list[tuple[str, str]]:
        def key(item):
            k = item[0].lower()
            return (HEADER_ORDER.index(k) if k in HEADER_ORDER else 1000, 0)

        return sorted(self.headers.items(), key=key)

    def to_xd(self) -> str:
        out = []
        for k, v in self.ordered_headers():
            out.append(f"{k}: {v}")
        out.append("")
        out.append("")
        out.extend(self.grid)
        out.append("")
        out.append("")
        prev = None
        for c in sorted(self.clues, key=lambda c: (0 if c.direction == "A" else 1, c.number)):
            if prev and prev != c.direction:
                out.append("")
            prev = c.direction
            out.append(f"{c.direction}{c.number}. {c.text or '[XXX]'} ~ {c.answer}")
        if self.notes.strip():
            out.append("")
            out.append("")
            out.append(self.notes.strip())
            return "\n".join(out) + "\n"
        # xd's own writer ends a file without notes with a blank line; so does the house style
        return "\n".join(out) + "\n\n"

    def check(self) -> list[str]:
        """Cheap structural checks before xdlint: returns problems."""
        problems = []
        if not self.grid:
            return ["no grid"]
        if len({len(r) for r in self.grid}) != 1:
            problems.append("grid rows differ in length")
        keys = {x.split("=", 1)[0] for x in self.headers.get("Rebus", "").split() if "=" in x}
        for r, row in enumerate(self.grid):
            bad = next((m for m in GRID_CHARS.finditer(row) if m.group() not in keys), None)
            if bad:
                problems.append(f"grid character {bad.group()!r} at row {r} col {bad.start()}")
                break
        if not self.clues:
            problems.append("no clues")
        for h in ("Title", "Date"):
            if h not in self.headers:
                problems.append(f"no {h} header")
        for where, text in [*self.headers.items(), *((f"{c.direction}{c.number}", c.text) for c in self.clues)]:
            m = _C1_RE.search(text)
            if m:  # a C1 control the repair couldn't decide: a human must (xdlint XD010 would reject it)
                problems.append(f"C1 control U+{ord(m.group()):04X} survives in {where}")
                break
        # no Author is a fact about the source, not a failure (many published puzzles have
        # none); a converter notes it as tricky instead
        return problems


def number_grid(grid: list[str]) -> dict[tuple[str, int], tuple[int, int]]:
    """Standard numbering: (direction, number) -> (row, col) of the slot's start."""
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out = {}
    n = 0

    def black(r, c):
        return r < 0 or c < 0 or r >= h or c >= w or grid[r][c] == BLOCK

    for r in range(h):
        for c in range(w):
            if black(r, c):
                continue
            across = black(r, c - 1) and not black(r, c + 1)
            down = black(r - 1, c) and not black(r + 1, c)
            if across or down:
                n += 1
                if across:
                    out[("A", n)] = (r, c)
                if down:
                    out[("D", n)] = (r, c)
    return out


def answer_at(grid: list[str], direction: str, r: int, c: int) -> str:
    """The grid letters of the slot starting at (r, c)."""
    letters = []
    dr, dc = (0, 1) if direction == "A" else (1, 0)
    while 0 <= r < len(grid) and 0 <= c < len(grid[0]) and grid[r][c] != BLOCK:
        letters.append(grid[r][c])
        r += dr
        c += dc
    return "".join(letters)
