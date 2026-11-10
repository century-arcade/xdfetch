"""xdfetch: download crossword puzzles and convert them to .xd.

  xdfetch get URL         download a .puz or .ipuz file and write it as .xd
  xdfetch convert FILE    convert local .puz or .ipuz files to .xd

Output goes to the current directory, named after the input (puzzle.puz -> puzzle.xd).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .formats import ConvertError, convert
from .http import DownloadError, download

OK, FAILED, USAGE = 0, 1, 2


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


def cmd_get(args: argparse.Namespace) -> int:
    if "://" not in args.what:
        print(f"xdfetch: {args.what!r} isn't a URL (named sources aren't supported yet)", file=sys.stderr)
        return USAGE
    try:
        got = download(args.what)
        xd = convert(got.data, got.filename)
        if args.raw:
            raw = Path(args.out) / got.filename if args.out and Path(args.out).is_dir() else Path(got.filename)
            if raw.exists() and not args.force:
                raise FileExistsError(f"{raw} exists; use --force to replace it")
            raw.write_bytes(got.data)
        write(xd, output_path(got.filename, args.out), args.force)
    except (DownloadError, ConvertError, OSError) as e:
        print(f"xdfetch: {e}", file=sys.stderr)
        return FAILED
    return OK


def cmd_convert(args: argparse.Namespace) -> int:
    if len(args.files) > 1 and args.out and not Path(args.out).is_dir():
        print("xdfetch: with several files, -o must be a directory", file=sys.stderr)
        return USAGE
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

    sp = sub.add_parser("get", help="download a puzzle and write it as .xd")
    sp.add_argument("what", metavar="URL")
    sp.add_argument("--raw", action="store_true", help="also keep the file as the site served it")
    output_options(sp)
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("convert", help="convert local puzzle files to .xd")
    sp.add_argument("files", nargs="+", metavar="FILE")
    output_options(sp)
    sp.set_defaults(func=cmd_convert)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
