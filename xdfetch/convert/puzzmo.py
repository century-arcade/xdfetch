"""Puzzmo's GraphQL answer for a puzzle, as the `puzzmo` adapter saves it. From a team queue
(the answer to `puzzle(id:)`), and for Puzzmo's own series the play screen's answer,
{"data": {"startOrFindGameplay": {"gamePlayed": {"puzzle": {...}}}}}, holding the same record:

    {"data": {"puzzle": {"id": "...:puzzle", "name": "Bird Words", "puzzle": "## Metadata\\n..."}}}

The `puzzle` field is xd text in Puzzmo's dialect: ## Metadata (title, author, copyright,
rebus with ❶ ❷ keys, sometimes a stray style line), ## Grid ('#' or '.' blocks, rebus
squares as their key character), ## Clues (A1. text ~ ANSWER, then metadata lines such as
`A1 ^refs: D4` and, on Puzzmo's own crossword, `A1 ^hint: ...`), an optional ## Line Breaks
(where the player may wrap a clue; ignored) and an optional ## Design
(a <style> naming letters, then a mask: `background: circle` or a gray
`background-light: #CCCCCC` for shading).

Conventions: Title is the puzzle's name, and a name that is only a date ("Tue, Nov 3,
2026") is written out ("Tuesday, November 3, 2026"); Author is the byline Puzzmo shows;
Copyright is "© <year> <author>" with the year from the text's copyright line; Puzzmo's
backticks around titles in clues become double quotes; ❶ and ❷ become digit keys; circles
are lowercase letters with Special: circle and a gray mask is Special: shaded.

The dialect's other features: a `splitcharacter:` marking word breaks in answers
(`TURN|IT|UP`); a rebus answer written keyed and then expanded (`O0BER # O[CTO]BER`);
links and images in clues (`{@ text | url @}`, `{! url | alt | size !}`), written in xd's
form; and Schrödinger squares, `*` in the grid, that take either of two letters, the
clue's answer giving one and an `^alt:` line under it the other (`^alt1:` and on for more).
A Schrödinger square becomes a rebus square whose value lists its letters (`1=E|K`), and the
clue is written once per reading. Clue metadata lines other than ^refs: and ^alt: (^hint:)
are not carried and are listed as tricky.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re

from ..xd import BLOCK, REBUS_KEYS, Clue, Puzzle, answer_at, number_grid, plain
from . import Context, ConvertError
from .conde import STYLE, sections


def sniff(data: bytes) -> bool:
    head = data[:200].lstrip()
    return (
        head.startswith(b'{"data"') and (b'"puzzle"' in head or b'"startOrFindGameplay"' in head) and b"## Grid" in data
    )


def record(body: dict) -> dict:
    """The puzzle record in either form of answer."""
    data = body["data"]
    if "startOrFindGameplay" in data:
        return data["startOrFindGameplay"]["gamePlayed"]["puzzle"]
    return data["puzzle"]


def convert(data: bytes, ctx: Context) -> Puzzle:
    try:
        rec = record(json.loads(data.decode("utf-8")))
        text = rec["puzzle"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise ConvertError(f"not a Puzzmo puzzle answer: {e}") from e
    sec = sections(text)
    if "Grid" not in sec or "Clues" not in sec:
        raise ConvertError("puzzle text has no Grid or Clues section")
    meta: dict[str, str] = {}
    for line in sec.get("Metadata", "").splitlines():
        m = re.match(r"^(\w+):\s*(.*?)\s*$", line)
        if m:
            meta[m.group(1).lower()] = m.group(2)
    p = Puzzle()

    # marks from the Design section: circles, or a gray mask for shading
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
                (circled if styles.get(ch, "shaded") == "circle" else shaded).add((r, c))
    if circled and shaded:
        p.tricky.append("both circled and shaded squares; the shading is kept as circles")
    marked = circled | shaded
    if circled:
        p.set("Special", "circle")
    elif shaded:
        p.set("Special", "shaded")

    split = meta.get("splitcharacter", "").strip()
    fills = dict(x.split("=", 1) for x in meta.get("rebus", "").split() if "=" in x)
    rows = [row.strip() for row in sec["Grid"].strip().splitlines()]
    if not rows or len({len(x) for x in rows}) != 1:
        raise ConvertError("grid rows differ in length")

    # the clue lines first: a Schrödinger square ('*' in the grid) takes its letters from
    # the answers that cross it, the clue's own and those on its ^alt: lines
    entries: list[tuple[str, int, str, str]] = []  # direction, number, text, answer
    alts: dict[tuple[str, int], list[str]] = {}
    extras: dict[str, int] = {}  # other clue metadata lines (A1 ^hint: ...) by key, refs aside
    for line in sec["Clues"].splitlines():
        line = line.strip()
        meta_line = CLUE_META.match(line)
        if meta_line:
            key = meta_line.group(2).lower()
            if re.fullmatch(r"alt\d*", key):  # ^alt:, ^alt1:, ... one more reading each
                alts.setdefault((meta_line.group(1)[0], int(meta_line.group(1)[1:])), []).append(
                    answer_of(line[meta_line.end() :], split)
                )
            elif key != "refs":
                extras[key] = extras.get(key, 0) + 1
            continue
        if not line:
            continue
        m = CLUE.match(line)
        if not m:
            p.needs_review(f"clue line not understood: {line[:60]}")
            continue
        text_ = plain(xd_markup(html.unescape(m.group(3)))).replace("`", '"')  # Puzzmo's backticks around titles
        entries.append((m.group(1), int(m.group(2)), text_, answer_of(m.group(4), split)))
    schrodinger = schrodinger_letters(rows, entries, alts)

    keys: dict[tuple[str, bool], str] = {}
    plain_keys = list(REBUS_KEYS)
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    grid = []
    for r, row in enumerate(rows):
        out = ""
        for c, ch in enumerate(row):
            if ch in ".#":
                out += BLOCK
            elif ch == "*" and "*" not in fills:
                value = "|".join(schrodinger.get((r, c), []))
                if len(schrodinger.get((r, c), [])) < 2:
                    p.needs_review(f"Schrödinger square at row {r + 1}, column {c + 1} has {value or 'no'} reading")
                    value = value or "?"
                k = (value, (r, c) in marked)
                if k not in keys:
                    try:
                        keys[k] = next(letters) if k[1] else plain_keys.pop(0)
                    except (StopIteration, IndexError):
                        raise ConvertError("more rebus values than keys") from None
                out += keys[k]
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
    p.grid = grid
    if keys:
        p.set("Rebus", " ".join(f"{k}={v[0]}" for v, k in keys.items()))

    numbering = number_grid(grid)
    values = {k: v[0] for v, k in keys.items()}  # grid key -> rebus value ("E|K" for a Schrödinger square)
    for direction, number, text_, answer in entries:
        # a tilde with spaces round it would start the answer in .xd; the clue's own is written
        # as literal markup ("Symbol {\~\} for about")
        text_ = re.sub(r"(?<= )~(?= )", lambda _: "{\\~\\}", text_)
        pos = numbering.get((direction, number))
        if pos is None:
            p.needs_review(f"{direction}{number}: clue has no slot in the grid")
            p.clues.append(Clue(direction, number, text_, answer.upper()))
            continue
        cells = [values.get(ch, ch.upper()).upper().split("|") for ch in answer_at(grid, direction, *pos)]
        expanded = "".join(c[0] for c in cells)
        readings = [answer.upper() or expanded]
        for alt in alts.pop((direction, number), []):
            if fits(alt.upper(), cells):
                readings.append(alt.upper())
            else:
                p.needs_review(f"{direction}{number}: ^alt: {alt} doesn't fit the slot")
        for reading in readings:
            if not fits(reading, cells):
                p.needs_review(f"{direction}{number}: clue answer {reading} differs from grid {expanded}")
            p.clues.append(Clue(direction, number, text_, reading))
    for (direction, number), rest in alts.items():
        p.needs_review(f"{direction}{number}: ^alt: {' '.join(rest)} for a clue that isn't there")
    if not p.clues:
        raise ConvertError("no clues")
    for key, n in sorted(extras.items()):
        p.tricky.append(f"{n} clues have a ^{key}: line, not carried")

    author = byline(rec, meta)
    p.set("Title", title_for(rec.get("name") or meta.get("title", ""), ctx, p))
    p.set("Author", author)
    editor = people(rec.get("editors")) or editor_of(meta.get("editor", ""))
    if editor:
        p.set("Editor", editor)
    year = re.search(r"(19|20)\d\d", meta.get("copyright", ""))
    if year:
        p.set("Copyright", f"© {year.group(0)} {author}".strip())
    elif meta.get("copyright"):
        p.set("Copyright", meta["copyright"])
    if ctx.date:
        p.set("Date", ctx.date.isoformat())
    return p


# a clue line, split at its last " ~ ": a clue may itself contain a tilde ("Obey a ¬, ~, or ! operator")
CLUE = re.compile(r"^([AD])(\d+)\.\s*(.*?)\s*~\s*([^~]*)$")
# a clue's metadata line, A1 ^refs: D4 or A1 ^hint: ...; Puzzmo's daily crossword gives each clue a hint,
# and a clue whose slot crosses a Schrödinger square has its other answer on an ^alt: line,
# sometimes under the wrong clue
CLUE_META = re.compile(r"^([AD]\d+)\s+\^(\w+):")
LINK = re.compile(r"\{@(.*?)@\}")  # Puzzmo: {@ text | url @}
IMAGE = re.compile(r"\{!(.*?)!\}")  # Puzzmo: {! url | alt | size !}


def answer_of(raw: str, split: str) -> str:
    """An answer as Puzzmo writes it, as letters. A rebus answer comes keyed and then expanded
    (`O0BER # O[CTO]BER`); the expanded half is taken, brackets dropped. The split character
    marks word breaks (`TURN|IT|UP`)."""
    s = raw.strip()
    if " # " in s:
        s = s.split(" # ", 1)[1]
    s = s.replace("[", "").replace("]", "")
    if split:
        s = s.replace(split, "")
    return s.strip()


def _attr(value: str) -> str:
    """An xd markup attribute value, quoted when it holds a ';'."""
    return f"'{value}'" if ";" in value else value


def xd_markup(text: str) -> str:
    """Puzzmo's link and image markup in xd's form (doc/xd-format-v4.md, xdown Formatting):
    {@ text | url @} -> {@text | href: url@}, {! url | alt | size !} -> {!alt | src: url; width: size!}."""

    def link(m: re.Match) -> str:
        content, sep, url = m.group(1).rpartition("|")
        if not sep:
            return m.group(0)
        return f"{{@{content.strip()} | href: {_attr(url.strip())}@}}"

    def image(m: re.Match) -> str:
        parts = [x.strip() for x in m.group(1).split("|")]
        if len(parts) < 2:
            return m.group(0)
        attrs = f"src: {_attr(parts[0])}" + (f"; width: {_attr(parts[2])}" if len(parts) > 2 and parts[2] else "")
        return f"{{!{parts[1]} | {attrs}!}}"

    return IMAGE.sub(image, LINK.sub(link, text))


def schrodinger_letters(
    rows: list[str], entries: list[tuple[str, int, str, str]], alts: dict[tuple[str, int], list[str]]
) -> dict[tuple[int, int], list[str]]:
    """For each '*' square, the letters the answers crossing it put there, in the order met:
    each clue's answer, then its ^alt: answers. An answer that isn't the slot's length (an ^alt:
    on the wrong clue) gives nothing."""
    plan = ["".join(BLOCK if ch in ".#" else ch for ch in row) for row in rows]
    numbering = number_grid(plan)
    out: dict[tuple[int, int], list[str]] = {}
    for direction, number, _, answer in entries:
        pos = numbering.get((direction, number))
        if pos is None:
            continue
        dr, dc = (0, 1) if direction == "A" else (1, 0)
        cells = [(pos[0] + i * dr, pos[1] + i * dc) for i in range(len(answer_at(plan, direction, *pos)))]
        if not any(plan[r][c] == "*" for r, c in cells):
            continue
        for reading in [answer, *alts.get((direction, number), [])]:
            if len(reading) != len(cells):
                continue
            for (r, c), letter in zip(cells, reading.upper(), strict=True):
                if plan[r][c] == "*" and letter not in out.setdefault((r, c), []):
                    out[(r, c)].append(letter)
    return out


def fits(reading: str, cells: list[list[str]]) -> bool:
    """Whether a reading fills the slot, each square taking one of its values (a rebus value is
    several letters; a Schrödinger square has more than one value)."""
    if not cells:
        return not reading
    return any(reading.startswith(v) and fits(reading[len(v) :], cells[1:]) for v in cells[0] if v)


def editor_of(line: str) -> str:
    """The xd text's editor: line when it names someone. It is often a leftover instead: "Not
    set", or a note on the submission it came from (`January 30, 2023 - "Title" - A. Setter,`,
    `A. Setter - 3/5`, on Puzzmo's daily 2023-2025); those give no Editor rather than a wrong one."""
    line = plain(line)
    if not line or line.lower() == "not set" or re.search(r'\d|"| - ', line):
        return ""
    return line


