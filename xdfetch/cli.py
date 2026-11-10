"""xdfetch command line.

list   the outlets xdfetch knows
get    fetch one outlet's puzzle and write it as .xd (not written yet)
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, registry


def cmd_list(args: argparse.Namespace) -> int:
    outlets = registry.load()
    for o in sorted(outlets.values(), key=lambda o: o.id):
        print(f"{o.id}\t{o.days}\t{o.homepage}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    print("xdfetch get: not written yet", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xdfetch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"xdfetch {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list", help="the outlets xdfetch knows")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("get", help="fetch one outlet's puzzle and write it as .xd")
    sp.add_argument("outlet")
    sp.add_argument("--date", help="YYYY-MM-DD (default: the outlet's latest)")
    sp.set_defaults(func=cmd_get)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
