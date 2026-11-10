# xdfetch design

Started 2026-11-09. This is a new implementation. The design comes from what we learned
running a private daily downloader for the xd corpus, but no code is carried over, so
everything here is written fresh and can be published.

## Goals

- **Something anyone can use for one puzzle.** `xdfetch get <outlet>` fetches, converts and
  writes a `.xd` in the current directory. No setup, no state.
- **Something an archivist can run every day.** `xdfetch run` keeps every file as served in
  a store (a directory or an `s3://` prefix), with a ledger of what was fetched, so a run
  that was killed resumes where it stopped and a later run can look again for corrections.
- **Full fidelity.** Rebus squares, circles, shading and clue markup make it into the
  `.xd`. What .xd can't hold is listed, not silently dropped.
- **Room for outlets that aren't in this repo.** Other packages can add adapters,
  converters and outlet rows through entry points, without forking.

## Pieces

| Module | Job |
|---|---|
| `http.py` | One session per host, the tool's own User-Agent, a rate limit, backoff. |
| `registry.py` + `outlets.tsv` | One row per outlet: adapter, params, publication days, time zone, when the file goes up, when to look again for corrections, homepage. |
| `adapters/` | One per *transport* (a plain URL, Amuse Labs, Puzzmo, ...): for a date, where the file is, then fetch it as served. |
| `convert/` | One per *format* (uclick XML, Amuse JSON, ipuz, .puz, ...), chosen by sniffing the bytes, never by file extension. Each builds a `Puzzle`. |
| `xd.py` | `Puzzle` to `.xd` text. |
| `store.py`, `ledger.py`, `fetch.py` | The archivist's mode: plan (expected minus already fetched), run, record. |
| `cli.py` | `list`, `get`, `run`, `plan`, `status`, `convert`. |

## Extension points

Other packages add to xdfetch by declaring entry points:

```toml
[project.entry-points."xdfetch.adapters"]
myhost = "mypkg.adapters:MyHostAdapter"

[project.entry-points."xdfetch.converters"]
myformat = "mypkg.convert:MY_FORMAT"     # sniff + convert

[project.entry-points."xdfetch.registries"]
mine = "mypkg:OUTLETS_TSV"               # extra outlet rows, and overrides of built-in ones
```

A later registry row with the same id replaces an earlier one whole.

## Outlet ids

Outlet ids follow the xd corpus's publication ids (`nyt`, `lat`, `wsj`, `up`, ...), so a
fetched puzzle's filename is the name the corpus would give it.

## Tests

Converter tests use small fixtures written for the test (a few squares and clues), not
real puzzles: published puzzles are copyrighted, and this repo is public. Live checks
against outlets are opt-in and never run in CI.

## Etiquette

- The User-Agent names the tool and its repo, nothing else.
- One request at a time per host, with a delay, and backoff on errors.
- Outlets that need a subscription use the user's own credentials, from the environment.
  The tool never gets around a paywall.

## Open questions

- Use xdformat's parser and writer for `.xd`, or a small writer of our own? xdformat
  would keep one definition of the format; a writer of our own keeps the dependency list
  short.
- Typography: write the outlet's own characters, or the corpus's house style (curly quotes
  flattened and so on)? Probably the corpus's style by default, with a switch.
- Other output formats (`.ipuz`, `.puz` for solving apps): later, if people ask.
- Which outlets start here and which are added by other packages.
