"""The `princetonian` adapter: The Daily Princetonian's crossword site.

params:
  mini   true for the mini, false (the default) for the full-size crossword

The site (https://crossword.dailyprincetonian.com/) is the paper's own, and its player reads
a small JSON API with no sign-in:

- GET /api/crosswords?mini=<true|false> lists every puzzle of that kind, newest first: id,
  title, date (midnight UTC of the day it ran), author_ids, description.
- GET /api/crosswords/<id> is that record again; /api/crosswords/<id>/clues is the puzzle,
  one object per clue with its answer and the x, y of its first square;
  /api/crosswords/<id>/authors is the constructors' names.

A puzzle is those last three answers, so they are kept as one file, <pubid>-<date>.json:

    {"crossword": <the record>, "clues": <the clues>, "authors": <the authors>}

Each value is the bytes the site served, unchanged; only the wrapper is ours. The list is
read once per run. A date the list doesn't have is a miss: neither series keeps a fixed
calendar (the paper stops for breaks and exams, and the mini comes and goes for months).
"""

from __future__ import annotations

import datetime as dt
import json

from ..http import FetchError, NotFound
from .base import Adapter, Fetched, Target

BASE = "https://crossword.dailyprincetonian.com"
PARTS = (("crossword", ""), ("clues", "/clues"), ("authors", "/authors"))


class PrincetonianAdapter(Adapter):
    name = "princetonian"
    interval = 2.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listed: dict[dt.date, dict] | None = None

    @property
    def list_url(self) -> str:
        mini = self.outlet.params.get("mini", "false").lower() == "true"
        return f"{BASE}/api/crosswords?mini={'true' if mini else 'false'}"

    def listed(self) -> dict[dt.date, dict]:
        """The site's list, by date, read once per run."""
        if self._listed is None:
            r = self.http.get(self.list_url, interval=self.interval)
            try:
                records = r.json()
                listed: dict[dt.date, dict] = {}
                for rec in records:
                    listed.setdefault(dt.date.fromisoformat(rec["date"][:10]), rec)
            except (ValueError, KeyError, TypeError) as e:
                raise FetchError(f"the puzzle list is not as expected: {e}", url=self.list_url) from e
            self._listed = listed
        return self._listed

    def targets(self, date: dt.date) -> list[Target]:
        rec = self.listed().get(date)
        if rec is None:
            raise NotFound(f"no puzzle dated {date} in the list", url=self.list_url)
        return [
            Target(
                url=f"{BASE}/api/crosswords/{rec['id']}",
                filename=f"{self.outlet.pubid}-{date.isoformat()}.json",
                note=f"{date}: {rec.get('title') or ''!r}; with /clues and /authors, wrapped in one object.",
            )
        ]

    def fetch(self, target: Target) -> Fetched:
        parts = []
        for key, path in PARTS:
            url = target.url + path
            r = self.http.get(url, interval=self.interval)
            body = r.content.strip()
            try:
                json.loads(body)
            except ValueError as e:
                raise FetchError(f"the answer is not JSON: {e}", url=url) from e
            parts.append(b'"' + key.encode() + b'": ' + body)
        data = b"{" + b", ".join(parts) + b"}\n"
        return Fetched(data=data, url=target.url, content_type="application/json", filename=target.filename)

    def describe(self) -> str:
        text = (
            "Each file is one puzzle from The Daily Princetonian's crossword site, as three answers "
            "from its API wrapped in one JSON object: `crossword` (/api/crosswords/<id>), `clues` "
            "(/api/crosswords/<id>/clues) and `authors` (/api/crosswords/<id>/authors), each exactly "
            "as served. The id for a date comes from the site's list (/api/crosswords?mini=...)."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
