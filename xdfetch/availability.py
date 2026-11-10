"""When each outlet's file is actually up, learned from the ledger.

The registry's `available_after` is a guess. Every fetch leaves evidence: a `missing` row
says the file wasn't there at that hour, the first `ok` row says it was, and a server that
sends Last-Modified (a static feed usually does; an API usually doesn't) says when it
was written. Hours count from the puzzle date's midnight in the outlet's timezone, the clock
`available_after` uses, so a negative number is the day before.

A run only looks for a file once `available_after` has passed, so the ledger can show that
the guess is too low (a miss after it) but not that it's too high; only Last-Modified can.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .ledger import Entry, Ledger
from .registry import Outlet, Registry


@dataclass
class Observed:
    id: str
    available_after: float
    dates: int  # dates with a file
    seen_up: float | None  # the earliest hour a first fetch found the file
    seen_not_up: float | None  # the latest hour a fetch found nothing, for a date that later had a file
    modified: float | None  # the earliest Last-Modified hour, where the server sends one

    @property
    def verdict(self) -> str:
        """What the evidence says about available_after."""
        if self.seen_not_up is not None and self.seen_not_up >= self.available_after:
            return f"raise: not up {self.seen_not_up:+.1f}h"
        # the latest hour it's known not to have been up: a miss beats Last-Modified (a feed can
        # republish an older file), and the file is never up before it was written
        known = [x for x in (self.seen_not_up, self.modified) if x is not None]
        if known and max(known) + 0.5 < self.available_after:
            return f"could be {max(known) + 0.5:.1f}"
        return "ok" if self.dates else ""


def hours_after(outlet: Outlet, day: dt.date, when: dt.datetime) -> float:
    midnight = dt.datetime.combine(day, dt.time(), tzinfo=ZoneInfo(outlet.tz))
    return (when - midnight).total_seconds() / 3600


def _when(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def observe(registry: Registry, ledger: Ledger) -> list[Observed]:
    out = []
    for outlet in registry.select(include_disabled=True):
        by_date: dict[str, list[Entry]] = {}
        for e in ledger.entries:
            if e.id == outlet.id:
                by_date.setdefault(e.date, []).append(e)
        ups, nots, mods = [], [], []
        for date, rows in by_date.items():
            day = dt.date.fromisoformat(date)
            i = next((i for i, e in enumerate(rows) if e.status in ("ok", "changed")), None)
            if i is None:
                continue
            first = rows[i]
            if (t := _when(first.fetched_at)) is not None:
                ups.append(hours_after(outlet, day, t))
            if (t := _when(first.modified)) is not None:
                mods.append(hours_after(outlet, day, t))
            for e in rows[:i]:
                if e.status == "missing" and (t := _when(e.fetched_at)) is not None:
                    nots.append(hours_after(outlet, day, t))
        out.append(
            Observed(
                outlet.id,
                outlet.available_after,
                len(ups),
                min(ups) if ups else None,
                max(nots) if nots else None,
                min(mods) if mods else None,
            )
        )
    return out


def table(rows: list[Observed]) -> str:
    def h(x: float | None) -> str:
        return f"{x:+.1f}" if x is not None else "-"

    lines = ["id\tavailable_after\tdates\tseen up by\tseen not up at\tlast-modified\tverdict"]
    for r in rows:
        lines.append(
            f"{r.id}\t{r.available_after:g}\t{r.dates}\t{h(r.seen_up)}\t{h(r.seen_not_up)}\t{h(r.modified)}\t{r.verdict}"
        )
    lines += [
        "",
        "Hours after the puzzle date's midnight in the outlet's timezone (available_after's clock).",
        "seen up by: the earliest hour a first fetch found the file. seen not up at: the latest hour a",
        "fetch found nothing, for a date that later had a file. last-modified: the server's own, where it",
        "sends one. A run only looks once available_after has passed, so misses can show the guess is too",
        "low; only last-modified can show it's too high.",
    ]
    return "\n".join(lines)
