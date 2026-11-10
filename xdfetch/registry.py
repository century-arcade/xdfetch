"""The outlet registry: one row per puzzle series xdfetch knows how to fetch.

The key is `pubid`, which follows the xd corpus's publication ids (lat, nyt, up...).

Columns:
  pubid            the series' id
  adapter          which adapter fetches it (xdfetch.adapters, or a plugin's)
  params           adapter parameters as key=value pairs, shell-quoted if they hold spaces
  days             which days a puzzle exists: daily | mon-sat | sun | mon,thu | ...
  since            first date to expect a puzzle (YYYY-MM-DD), blank = unknown
  tz               the outlet's timezone (IANA name) for "today"
  available_after  hours after local midnight before the day's file is reliably up
  refetch          days after publication worth fetching again and comparing, e.g. 1,2 (blank = never)
  homepage         the outlet's own page for the series
  auth             name of the environment variable holding the secret the adapter needs, blank = none
  enabled          yes | no
  notes            free text: what the file is, how it's named, quirks of the series

Overlays. The effective registry (`effective()`) is built in layers:

  1. xdfetch's own outlets.tsv, next to this module;
  2. each TSV registered by an installed package under the entry-point group
     `xdfetch.registries`, in order of entry-point name. The entry point's object is the
     path to the file (a str or os.PathLike, or an importlib.resources Traversable), or a
     callable taking no arguments that returns one;
  3. any files passed to `effective()`, in the order given.

A later layer's row with the same pubid replaces the earlier row whole (no column-by-column
merging), keeping the earlier row's place in the order; new pubids are added at the end.
Within one file, a pubid may appear only once. A layer may leave out columns; they take
their defaults.
"""

from __future__ import annotations

import datetime as dt
import os
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import metadata
from importlib.resources import as_file
from importlib.resources.abc import Traversable
from pathlib import Path
from zoneinfo import ZoneInfo

from . import tsv

BUILTIN = Path(__file__).with_name("outlets.tsv")
ENTRY_POINT_GROUP = "xdfetch.registries"

COLUMNS = [
    "pubid",
    "adapter",
    "params",
    "days",
    "since",
    "tz",
    "available_after",
    "refetch",
    "homepage",
    "auth",
    "enabled",
    "notes",
]

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class RegistryError(ValueError):
    pass


@dataclass
class Outlet:
    pubid: str
    adapter: str
    params: dict[str, str] = field(default_factory=dict)
    days: frozenset[int] = frozenset(range(7))  # 0 = Monday, as datetime.weekday()
    since: dt.date | None = None
    tz: str = "America/New_York"
    available_after: float = 0.0
    refetch: tuple[int, ...] = ()
    homepage: str = ""
    auth: str = ""
    enabled: bool = True
    notes: str = ""

    def publishes_on(self, day: dt.date) -> bool:
        if self.since and day < self.since:
            return False
        return day.weekday() in self.days

    def dates(self, start: dt.date, end: dt.date) -> list[dt.date]:
        """Every date in [start, end] this outlet should have a puzzle for."""
        out = []
        day = start
        while day <= end:
            if self.publishes_on(day):
                out.append(day)
            day += dt.timedelta(days=1)
        return out

    def latest_available(self, now: dt.datetime | None = None) -> dt.date:
        """The latest date whose puzzle should be up by now, in the outlet's timezone."""
        now = now or dt.datetime.now(dt.UTC)
        local = now.astimezone(ZoneInfo(self.tz))
        local -= dt.timedelta(hours=self.available_after)
        return local.date()

    def param(self, name: str, default: str | None = None) -> str:
        if name in self.params:
            return self.params[name]
        if default is None:
            raise RegistryError(f"{self.pubid}: adapter {self.adapter} needs param {name}")
        return default

    def to_row(self) -> dict[str, str]:
        return {
            "pubid": self.pubid,
            "adapter": self.adapter,
            "params": " ".join(f"{k}={shlex.quote(v)}" for k, v in self.params.items()),
            "days": format_days(self.days),
            "since": self.since.isoformat() if self.since else "",
            "tz": self.tz,
            "available_after": f"{self.available_after:g}" if self.available_after else "",
            "refetch": ",".join(str(d) for d in self.refetch),
            "homepage": self.homepage,
            "auth": self.auth,
            "enabled": "yes" if self.enabled else "no",
            "notes": self.notes,
        }


def parse_days(spec: str) -> frozenset[int]:
    spec = spec.strip().lower()
    if not spec or spec == "daily":
        return frozenset(range(7))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            ia, ib = WEEKDAYS.index(a), WEEKDAYS.index(b)
            if ia <= ib:
                out.update(range(ia, ib + 1))
            else:
                out.update(range(ia, 7))
                out.update(range(ib + 1))
        else:
            out.add(WEEKDAYS.index(part))
    return frozenset(out)


def format_days(days: frozenset[int]) -> str:
    if days == frozenset(range(7)):
        return "daily"
    return ",".join(WEEKDAYS[d] for d in sorted(days))


