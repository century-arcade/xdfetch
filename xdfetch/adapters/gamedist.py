"""The `gamedist` adapter: GameDistribution's crossword feeds, which carry King Features'
puzzles (Thomas Joseph, Eugene Sheffer, the Premier Crossword) for the players of
Arkadium and Hearst, since King's own `.jpz` feed stopped in April 2025.

params:
  feed   the feed's slug: hearst_thomas-joseph-crossword, hearst_eugene-sheffer-crossword,
         hearst_premier-sunday-crossword

How it works:

- A month listing, https://crosswords-sgweb.gamedistribution.com/feed/<slug>/year/<YYYY>/month/<M>,
  answers an anonymous GET with a JSON list of the puzzles from that month to the newest
  (about a week ahead of today): date, the feed's byline, and feedUrl, the puzzle's file
  under /storage/<slug>/<uuid>.json. Each month's listing is read once per run.
- The file is a Crossword Compiler document as JSON, with the puzzle's record from the
  listing in `metaData`. It is saved as served, named <id>-YYYY-MM-DD.json by the listing's
  date, and converted by `ccjson`.

A date the listing doesn't have is a miss.
"""

from __future__ import annotations

import datetime as dt

from ..http import FetchError, NotFound
from .base import Adapter, Target

BASE = "https://crosswords-sgweb.gamedistribution.com/feed"


class GameDistAdapter(Adapter):
    name = "gamedist"
    interval = 1.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listings: dict[tuple[int, int], dict[str, dict]] = {}

    def listing_url(self, date: dt.date) -> str:
        return f"{BASE}/{self.outlet.param('feed')}/year/{date.year}/month/{date.month}"

    def listing(self, date: dt.date) -> dict[str, dict]:
        key = (date.year, date.month)
        if key not in self._listings:
            url = self.listing_url(date)
            r = self.http.get(url, interval=self.interval)
            try:
                items = r.json()
            except ValueError as e:
                raise FetchError(f"month listing is not JSON: {e}", url=url) from e
            if not isinstance(items, list):
                raise FetchError("month listing is not a list", url=url)
            self._listings[key] = {i["date"]: i for i in items if isinstance(i, dict) and i.get("date")}
        return self._listings[key]

    def targets(self, date: dt.date) -> list[Target]:
        item = self.listing(date).get(date.isoformat())
        if not item or not item.get("feedUrl"):
            raise NotFound(f"no {self.outlet.id} puzzle dated {date} in the month listing", url=self.listing_url(date))
        return [Target(url=item["feedUrl"], filename=f"{self.outlet.id}-{date.isoformat()}.json")]

    def describe(self) -> str:
        feed = self.outlet.param("feed")
        text = (
            f"Each file is the puzzle's record on GameDistribution's crossword feed `{BASE}/{feed}/`, saved as "
            "served: a Crossword Compiler document as JSON, with the feed's record of the puzzle (its date and "
            f"byline) in `metaData`. The feed's month listings (`{BASE}/{feed}/year/<YYYY>/month/<M>`) give "
            "each date's file, `/storage/<slug>/<uuid>.json`; the file is named here by the listing's date."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
