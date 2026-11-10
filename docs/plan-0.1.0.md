# Plan: xdfetch 0.1.0

Drafted 2026-11-09. The architecture is in [DESIGN.md](../DESIGN.md); this is what goes
into the first real release and in what order.

## What 0.1.0 is

**Someone who uses xword-dl today can switch to xdfetch for the sites they care about and
get a correct `.xd`.** That means:

- `pip install xdfetch` (or `uv tool install xdfetch`), then `xdfetch get <site>` writes
  today's puzzle as `<site><date>.xd` in the current directory.
- `xdfetch get <url>` works for a link to a `.puz`, `.ipuz` or `.jpz` file, and for any
  page a plugin recognizes.
- `xdfetch convert <file>` turns a local `.puz`, `.ipuz` or `.jpz` into `.xd`.
- Downloaders are plugins. A third party can write one in a single file and a
  `pyproject.toml`, and `xdfetch list` shows it once installed.
- Nothing in it refers to gxd: no publication tables, receipts, archives, ledgers or
  house style.

## Not in 0.1.0

- **An archive mode** (a store of raw files, a ledger, resuming runs, re-fetching for
  corrections). That's a scheduled-job feature, not a downloader's; if it comes, it's a
  plugin or a later command.
- **Output other than `.xd`.** `.puz` and `.ipuz` for solving apps are the obvious next
  step, but they're a different promise (writing formats, not reading them).
- **Date ranges in one command.** `get` takes one date; a shell loop covers ranges for now.
- **A GUI, a server, or a scheduler.**

## Decisions this plan makes (say if you disagree)

1. **Depend on xdformat for the model and the writer.** `xdformat.xdfile` is the puzzle
   model and `to_unicode()` the serializer, and its `parse_puz` / `parse_ipuz` are the
   `.puz` and `.ipuz` converters (the `[convert]` extra, which brings in puzpy). One
   definition of .xd across century-arcade's tools, less code here. Where xdformat falls
   short (circles, shading, lossy-conversion reports), fix it upstream in xdformat and
   pin the version that has the fix.
2. **Python 3.11+.** For `tomllib` (the config file) without a dependency. 3.10 reaches
   end of life in October 2026.
3. **Dependencies:** `xdformat[convert]`, `requests`. Nothing else in the core.
4. **No registry file.** Sources are declared in Python (a class, or one
   `UrlTemplateSource(...)` line), not in a TSV, so a plugin is just a package.
5. **Errors are exit codes:** 0 written, 1 failed, 2 bad usage, 3 no puzzle for that date
   (not published that day, or not up yet). Scripts can tell "try later" from "broken".
6. **Plugin API is versioned.** `xdfetch.source.API_VERSION = 1`; a plugin built for a
   different major version is skipped with a warning instead of crashing `list`.

## Decision that's still yours: where the downloaders live

The API makes this a packaging question only. A source is the same code wherever it
lives, so it can move later without changes.

| Option | Public sources | Private sources | Trade-off |
|---|---|---|---|
| **A. In this repo** | `xdfetch/sources/`, shipped in the wheel | a separate private package (say `xdfetch-private` on GitLab) installed alongside | One `pip install` gets a useful tool. Site breakages mean xdfetch releases. |
| **B. A second public repo** | `century-arcade/xdfetch-sources`, installed as an extra (`pip install xdfetch[sources]`) | the same private package | The core is stable and sources can release weekly. Two repos to keep in step. |
| **C. A folder now, a repo later** | start as A | the same | Defers the choice until the release rhythm is clear. |

**Recommendation: C.** Ship the public sources in `xdfetch/sources/` for 0.1.0, registered
through entry points like any plugin. If fixing broken sites starts forcing too many
core releases, move the folder to its own repo; the API doesn't change.

**Private sources** go in a separate private package, not a git-ignored folder in this
repo. A folder like that is easy to commit by accident, and it can't be installed on
another machine. The private package declares the same entry points, so installing it
beside xdfetch is all it takes.

**Which sites go where** is up to you. Two things to weigh for each site: does xword-dl,
public and MIT, already download it (then publishing adds little exposure), and does it
reach paid puzzles without the user's own login (then keep it private). The public
sources need to be written fresh for this repo either way.

## Milestones

Each one ends with tests passing and something you can try.

**M1. Convert local files** (core, no network)
- `Puzzle` model over `xdformat.xdfile`, with a `lost` list for what didn't fit.
- Formats: `.xd` (passthrough, validated), `.puz` and `.ipuz` (via xdformat), `.jpz`
  (new: unzipped or zipped XML, parsed safely). Sniffing picks the format.
- `xdfetch convert FILE [-o TEMPLATE]`; filename templates (`naming.py`).
- Synthetic fixtures for each format: rebus, circles, a missing-answer puzzle, non-ASCII
  clues.
- *Try it:* convert a `.puz` you have.

**M2. Fetch** (core)
- `http.py`: User-Agent, rate limit per host, retry with backoff on 429 and 5xx, timeouts.
- `source.py` (`Source`, `Request`, `Download`, `UrlTemplateSource`, `API_VERSION`) and
  `plugins.py` (entry points, conflicts, broken plugins reported).
- `xdfetch get ID [--date D | --latest] [-o T] [--raw]`, `xdfetch get URL`, `xdfetch list`.
- Calendar: a source's `days` and `tz` decide "today" and whether a date has a puzzle.
- *Try it:* a toy plugin in `tests/` that serves a fixture from a local HTTP server.

**M3. Settings and credentials**
- `config.py`: TOML file in the platform's config folder, `XDFETCH_<ID>_<SETTING>`
  overrides, `xdfetch config` to show the path and what's set (secrets masked).
- A source that needs a missing setting fails with exit code 1 and names it.

**M4. Sources** (needs the decision above)
- The public sources for 0.1.0, written fresh. Enough to replace xword-dl for its most
  used sites. Suggested floor: one plain-URL source, one embed-host family (one
  converter covering several newspapers), and one subscription site that uses the
  user's own cookie.
- Each source: a synthetic fixture test, and a live test behind `--live`.
- A short `docs/writing-a-source.md`, tested by building the example in it.
- `xdfetch.testing` helpers for plugin authors.

**M5. Release**
- README: install, `get`, `convert`, settings, plugins, and a table mapping xword-dl
  commands to xdfetch ones.
- CI: tests on 3.11 and 3.14 on Linux, plus one Windows job (paths and config folder).
- Bump to 0.1.0, tag, and let the release workflow publish it.

## Open questions for later releases

- Output to `.puz` / `.ipuz` (0.2?).
- Date ranges and a `--since` for catching up.
- Whether an archive mode belongs here or in a separate tool.
- A shared index of third-party plugins (a list in the README is enough to start).