def parse_params(spec: str) -> dict[str, str]:
    params = {}
    for token in shlex.split(spec):
        if "=" not in token:
            raise RegistryError(f"param {token!r} is not key=value")
        k, v = token.split("=", 1)
        params[k] = v
    return params


def outlet_from_row(row: dict[str, str]) -> Outlet:
    pubid = row["pubid"].strip()
    try:
        days = parse_days(row.get("days", ""))
    except ValueError as e:
        raise RegistryError(f"{pubid}: bad days {row.get('days')!r}: {e}") from e
    since = row.get("since", "").strip()
    refetch = row.get("refetch", "").strip()
    tz = row.get("tz", "").strip() or "America/New_York"
    try:
        ZoneInfo(tz)
    except Exception as e:
        raise RegistryError(f"{pubid}: unknown tz {tz!r}") from e
    return Outlet(
        pubid=pubid,
        adapter=row["adapter"].strip(),
        params=parse_params(row.get("params", "")),
        days=days,
        since=dt.date.fromisoformat(since) if since else None,
        tz=tz,
        available_after=float(row.get("available_after", "") or 0),
        refetch=tuple(int(d) for d in refetch.split(",") if d.strip()),
        homepage=row.get("homepage", "").strip(),
        auth=row.get("auth", "").strip(),
        enabled=row.get("enabled", "yes").strip().lower() in ("", "yes", "y", "true", "1"),
        notes=row.get("notes", "").strip(),
    )


class Registry:
    def __init__(self, outlets: list[Outlet]):
        self.outlets = outlets
        self.by_pubid = {o.pubid: o for o in outlets}
        if len(self.by_pubid) != len(outlets):
            dupes = sorted({o.pubid for o in outlets if sum(x.pubid == o.pubid for x in outlets) > 1})
            raise RegistryError(f"duplicate pubid rows: {', '.join(dupes)}")

    @classmethod
    def load(cls, path: str | Path) -> Registry:
        """One TSV file on its own (no overlays)."""
        columns, rows = tsv.read(path)
        missing = [c for c in ("pubid", "adapter") if c not in columns]
        if missing:
            raise RegistryError(f"{path}: missing columns {missing}")
        try:
            return cls([outlet_from_row(r) for r in rows])
        except RegistryError as e:
            raise RegistryError(f"{path}: {e}") from e

    def overlay(self, other: Registry) -> Registry:
        """This registry with `other`'s rows on top: a row with the same pubid replaces ours whole."""
        merged = dict(self.by_pubid)
        merged.update(other.by_pubid)
        return Registry(list(merged.values()))

    def select(self, pubids: list[str] | None = None, include_disabled: bool = False) -> list[Outlet]:
        if pubids:
            unknown = [p for p in pubids if p not in self.by_pubid]
            if unknown:
                raise RegistryError(f"not in the registry: {', '.join(unknown)}")
            chosen = [self.by_pubid[p] for p in pubids]
        else:
            chosen = list(self.outlets)
        if not include_disabled:
            chosen = [o for o in chosen if o.enabled]
        return chosen

    def __getitem__(self, pubid: str) -> Outlet:
        return self.by_pubid[pubid]

    def __contains__(self, pubid: str) -> bool:
        return pubid in self.by_pubid


def plugin_files() -> list[tuple[str, Path | Traversable]]:
    """(entry point name, file) for each registry an installed package adds, by name."""
    out: list[tuple[str, Path | Traversable]] = []
    for ep in sorted(metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
        where = f"registry plugin {ep.name!r} ({ep.value}, entry point group {ENTRY_POINT_GROUP})"
        try:
            obj = ep.load()
            if callable(obj):
                obj = obj()
        except Exception as e:
            raise RegistryError(f"{where} failed to load: {e.__class__.__name__}: {e}") from e
        if isinstance(obj, (str, os.PathLike)):
            out.append((ep.name, Path(obj)))
        elif isinstance(obj, Traversable):
            out.append((ep.name, obj))
        else:
            raise RegistryError(f"{where} gave {type(obj).__name__}, not a path to a TSV file")
    return out


def _load_layer(name: str, path: Path | Traversable) -> Registry:
    if not path.is_file():
        raise RegistryError(f"{name}: no such file {path}")
    with as_file(path) as p:
        return Registry.load(p)


def effective(paths: Iterable[str | Path] = ()) -> Registry:
    """The registry to use: xdfetch's own rows, then each plugin's, then `paths`, later rows
    replacing earlier ones with the same pubid. See the module docstring."""
    reg = Registry.load(BUILTIN)
    for name, path in plugin_files():
        reg = reg.overlay(_load_layer(f"registry plugin {name!r}", path))
    for path in paths:
        reg = reg.overlay(_load_layer(str(path), Path(path)))
    return reg


def write(path: str | Path, outlets: list[Outlet]) -> None:
    Path(path).write_text(tsv.format_rows(COLUMNS, [o.to_row() for o in outlets]), encoding="utf-8")
