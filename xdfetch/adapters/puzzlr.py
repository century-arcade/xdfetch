"""The `puzzlr` adapter: PZLR (puzzlr.net), the games platform behind the Wall Street
Journal's crosswords.

params:
  tenant   the publisher's slug on PZLR, e.g. wsj
  game     the tRPC procedure's game, default crossword
  offset   days added to the requested date to get the date PZLR files the puzzle under,
           default 0. The Journal's row asks for print dates and PZLR dates a puzzle by its
           online release, the day before: offset=-1.

The embed's own request, an anonymous CORS call, answers by tenant and date with no sign-in:

    https://api.puzzlr.net/trpc/crossword.getLevel?batch=1&input={"0":{"tenant":"wsj","date":"2026-10-28"}}

The response is saved as served (a one-element tRPC batch), named <id>-YYYY-MM-DD.json by
the requested date. A date with no level answers {"unavailable": true, "reason":
"not_scheduled"}: a miss.
"""

from __future__ import annotations

import datetime as dt
import json
from urllib.parse import quote

from ..http import FetchError, NotFound
from .base import Adapter, Fetched, Target

API = "https://api.puzzlr.net/trpc/"


class PuzzlrAdapter(Adapter):
    name = "puzzlr"
    interval = 3.0

    def level_url(self, date: dt.date) -> str:
        game = self.outlet.params.get("game", "crossword")
        payload = json.dumps(
            {"0": {"tenant": self.outlet.param("tenant"), "date": date.isoformat()}}, separators=(",", ":")
        )
        return f"{API}{game}.getLevel?batch=1&input={quote(payload, safe='')}"

    def targets(self, date: dt.date) -> list[Target]:
        offset = int(self.outlet.params.get("offset", "0"))
        theirs = date + dt.timedelta(days=offset)
        note = f"PZLR files the puzzle for {date} under {theirs}." if offset else ""
        return [Target(url=self.level_url(theirs), filename=f"{self.outlet.id}-{date.isoformat()}.json", note=note)]

    def fetch(self, target: Target) -> Fetched:
        got = super().fetch(target)
        try:
            body = json.loads(got.data)
            result = body[0]["result"]["data"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise FetchError(f"not a tRPC level response: {e}", url=target.url) from e
        if result.get("unavailable"):
            raise NotFound(f"no level: {result.get('reason', 'unavailable')}", url=target.url)
        if not isinstance(result.get("data"), dict) or "grid" not in result["data"]:
            raise FetchError("level response has no grid", url=target.url)
        return got

    def describe(self) -> str:
        tenant = self.outlet.param("tenant")
        offset = int(self.outlet.params.get("offset", "0"))
        game = self.outlet.params.get("game", "crossword")
        text = (
            f"The outlet plays its puzzles on PZLR (puzzlr.net), tenant `{tenant}`. Each file is the response to "
            f'the embed\'s own request for a date, `{API}{game}.getLevel?batch=1&input={{"0":{{"tenant":'
            f'"{tenant}","date":"<date>"}}}}`, saved as served and named by the date asked for.'
        )
        if offset:
            text += (
                f" PZLR's date for a puzzle is {abs(offset)} day(s) {'before' if offset < 0 else 'after'} the date "
                "it is filed under here."
            )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
