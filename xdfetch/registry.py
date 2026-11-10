"""The outlet registry: outlets.tsv, one row per outlet.

Columns:
    id               the outlet's id, following the xd corpus's publication ids
    adapter          which adapter fetches it (see xdfetch.adapters)
    params           the adapter's parameters, as space-separated key=value
    days             publication days: daily, mon-sat, sun, ...
    tz               the outlet's time zone, for "today"
    homepage         the outlet's own page for its puzzles
    notes            anything worth knowing
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

OUTLETS_TSV = Path(__file__).with_name("outlets.tsv")


@dataclass(frozen=True)
class Outlet:
    id: str
    adapter: str
    params: str = ""
    days: str = "daily"
    tz: str = "America/New_York"
    homepage: str = ""
    notes: str = ""


def load(path: Path = OUTLETS_TSV) -> dict[str, Outlet]:
    """Read a registry file. Later rows with the same id replace earlier ones."""
    outlets: dict[str, Outlet] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            fields = {k: (v or "") for k, v in row.items() if k in Outlet.__dataclass_fields__}
            outlet = Outlet(**fields)
            outlets[outlet.id] = outlet
    return outlets
