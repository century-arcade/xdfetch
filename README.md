# xdfetch

Downloads crossword puzzles and converts them to
[.xd](https://github.com/century-arcade/xdformat), a plain-text crossword format.

**Early days.** It fetches puzzles from the outlets it knows (see Outlets below) or from a
URL, converts puzzle files (see Formats), and can keep an archive of every file it fetches
(see Keeping an archive).

## Use

    pip install xdfetch            # or: uv tool install xdfetch

    xdfetch list                                    # the outlets: id, days, homepage
    xdfetch get nytimes.mini                        # the latest -> nytimes.mini-2026-11-08.xd
    xdfetch get universal.daily --date 2026-11-02   # -> universal.daily-2026-11-02.xd
    xdfetch get https://example.com/puzzle.puz      # -> puzzle.xd
    xdfetch get https://example.com/puzzle.puz --format both   # also keep puzzle.puz as served
    xdfetch get https://example.com/puzzle.puz --format raw    # only the file as served
    xdfetch convert *.puz *.ipuz                    # -> one .xd each
    xdfetch convert old.puz -o -                    # to stdout

Output goes in the current directory unless `-o` names a file or a directory. An
existing file is left alone unless you add `--force`. `get` exits with 3 when the outlet
has no puzzle for the date. An outlet whose row names an `auth` variable reads its secret
from that environment variable.

The format is picked by looking at the file, not its extension. Text is written as UTF-8,
with curly quotes and ellipses made plain ASCII and HTML in clues turned into xd's markup.

## Keeping an archive

`get` fetches one puzzle. `run` is for fetching many, again and again: run it on a
schedule and it keeps a growing archive of every outlet's files, exactly as served, and a
ledger of what it has fetched so the next run doesn't repeat it.

    xdfetch run --store ./archive                   # yesterday's puzzles from every enabled outlet
    xdfetch run --store ./archive --start 2026-10-01 --id universal.daily usatoday.daily
    xdfetch plan --store ./archive --date today     # what run would fetch
    xdfetch status --store ./archive                # per outlet: last file, misses, errors
    xdfetch availability --store ./archive          # when each outlet's file is really up
    xdfetch verify ./archive/downloads/2026/*.zip   # check archives against their manifests

### The store

`--store` names a directory or `s3://bucket/prefix` (`pip install 'xdfetch[s3]'`); it can
also come from the `XDFETCH_STORE` environment variable. A run writes three things there:

    ledger.tsv                                   one row per fetch, added to by every run
    downloads/2026/20261109-070000-www.zip       the files this run fetched (none fetched, no zip)
    reports/2026/20261109-070000-report.md       this run's report

The archive holds files as the outlet served them, not `.xd`. Unzip one and
`xdfetch convert` its files when you want `.xd`.

### Which outlets

A run fetches every enabled outlet that `xdfetch list` shows, or only the ones named
after `--id`. `--registry FILE` (repeatable, on every command but `convert` and `verify`)
lays a file of your own rows over xdfetch's. It adds outlets, or replaces a built-in row
that has the same `id`; it does not narrow the run to the outlets in the file. A
tab-separated file with a header line, with only the columns you need (the columns are
listed under Outlets below):

    id	adapter	params	days	homepage
    example.weekly	url	url=https://example.com/puzzles/%Y-%m-%d.puz	sat	https://example.com/

To leave a built-in outlet out of every run, replace its row with a disabled one:

    id	adapter	enabled
    usatoday.daily	url	no

### Which dates

| Options | Dates |
|---|---|
| none | yesterday |
| `--date D` | that one date |
| `--start D` | from D to today |
| `--start D --end E` | from D to E |

A date is `YYYY-MM-DD`, `today` or `yesterday` (UTC). Within the range, an outlet is asked
only for the days it publishes (`days`, `since`) and only once the day's file should be up
(`available_after`).

A run looks only at the dates in its range. It does not work out what it missed since the
last run, so a job that skips a night, or that should retry misses and do re-fetches,
needs a range that reaches back. For example, with GNU `date`:

    xdfetch run --store ./archive --start "$(date -d '8 days ago' +%F)"

Dates the ledger already has are skipped, so a wide range costs nothing extra.

### What is fetched

For each outlet and date in the range, the ledger decides (`plan` prints the reason):

| Reason | When |
|---|---|
| `new` | the ledger has no row for it |
| `retry` | the last try was `missing` or `error`, and the date is at most 3 days old |
| `refetch` | the outlet's `refetch` column names days after publication to look again (`1,2,7`), and one is due |
| `forced` | `--force`: fetch it whatever the ledger says |

`--no-refetch` turns re-fetches off. Each try ends as one of:

| Status | Meaning |
|---|---|
| `ok` | first copy of the file, archived |
| `same` | a re-fetch got identical bytes; nothing new is kept |
| `changed` | a re-fetch got different bytes; the new file is kept in this run's zip as `name.v2.ext`, and the first copy stays where it was |
| `missing` | the outlet has nothing for that date (a 404 or an empty page) |
| `error` | anything else; an outlet that errors 3 times in a row is skipped for the rest of the run |

An archive is never rewritten once stored. Each zip holds the fetched files under their
outlet's id, a `MANIFEST.tsv` (file name, sha256, size, URL and fetch time of each) and a
`NOTES.md` saying where each outlet's files came from.

Other options of `run`: `--dry-run` plans without fetching, `--interval SECONDS` sets the
pause between requests to one host (default 2), and `--summary FILE` writes the report to
a second place, such as a CI job summary. The report is also printed. `run` exits with 1
if any fetch ended in `error`; a `missing` is not an error.

### Checking on it

- `status` prints a line per outlet: the date of its last file, how many files, misses
  and errors the ledger holds, and how many of its most recent dates in a row ended in a
  miss or an error.
- `availability` compares each outlet's `available_after` with what the ledger saw (when
  a file was first found, when it was still missing, and the server's Last-Modified), and
  says whether the number should be raised or could be lower.
- `verify ZIP...` checks each zip against its own manifest: every listed file is there
  with the same sha256 and size, and no file under an outlet's folder is unlisted. It
  reads only the zips, and exits with 1 if any has a problem.

## Formats

| Format | Served by, for example |
|---|---|
| Across Lite `.puz` | many outlets and archives |
| ipuz (`.ipuz`, also as JSONP) | Crossword Compiler and other tools |
| Crossword Compiler XML (`.jpz`) | Arkadium's feeds, many others |
| uclick XML | Andrews McMeel (Universal, USA Today) |
| NYT puzzle JSON (v6) | The New York Times |
| Condé Nast puzzle record | The New Yorker |
| Washington Post games JSON | The Washington Post |
| Daily Princetonian crossword API | The Daily Princetonian |
| Crossword Compiler as JSON (xml2js) | King Features, on GameDistribution's feeds |
| PZLR crossword level | The Wall Street Journal |
| Puzzmo's xd dialect, in its GraphQL answers | Puzzmo, the Boston Globe |

Other packages can add formats; see "Adding to xdfetch from another package" below.

## Outlets

The series xdfetch knows how to fetch are rows of
[`xdfetch/outlets.tsv`](xdfetch/outlets.tsv), each with an `id` of the form
`publisher.series`: `nytimes.daily`, `nytimes.mini`, `nytimes.midi`, `newyorker.daily`,
`newyorker.mini`, `universal.daily`, `universal.sunday`, `usatoday.daily`,
`washingtonpost.sunday`, `arkadium.mini`, `arkadium.two-minute-mini`,
`brendanemmettquigley.blog`, `dailyprincetonian.daily`, `dailyprincetonian.mini`,
`kingfeatures.thomas-joseph`, `kingfeatures.eugene-sheffer`, `kingfeatures.premier-sunday`,
`wsj.daily`, `bostonglobe.sunday`, `bostonglobe.mini`, `puzzmo.daily`, `puzzmo.mini`,
`puzzmo.big`. `xdfetch list` prints them all.

A row's columns, of which only `id` and `adapter` are required:

| Column | Meaning | Blank means |
|---|---|---|
| `id` | the series' id | |
| `adapter` | which adapter fetches it: `url`, `page`, `nyt`, `conde`, `princetonian`, `gamedist`, `puzzlr`, `puzzmo`, or one a package adds | |
| `params` | the adapter's parameters, as `key=value` pairs separated by spaces (quote a value that holds spaces) | none |
| `days` | the days a puzzle runs: `daily`, `mon-sat`, `sun`, `mon,thu` | daily |
| `since` | the first date to expect a puzzle, `YYYY-MM-DD` | any date |
| `tz` | the outlet's timezone, an IANA name | `America/New_York` |
| `available_after` | hours after midnight in `tz` before the day's file is reliably up; negative for the evening before | 0 |
| `refetch` | days after publication to fetch again and compare, such as `1,2,7` | never |
| `homepage` | the outlet's own page for the series | |
| `auth` | the environment variable holding the secret the adapter needs | no secret |
| `enabled` | `yes` or `no` | yes |
| `notes` | what the file is, how it's named, quirks of the series | |

Two adapters need no code for a new outlet. `url` fetches a file at a predictable address:
its `url` param is the address with strftime fields for the date (`%Y-%m-%d`), and an
optional `filename` param names the file to keep it under. `page` fetches a dated page
(`page`, also with strftime fields) and then every file it links whose address matches
the `link` regex.

Three more serve platforms that carry several outlets' puzzles:

- `gamedist`, GameDistribution's crossword feeds (King Features' puzzles): `feed` is the
  feed's slug. The rows also set how the puzzle is written: `author` (a fixed byline),
  `dash` and `endash` (what to write for an em or en dash in a clue) and `quotes=repair`
  (a space after a clue's opening quote mark removed, unbalanced quote marks noted).
- `puzzlr`, PZLR: `tenant` is the publisher's slug, and `offset` the days added to the
  date asked for to get the date PZLR files the puzzle under. `copyright` is written when
  the puzzle carries none.
- `puzzmo`, Puzzmo: `team` and `queue` name a publisher's queue, or `finder` names one of
  Puzzmo's own series (`crossword`, `crossword/mini`, `crossword/big`).

Adapters return each file as the outlet served it; converting is a separate step.

## Adding to xdfetch from another package

Another package can add adapters, outlet rows and formats without changing xdfetch,
through three entry-point groups in its `pyproject.toml`:

    [project]
    dependencies = ["xdfetch"]

    # an adapter: the entry point's name is the adapter's name, its object an
    # xdfetch.adapters.Adapter subclass
    [project.entry-points."xdfetch.adapters"]
    mysite = "mypackage.adapters:MySiteAdapter"

    # outlet rows: a path to a TSV with the same columns as outlets.tsv (a str,
    # os.PathLike or importlib.resources Traversable), or a function returning one
    [project.entry-points."xdfetch.registries"]
    mypackage = "mypackage:outlets_tsv"

    # a converter: a (name, sniff, convert) tuple, or an object such as a module
    # with sniff and convert functions
    [project.entry-points."xdfetch.converters"]
    myformat = "mypackage.myformat"

Converter plugins are sniffed before the built-in converters and may hand data back by
returning None; the docstring of `xdfetch.convert` gives the full shape.

`xdfetch.registry.effective()` reads xdfetch's own rows, then each package's TSV (in
order of entry-point name), then any files passed to it. A later row with the same
`id` replaces the earlier one whole, so a package can change a built-in outlet's row as
well as add its own. A program that keeps a registry of its own can load just its files
with `xdfetch.registry.from_files(paths)`; ids outside xdfetch's own rows can be any
string and are used as given. `xdfetch.adapters.get(name)` finds built-in adapters first,
then the packages'; a missing or broken one is an error that names it.

## Development

    uv sync
    uv run pytest
    uv run ruff check && uv run ruff format --check
    uv run ty check

Tests use tiny puzzles made up for the purpose (`tests/conftest.py`, `tests/synthetic.py`).
Please don't add real, published puzzles to the repo.

## License

MIT. See [LICENSE](LICENSE).