def people(users: list[dict] | None) -> str:
    """Names as Puzzmo's site shows them: each user's publishingName, else name (the share card
    shows name), usernames and all, joined "A and B", "A, B and C"."""
    names = [plain(u.get("publishingName") or u.get("name") or "") for u in users or []]
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def byline(rec: dict, meta: dict[str, str]) -> str:
    """The byline as Puzzmo shows it, from the answer's authors. The xd text's own author: line
    is often a leftover from editing (a staff member's initials) and is used only when the answer
    has no authors, as a team queue's answer never has."""
    return people(rec.get("authors")) or re.sub(r"\s+&\s+", " and ", plain(meta.get("author", "")))


DATE_NAME = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}, \d{4}$")


def title_for(name: str, ctx: Context, p: Puzzle) -> str:
    """The title: the puzzle's name, except that a name that is only a date (the Globe's mini
    is named "Tue, Nov 3, 2026") is written out, "Tuesday, November 3, 2026"."""
    name = name.strip()
    if not DATE_NAME.match(name):
        return name
    try:
        day = dt.datetime.strptime(name, "%a, %b %d, %Y").date()
    except ValueError:
        return name
    if ctx.date and day != ctx.date:
        p.tricky.append(f"named {name!r}, file dated {ctx.date}")
    return f"{day:%A}, {day:%B} {day.day}, {day:%Y}"
