"""The ledger: one row per fetch that ended in a file or a verdict. The restart point.

A run computes the dates each outlet should have, subtracts what the ledger already
holds, and fetches only that. Kill a run halfway and the next one carries on.

The ledger is `ledger.tsv` at the top of the store. Columns, in this order:
  pubid, date      which puzzle: the outlet's id and the puzzle's date
  filename         path inside the archive (blank for missing/error)
  sha256, bytes    of the file
  source_url       where it was fetched from
  fetched_at       ISO 8601 UTC
  archive          the archive (zip name) holding the file
  status           ok | same | changed | missing | error | companion
  detail           error text, or the sha the file was compared with
  modified         the server's Last-Modified (ISO 8601 UTC) where it sent one: when the file
                   was written, which for a static feed is when it became available

The first column holds the outlet's id (`Entry.id`). It is called `pubid` on disk because
existing stores were written with that name; the name is kept so they read and write
unchanged.

Statuses: `ok` first copy; `same` a re-fetch found identical bytes (no new file);
`changed` a re-fetch found different bytes (new file, kept beside the first);
`missing` the outlet has nothing for that date (a 404 or an empty page);
`error` something else went wrong (retried on later runs); `companion` a file kept beside
the puzzle (a listing record), archived but not a fetch of the puzzle.

A `missing` row is evidence too: the file wasn't up at that hour. `availability` reads
those and the `ok` rows back as an observed window per outlet, to check `available_after`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields

from . import tsv
from .store import Store

COLUMNS = [
    "pubid",
    "date",
    "filename",
    "sha256",
    "bytes",
    "source_url",
    "fetched_at",
    "archive",
    "status",
    "detail",
    "modified",
]
KEY = "ledger.tsv"


@dataclass
class Entry:
    id: str  # the outlet's id; the `pubid` column on disk
    date: str
    filename: str = ""
    sha256: str = ""
    bytes: str = ""
    source_url: str = ""
    fetched_at: str = ""
    archive: str = ""
    status: str = ""
    detail: str = ""
    modified: str = ""

    @property
    def day(self) -> dt.date:
        return dt.date.fromisoformat(self.date)


# Entry field -> ledger column, in column order. Only `id` is named differently on disk.
FIELD_COLUMNS = {f.name: ("pubid" if f.name == "id" else f.name) for f in fields(Entry)}
assert list(FIELD_COLUMNS.values()) == COLUMNS


def entry_from_row(row: dict[str, str]) -> Entry:
    """An Entry from a ledger row; a column the row lacks is blank."""
    return Entry(**{name: row.get(column, "") for name, column in FIELD_COLUMNS.items()})


def entry_to_row(entry: Entry) -> dict[str, str]:
    return {column: getattr(entry, name) for name, column in FIELD_COLUMNS.items()}


class Ledger:
    def __init__(self, entries: list[Entry] | None = None):
        self.entries: list[Entry] = entries or []

    @classmethod
    def parse(cls, text: str) -> Ledger:
        _, rows = tsv.parse(text)
        return cls([entry_from_row(r) for r in rows])

    @classmethod
    def load(cls, store: Store, key: str = KEY) -> Ledger:
        data = store.get(key)
        return cls.parse(data.decode("utf-8")) if data else cls()

    def save(self, store: Store, key: str = KEY) -> None:
        store.put(key, self.format().encode("utf-8"))

    def format(self) -> str:
        return tsv.format_rows(COLUMNS, [entry_to_row(e) for e in self.entries])

    def append(self, entry: Entry) -> None:
        self.entries.append(entry)

    def extend(self, entries: list[Entry]) -> None:
        self.entries.extend(entries)

    # --- queries ---

    def for_puzzle(self, oid: str, date: dt.date) -> list[Entry]:
        d = date.isoformat()
        return [e for e in self.entries if e.id == oid and e.date == d]

    def have(self, oid: str, date: dt.date) -> bool:
        """Do we hold a file for this puzzle?"""
        return any(e.status in ("ok", "changed") for e in self.for_puzzle(oid, date))

    def latest_file(self, oid: str, date: dt.date) -> Entry | None:
        files = [e for e in self.for_puzzle(oid, date) if e.status in ("ok", "changed")]
        return files[-1] if files else None

    def last_attempt(self, oid: str, date: dt.date) -> Entry | None:
        rows = self.for_puzzle(oid, date)
        return rows[-1] if rows else None

    def fetch_count(self, oid: str, date: dt.date) -> int:
        """How many times this puzzle was fetched with a result (ok/same/changed)."""
        return sum(1 for e in self.for_puzzle(oid, date) if e.status in ("ok", "same", "changed"))

    def versions(self, oid: str, date: dt.date) -> int:
        return sum(1 for e in self.for_puzzle(oid, date) if e.status in ("ok", "changed"))

    def consecutive_misses(self, oid: str, dates: list[dt.date]) -> int:
        """Of the given dates (ascending), how many at the end are missing or errored?"""
        n = 0
        for day in reversed(dates):
            last = self.last_attempt(oid, day)
            if last is None or last.status in ("ok", "same", "changed"):
                break
            n += 1
        return n
