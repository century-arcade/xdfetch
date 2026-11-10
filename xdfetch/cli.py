"""xdfetch: download crossword puzzles and convert them to .xd.

  xdfetch get URL             download a puzzle file and write it as .xd (or as served)
  xdfetch get ID [--date D]   fetch an outlet's puzzle (latest by default) and write it as .xd
  xdfetch convert FILE        convert local puzzle files to .xd
  xdfetch list                the outlets xdfetch can fetch, by id

Output goes to the current directory, named after the input (puzzle.puz -> puzzle.xd) or,
for an outlet, <id>-<YYYY-MM-DD>.xd.

Keeping an archive. A store (a directory, or s3://bucket/prefix) holds a ledger of every
fetch, zip archives of the files as served, and a report per run:

  xdfetch run           fetch what's due (yesterday by default, or a range), archive it, update the ledger
  xdfetch plan          what `run` would fetch, without fetching
  xdfetch status        per-outlet state from the ledger
  xdfetch availability  when each outlet's file is actually up, from the ledger, against available_after
  xdfetch verify        check archives' files against their manifests

Exit status: 0 done, 1 failed, 2 usage, 3 the outlet has no puzzle for that date (get).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

from . import __version__, adapters, availability, fetch
from . import archive as arch
from . import registry as reg
from .convert import Context, ConvertError, PluginError, UnknownFormat, format_of
from .convert import convert as convert_puzzle
from .http import DownloadError, FetchError, Http, NotFound, download
from .ledger import Ledger
from .store import Store, open_store

OK, FAILED, USAGE, NOT_FOUND = 0, 1, 2, 3
STORE_ENV = "XDFETCH_STORE"


class UsageError(Exception):
    """Bad arguments: main() prints the message and exits USAGE."""


# --- converting and writing files -------------------------------------------------------


def convert(data: bytes, filename: str, ctx: Context | None = None) -> str:
    """The .xd text for a puzzle file's bytes, whatever its format (see xdfetch.convert)."""
    name = filename or "input"
    try:
        _, puzzle = convert_puzzle(data, ctx or Context(filename=filename))
    except UnknownFormat as e:
        raise ConvertError(f"{name}: not a puzzle format xdfetch knows") from e
    except PluginError as e:
        raise ConvertError(f"{name}: {e}") from e
    except ConvertError as e:
        raise ConvertError(f"{name}: not a valid {format_of(e) or 'puzzle'} file ({e})") from e
    except Exception as e:  # a damaged file can trip a converter in ways it doesn't foresee
        raise ConvertError(f"{name}: not a valid {format_of(e) or 'puzzle'} file ({type(e).__name__}: {e})") from e
    return puzzle.to_xd()


def output_path(name: str, out: str | None) -> Path | None:
    """Where to write the .xd for an input called `name`; None means stdout."""
    if out == "-":
        return None
    xdname = Path(name).stem + ".xd"
    if out is None:
        return Path(xdname)
    p = Path(out)
    return p / xdname if p.is_dir() else p


def write(xd: str, path: Path | None, force: bool) -> None:
    if path is None:
        sys.stdout.write(xd)
        return
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; use --force to replace it")
    path.write_text(xd, encoding="utf-8", newline="\n")
    print(path, file=sys.stderr)


def raw_path(name: str, out: str | None) -> Path | None:
    """Where to keep the file as served; None means stdout."""
    if out == "-":
        return None
    if out is None:
        return Path(name)
    p = Path(out)
    return p / name if p.is_dir() else p


def write_raw(data: bytes, path: Path | None, force: bool) -> None:
    if path is None:
        sys.stdout.buffer.write(data)
        return
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; use --force to replace it")
    path.write_bytes(data)
    print(path, file=sys.stderr)


def write_puzzle(data: bytes, served_name: str, xd: str | None, xd_name: str, args: argparse.Namespace) -> None:
    """Write per --format: the .xd under `xd_name`, and/or the bytes as served under `served_name`."""
    if args.format == "raw":
        write_raw(data, raw_path(served_name, args.out), args.force)
        return
    assert xd is not None
    if args.format == "both":  # the file as served goes beside the .xd, under the site's name
        xd_path = output_path(xd_name, args.out)
        folder = xd_path.parent if xd_path else Path()
        write_raw(data, folder / served_name, args.force)
    write(xd, output_path(xd_name, args.out), args.force)


# --- shared pieces for commands: dates, the registry, the store ----------------------------


