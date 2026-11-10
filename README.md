# xdfetch

Downloads crossword puzzles and converts them to
[.xd](https://github.com/century-arcade/xdformat), a plain-text crossword format.

**Early days.** It fetches puzzles from the outlets it knows (see Outlets below) or from a
URL, converts puzzle files (see Formats), and can keep an archive of every file it fetches.

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

### Keeping an archive

    xdfetch run --store ./archive                   # yesterday's puzzles from every enabled outlet
    xdfetch run --store ./archive --start 2026-10-01 --id universal.daily usatoday.daily
    xdfetch plan --store ./archive --date today     # what run would fetch
    xdfetch status --store ./archive                # per outlet: last file, misses, errors
    xdfetch availability --store ./archive          # when each outlet's file is really up
    xdfetch verify ./archive/downloads/2026/*.zip   # check archives against their manifests

A store is a directory or `s3://bucket/prefix` (`pip install 'xdfetch[s3]'`); `--store`
can also come from `XDFETCH_STORE`. It holds `ledger.tsv`, one row per fetch, so a run
fetches only what's due: new dates, recent misses, and the re-fetches an outlet's `refetch`
asks for. Each run's files go, as served, into a zip under `downloads/<year>/` with a
`MANIFEST.tsv` (URL, sha256, fetch time) and a `NOTES.md`; a changed re-fetch is kept beside
the first copy. `--registry FILE` (repeatable) lays your own outlet rows over xdfetch's on
any command that reads them.

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

Other packages can add formats; see "Adding to xdfetch from another package" below.

## Outlets

The series xdfetch knows how to fetch are rows of
[`xdfetch/outlets.tsv`](xdfetch/outlets.tsv), each with an `id` of the form
`publisher.series`: `nytimes.daily`, `nytimes.mini`, `nytimes.midi`, `newyorker.daily`,
`newyorker.mini`, `universal.daily`, `universal.sunday`, `usatoday.daily`,
`washingtonpost.sunday`, `arkadium.mini`, `arkadium.two-minute-mini`,
`brendanemmettquigley.blog`, `dailyprincetonian.daily`, `dailyprincetonian.mini`. Each row
names the adapter that fetches it, the adapter's parameters, which days it runs, its
homepage and notes on its files. The column meanings are in `xdfetch/registry.py`;
`xdfetch list` prints them all.

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
