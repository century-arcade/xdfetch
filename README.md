# xdfetch

Downloads crossword puzzles and converts them to
[.xd](https://github.com/century-arcade/xdformat), a plain-text crossword format.

**Early days.** It converts `.puz` and `.ipuz` files, from a URL or from disk. Downloading
by site name (`xdfetch get lat`) is next.

## Use

    pip install xdfetch            # or: uv tool install xdfetch

    xdfetch get https://example.com/puzzle.puz      # -> puzzle.xd
    xdfetch get https://example.com/puzzle.puz --format both   # also keep puzzle.puz as served
    xdfetch get https://example.com/puzzle.puz --format raw    # only the file as served
    xdfetch convert *.puz *.ipuz                    # -> one .xd each
    xdfetch convert old.puz -o -                    # to stdout

Output goes in the current directory unless `-o` names a file or a directory. An
existing file is left alone unless you add `--force`.

The format is picked by looking at the file, not its extension. Text is written as UTF-8,
as the puzzle had it.

## Outlets

The series xdfetch knows how to fetch are rows of
[`xdfetch/outlets.tsv`](xdfetch/outlets.tsv), each with an `id` of the form
`publisher.series`: `nytimes.daily`, `nytimes.mini`, `nytimes.midi`, `newyorker.daily`,
`newyorker.mini`, `universal.daily`, `universal.sunday`, `usatoday.daily`,
`washingtonpost.sunday`, `arkadium.mini`, `arkadium.two-minute-mini`,
`brendanemmettquigley.blog`, `dailyprincetonian.daily`, `dailyprincetonian.mini`. Each row
names the adapter that fetches it, the adapter's parameters, which days it runs, its
homepage and notes on its files. The column meanings are in `xdfetch/registry.py`.

    python -c "from xdfetch import registry; print(*registry.effective().by_id)"

Adapters return each file as the outlet served it; converting is a separate step.

## Adding downloaders from another package

Another package can add adapters and outlet rows without changing xdfetch, through
entry points in its `pyproject.toml`:

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

Tests use tiny puzzles made up for the purpose (`tests/conftest.py`). Please don't add
real, published puzzles to the repo.

## License

MIT. See [LICENSE](LICENSE).