def parse_date(s: str) -> dt.date:
    """YYYY-MM-DD, `today` or `yesterday` (UTC)."""
    if s == "today":
        return dt.datetime.now(dt.UTC).date()
    if s == "yesterday":
        return dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise UsageError(f"not a date: {s!r} (YYYY-MM-DD, today or yesterday)") from e


def date_range(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    """--date D, or --start/--end (each defaulting to today), or yesterday."""
    if args.date:
        d = parse_date(args.date)
        return d, d
    if args.start or args.end:
        start = parse_date(args.start) if args.start else parse_date("today")
        end = parse_date(args.end) if args.end else parse_date("today")
        return start, end
    y = parse_date("yesterday")
    return y, y


def add_registry_option(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--registry",
        action="append",
        metavar="FILE",
        help="a TSV of outlet rows laid over xdfetch's own (repeatable; later files win)",
    )


def load_registry(args: argparse.Namespace) -> reg.Registry:
    """The effective registry with --registry files on top."""
    return reg.effective(getattr(args, "registry", None) or [])


def add_store_option(p: argparse.ArgumentParser, env: str = STORE_ENV, default: str | None = None) -> None:
    p.add_argument(
        "--store",
        default=os.environ.get(env) or default,
        help=f"where the ledger and archives live: a directory or s3://bucket/prefix (default: ${env}"
        + (f" or {default})" if default else ")"),
    )
    p.add_argument("-v", "--verbose", action="store_true", help="log more")


def store_from_args(args: argparse.Namespace, env: str = STORE_ENV) -> Store:
    if not args.store:
        raise UsageError(f"no store: pass --store DIR (or s3://bucket/prefix), or set {env}")
    return open_store(args.store)


def add_range_options(p: argparse.ArgumentParser, id_option: str = "--id") -> None:
    p.add_argument("--date", help="one date (YYYY-MM-DD, today, yesterday); default yesterday")
    p.add_argument("--start", help="first date of a range")
    p.add_argument("--end", help="last date of a range (default: today)")
    p.add_argument(
        id_option, dest="ids", nargs="+", metavar="ID", help="only these outlets (default: every enabled one)"
    )
    p.add_argument("--no-refetch", action="store_true", help="don't re-fetch recent puzzles to compare")
    p.add_argument("--force", action="store_true", help="fetch even what the ledger already has")


def add_run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--interval", type=float, default=2.0, help="seconds between requests to one host")
    p.add_argument("--dry-run", action="store_true", help="plan only")
    p.add_argument("--summary", help="also write the markdown report here (e.g. a CI job summary)")


# --- the archive's commands: each takes a registry and a store, for reuse ----------------


def cmd_plan(args: argparse.Namespace, registry: reg.Registry, store: Store) -> int:
    start, end = date_range(args)
    ledger = Ledger.load(store)
    jobs = fetch.plan(registry, ledger, start, end, args.ids, refetch=not args.no_refetch, force=args.force)
    for j in jobs:
        print(f"{j.outlet.id}\t{j.date}\t{j.reason}")
    print(f"{len(jobs)} to fetch", file=sys.stderr)
    return OK


def run_command(
    args: argparse.Namespace, registry: reg.Registry, store: Store, http: Http | None = None, **options
) -> fetch.RunReport:
    """`run` without the exit status: fetch.run with the arguments, the report printed (and
    written to --summary). `options` go to fetch.run (archive=, on_archive=, report_title=, ...)."""
    start, end = date_range(args)
    report = fetch.run(
        registry,
        store,
        start,
        end,
        args.ids,
        http=http or Http(interval=args.interval),
        refetch=not args.no_refetch,
        force=args.force,
        dry_run=args.dry_run,
        **options,
    )
    print(report.markdown())
    if args.summary:
        Path(args.summary).write_text(report.markdown(), encoding="utf-8")
    return report


def cmd_run(args: argparse.Namespace, registry: reg.Registry, store: Store, **options) -> int:
    report = run_command(args, registry, store, **options)
    return FAILED if report.errored else OK


def cmd_status(args: argparse.Namespace, registry: reg.Registry, store: Store, today: dt.date | None = None) -> int:
    ledger = Ledger.load(store)
    today = today or parse_date("today")
    print("id\tenabled\tlast file\tfiles\tmissing\terrors\tmisses in a row")
    for o in registry.select(include_disabled=True):
        rows = [e for e in ledger.entries if e.id == o.id]
        files = [e for e in rows if e.status in ("ok", "changed")]
        last = max((e.date for e in files), default="")
        missing = sum(1 for e in rows if e.status == "missing")
        errors = sum(1 for e in rows if e.status == "error")
        recent = o.dates(today - dt.timedelta(days=14), today)
        streak = ledger.consecutive_misses(o.id, recent)
        print(f"{o.id}\t{'yes' if o.enabled else 'no'}\t{last}\t{len(files)}\t{missing}\t{errors}\t{streak}")
    return OK


def cmd_availability(args: argparse.Namespace, registry: reg.Registry, store: Store) -> int:
    print(availability.table(availability.observe(registry, Ledger.load(store))))
    return OK


def cmd_verify(args: argparse.Namespace, extra_files: Iterable[str] | None = None) -> int:
    """Check archive files (paths) against their manifests. See archive.verify for `extra_files`."""
    rc = OK
    for name in args.archive:
        try:
            problems = arch.verify(Path(name).read_bytes(), extra_files)
        except (OSError, zipfile.BadZipFile, KeyError) as e:  # KeyError: no MANIFEST.tsv
            print(f"{name}: not a readable archive: {e}")
            rc = FAILED
            continue
        for p in problems:
            print(f"{name}: {p}")
            rc = FAILED
        if not problems:
            print(f"{name}: ok")
    return rc


# --- list and get ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace, registry: reg.Registry) -> int:
    outlets = registry.select(include_disabled=True)
    rows = [(o.id, reg.format_days(o.days), o.homepage + ("" if o.enabled else "  (disabled)")) for o in outlets]
    w0 = max((len(r[0]) for r in rows), default=0)
    w1 = max((len(r[1]) for r in rows), default=0)
    for oid, days, homepage in rows:
        print(f"{oid:<{w0}}  {days:<{w1}}  {homepage}".rstrip())
    return OK


def latest_date(outlet: reg.Outlet, now: dt.datetime | None = None) -> dt.date | None:
    """The latest date the outlet has a puzzle for that should be up by now; None if none."""
    day = outlet.latest_available(now)
    for _ in range(366):
        if outlet.since and day < outlet.since:
            return None
        if outlet.publishes_on(day):
            return day
        day -= dt.timedelta(days=1)
    return None


def get_outlet(args: argparse.Namespace, outlet: reg.Outlet, http: Http | None = None) -> int:
    """`get ID`: fetch the outlet's puzzle for --date (default: its latest) and write it."""
    if args.date:
        date = parse_date(args.date)
        if not outlet.publishes_on(date):
            print(f"xdfetch: {outlet.id} has no puzzle on {date} ({describe_days(outlet)})", file=sys.stderr)
            return NOT_FOUND
    else:
        latest = latest_date(outlet)
        if latest is None:
            print(f"xdfetch: {outlet.id} has no puzzle up yet", file=sys.stderr)
            return NOT_FOUND
        date = latest
    http = http or Http()
    try:
        adapter = adapters.get(outlet.adapter)(outlet, http)
        targets = adapter.targets(date)
        companions: dict[str, bytes] = {}
        puzzles: list[tuple[adapters.Target, adapters.Fetched]] = []
        for t in targets:
            got = adapter.fetch(t)
            if t.companion:  # handed to the converter, not written
                companions[t.filename.rsplit("/", 1)[-1]] = got.data
            else:
                puzzles.append((t, got))
    except NotFound as e:
        where = f" at {e.url}" if e.url and e.url not in str(e) else ""
        print(f"xdfetch: {outlet.id} has no puzzle for {date}: {e}{where}", file=sys.stderr)
        return NOT_FOUND
    except adapters.MissingSecret as e:
        print(
            f"xdfetch: {outlet.id} needs a secret: set the environment variable {e.variable} and try again",
            file=sys.stderr,
        )
        return FAILED
    except FetchError as e:
        where = f" at {e.url}" if e.url and e.url not in str(e) else ""
        print(f"xdfetch: {outlet.id} {date}: {e}{where}", file=sys.stderr)
        return FAILED
    except Exception as e:  # an adapter or registry problem: say so, don't trace back
        print(f"xdfetch: {outlet.id} {date}: {type(e).__name__}: {e}", file=sys.stderr)
        return FAILED
    if not puzzles:
        print(f"xdfetch: {outlet.id} has no puzzle for {date}", file=sys.stderr)
        return NOT_FOUND
    try:
        converted = []
        for i, (t, got) in enumerate(puzzles):
            served = Path(got.filename or t.filename).name
            xd_name = f"{outlet.id}-{date.isoformat()}" + (f"-{i + 1}" if i else "") + ".xd"
            xd = None
            if args.format != "raw":  # convert everything before writing anything
                ctx = Context(outlet.id, date, served, got.url, dict(outlet.params), companions)
                xd = convert(got.data, served, ctx)
            converted.append((got.data, served, xd, xd_name))
        for data, served, xd, xd_name in converted:
            write_puzzle(data, served, xd, xd_name, args)
    except (ConvertError, OSError) as e:
        print(f"xdfetch: {e}", file=sys.stderr)
        return FAILED
    return OK


def describe_days(outlet: reg.Outlet) -> str:
    days = reg.format_days(outlet.days)
    text = "daily" if days == "daily" else f"runs {days}"
    return text + (f", since {outlet.since}" if outlet.since else "")


def get_url(args: argparse.Namespace) -> int:
    try:
        got = download(args.what)
        if args.format == "raw":
            write_raw(got.data, raw_path(got.filename, args.out), args.force)
            return OK
        xd = convert(got.data, got.filename)  # before writing anything, so a bad file leaves nothing behind
        write_puzzle(got.data, got.filename, xd, got.filename, args)
    except (DownloadError, ConvertError, OSError) as e:
        print(f"xdfetch: {e}", file=sys.stderr)
        return FAILED
    return OK


def cmd_get(args: argparse.Namespace) -> int:
    if "://" in args.what:
        if args.date:
            raise UsageError("--date is for an outlet id, not a URL")
        return get_url(args)
    registry = load_registry(args)
    if args.what not in registry:
        raise UsageError(f"{args.what!r} is neither a URL nor an outlet id (`xdfetch list` shows the ids)")
    return get_outlet(args, registry[args.what])


def cmd_convert(args: argparse.Namespace) -> int:
    if len(args.files) > 1 and args.out and not Path(args.out).is_dir():
        raise UsageError("with several files, -o must be a directory")
    status = OK
    for f in args.files:
        try:
            xd = convert(Path(f).read_bytes(), Path(f).name)
            write(xd, output_path(f, args.out), args.force)
        except (ConvertError, OSError) as e:
            print(f"xdfetch: {e}", file=sys.stderr)
            status = FAILED
    return status


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xdfetch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"xdfetch {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def output_options(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-o", "--out", help="output file or directory; - for stdout")
        sp.add_argument("-f", "--force", action="store_true", help="replace files that exist")

    def with_store(fn):
        return lambda args: fn(args, load_registry(args), store_from_args(args))

    sp = sub.add_parser("get", help="download a puzzle (a URL, or an outlet's by id) and write it as .xd")
    sp.add_argument("what", metavar="URL|ID")
    sp.add_argument("--date", help="for an outlet: the puzzle's date (YYYY-MM-DD, today, yesterday); default latest")
    sp.add_argument(
        "--format",
        choices=["xd", "raw", "both"],
        default="xd",
        help="xd (the default), raw (the file as the site served it, unconverted), or both",
    )
    output_options(sp)
    add_registry_option(sp)
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("convert", help="convert local puzzle files to .xd")
    sp.add_argument("files", nargs="+", metavar="FILE")
    output_options(sp)
    sp.set_defaults(func=cmd_convert)

    sp = sub.add_parser("list", help="the outlets: id, days, homepage")
    add_registry_option(sp)
    sp.set_defaults(func=lambda args: cmd_list(args, load_registry(args)))

    sp = sub.add_parser("run", help="fetch what's due and archive it")
    add_store_option(sp)
    add_registry_option(sp)
    add_range_options(sp)
    add_run_options(sp)
    sp.set_defaults(func=with_store(cmd_run))

    sp = sub.add_parser("plan", help="show what run would fetch")
    add_store_option(sp)
    add_registry_option(sp)
    add_range_options(sp)
    sp.set_defaults(func=with_store(cmd_plan))

    sp = sub.add_parser("status", help="per-outlet state from the ledger")
    add_store_option(sp)
    add_registry_option(sp)
    sp.set_defaults(func=with_store(cmd_status))

    sp = sub.add_parser("availability", help="when each outlet's file is actually up, from the ledger")
    add_store_option(sp)
    add_registry_option(sp)
    sp.set_defaults(func=with_store(cmd_availability))

    sp = sub.add_parser("verify", help="check archives' files against their manifests")
    sp.add_argument("archive", nargs="+", metavar="ZIP")
    sp.set_defaults(func=cmd_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO, format="%(levelname)s %(message)s"
    )
    try:
        return args.func(args)
    except (UsageError, reg.RegistryError) as e:
        print(f"xdfetch: {e}", file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
