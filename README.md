# xdfetch

Downloads crossword puzzles and converts them to
[.xd](https://github.com/century-arcade/xdformat), a plain-text crossword format.

**Early days.** It converts puzzle files (see Formats below), from a URL or from disk.
Downloading by site name is next.

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
with curly quotes and ellipses made plain ASCII and HTML in clues turned into xd's markup.

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

Other packages can add formats as converter plugins, through the Python entry-point group
`xdfetch.converters`; the docstring of `xdfetch.convert` says how.

## Development

    uv sync
    uv run pytest
    uv run ruff check && uv run ruff format --check
    uv run ty check

Tests use tiny puzzles made up for the purpose (`tests/conftest.py`, `tests/synthetic.py`).
Please don't add real, published puzzles to the repo.

## License

MIT. See [LICENSE](LICENSE).
