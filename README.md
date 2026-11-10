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

## Development

    uv sync
    uv run pytest
    uv run ruff check && uv run ruff format --check
    uv run ty check

Tests use tiny puzzles made up for the purpose (`tests/conftest.py`). Please don't add
real, published puzzles to the repo.

## License

MIT. See [LICENSE](LICENSE).
