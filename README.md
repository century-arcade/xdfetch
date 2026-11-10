# xdfetch

Fetches crossword puzzles from the outlets that publish them online and converts them to
[.xd](https://github.com/century-arcade/xdformat), the plain-text crossword format of the
[xd corpus](https://github.com/century-arcade/xd).

**Status: just started.** The package installs and the command runs, but it can't fetch
anything yet. [DESIGN.md](DESIGN.md) has the design and [docs/plan-0.1.0.md](docs/plan-0.1.0.md) the plan for the first release.

## What it will do

    pip install xdfetch
    xdfetch list                        # the sites the installed plugins know
    xdfetch get lat                     # today's LA Times -> lat2026-11-09.xd
    xdfetch get nyt --date 2026-11-01   # with your own subscription cookie in the config
    xdfetch get https://example.com/puzzle.puz
    xdfetch convert old-puzzle.puz      # a local .puz, .ipuz or .jpz -> .xd

Three rules shape it:

1. **Fetch keeps the bytes as served.** The file the site sent is kept as it was, and
   conversion reads from that.
2. **Convert is separate:** one converter per *format*, not per site, chosen by looking
   at the content. Anything a source has that .xd can't carry is reported, never dropped
   silently.
3. **Downloaders are plugins.** Each site is a small source class in an installed package,
   so sites can be added (or kept private) without changing xdfetch.

## Development

    uv sync --group dev
    uv run pytest
    uv run ruff check

## License

MIT. See [LICENSE](LICENSE).
