# xdfetch design

xdfetch downloads crossword puzzles from the sites that publish them and writes them as
[.xd](https://github.com/century-arcade/xdformat). It is meant to replace
[xword-dl](https://github.com/thisisparker/xword-dl) for anyone who wants .xd: one command,
no setup, and downloaders that live in plugins, so new sites can be added (or kept
private) without changing xdfetch itself.

This is a new implementation, written from scratch for this repo. The release plan is in
[docs/plan-0.1.0.md](docs/plan-0.1.0.md).

## Principles

1. **Keep what the site served.** A download is the bytes as the site sent them;
   conversion reads from those bytes. `--raw` saves them next to the `.xd`.
2. **Convert by format, not by site.** A converter is chosen by looking at the content,
   never the file extension. Many sites share one format (a puzzle host serves the same
   JSON to every newspaper that embeds it), so one converter serves them all.
3. **Full fidelity, and say what's lost.** Rebus squares, circles, shading and clue
   markup go into the `.xd` by the format's own conventions. Anything .xd can't hold is
   reported on stderr, never dropped silently. Text is written as the site wrote it
   (UTF-8, accents and curly quotes kept); xdfetch applies no house style.
4. **Downloaders are plugins.** The core knows how to fetch politely, convert, and
   write. Which sites exist is entirely up to the installed plugins, including the ones
   that ship with xdfetch.
5. **Polite by default.** The User-Agent names the tool and its repo. Requests to a host
   go one at a time, with a delay and backoff. Sites that need a subscription use the
   user's own credentials; xdfetch never works around a paywall.

## Pieces

| Module | Job |
|---|---|
| `xdfetch/model.py` | The `Puzzle` a converter builds: an `xdformat.xdfile` plus what was lost on the way. |
| `xdfetch/formats/` | Converters for open, documented formats: `.puz`, `.ipuz`, `.jpz`, and `.xd` itself. Each is a `sniff` and a `convert`. |
| `xdfetch/http.py` | The session every source uses: User-Agent, rate limit per host, retry with backoff, timeouts. |
| `xdfetch/source.py` | The plugin API: `Source`, `Download`, and helpers such as `UrlTemplateSource`. |
| `xdfetch/plugins.py` | Finds sources and formats through entry points; a broken plugin is reported, never fatal. |
| `xdfetch/config.py` | Settings and credentials: a TOML file, overridden by environment variables. |
| `xdfetch/naming.py` | Output filenames from a template. |
| `xdfetch/cli.py` | `list`, `get`, `convert`, `config`. |

## The plugin API

A plugin is any installed package that declares entry points:

```toml
[project.entry-points."xdfetch.sources"]
lat = "mypkg.lat:LATimes"            # a Source subclass, or a list of them

[project.entry-points."xdfetch.formats"]
amuse = "mypkg.amuse:FORMAT"         # a Format: name, sniff(bytes), convert(bytes, ctx)
```

A source says who it is and how to find a puzzle:

```python
class LATimes(Source):
    id = "lat"                       # short, lowercase; used in commands and filenames
    name = "Los Angeles Times"
    homepage = "https://www.latimes.com/games/daily-crossword"
    days = "daily"                   # which days a puzzle appears
    tz = "America/Los_Angeles"       # what "today" means for this site
    settings = ()                    # names of settings it needs, e.g. ("cookie",)

    def locate(self, date) -> Request | None: ...   # where that day's file is, or None
    def latest(self) -> date: ...                    # optional: the newest available date
    def fetch(self, req, http) -> Download: ...      # optional: anything beyond one GET
```

Most sources that serve a file at a predictable URL need no code beyond a declaration:

```python
Universal = UrlTemplateSource(
    id="up", name="Universal", url="https://example.com/data/fcx%y%m%d.xml", days="daily",
)
```

Sources and formats are separate on purpose: a site's own JSON format belongs with the
plugin that downloads from that site, while the open formats live in the core and every
plugin can use them.

Sources that ship with xdfetch register through the same entry points as any other
plugin, so moving a source into or out of this repo changes no code.

If two installed plugins declare the same source id, the user's config picks one; until
it does, `list` shows both as `plugin:id` and `get` asks which.

## Output

The default filename is `{id}{date}.xd`, e.g. `lat2026-11-09.xd`: the source id followed by
the puzzle's date, the same shape as the xd corpus's puzzle ids. `-o` takes a template
with `{id}`, `{date}` (with a strftime format: `{date:%Y%m%d}`), `{title}`, `{author}` and
`{ext}`; `-o -` writes to stdout.

Headers are the ones the .xd spec defines: Title, Author, Editor, Copyright, Date, Rebus,
Notes, and so on. Nothing tool-specific is added.

## Settings and credentials

`xdfetch config` shows where the file is and what's set. The file is TOML, one table
per source:

```toml
[nyt]
cookie = "..."
```

`XDFETCH_<ID>_<SETTING>` (e.g. `XDFETCH_NYT_COOKIE`) overrides the file. A source that is
missing a setting it needs fails with a message naming the setting.

## Tests

Converter tests use small fixtures written for the test, a few squares and clues, never
real puzzles: published puzzles are copyrighted and this repo is public. `xdfetch.testing`
gives plugin authors the same helper (raw bytes in, expected `.xd` out). Tests that reach
a live site are opt-in (`pytest --live`) and never run in CI.
