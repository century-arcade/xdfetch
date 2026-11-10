# xdfetch

Fetches crossword puzzles from the outlets that publish them online and converts them to
[.xd](https://github.com/century-arcade/xdformat), the plain-text crossword format of the
[xd corpus](https://github.com/century-arcade/xd).

**Status: just started.** The package installs and the command runs, but it can't fetch
anything yet. [DESIGN.md](DESIGN.md) has the plan.

## What it will do

    pip install xdfetch
    xdfetch list                        # the outlets it knows
    xdfetch get lat                     # today's LA Times -> lat2026-11-09.xd
    xdfetch get nyt --date 2026-11-01   # with your own subscription cookie in NYT_S
    xdfetch run --store ./archive --start 2026-10-01 --end 2026-10-31   # keep an archive

Three rules shape it:

1. **Fetch keeps the bytes as served.** The file the outlet sent is kept as it was, and
   conversion reads from that.
2. **Convert is separate:** one converter per *format*, not per outlet, chosen by looking
   at the content. Anything a source has that .xd can't carry is reported, never dropped
   silently.
3. **Most outlets are a row, not code.** `outlets.tsv` says where each outlet's file is and
   when it publishes; code is only needed for a new kind of host.

## Development

    uv sync --group dev
    uv run pytest
    uv run ruff check

## License

MIT. See [LICENSE](LICENSE).
