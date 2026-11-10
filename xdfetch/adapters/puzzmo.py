"""The `puzzmo` adapter: a publisher's team queues on Puzzmo (the Boston Globe's crosswords).

params:
  team    the team slug on Puzzmo, e.g. boston-globe-amlaj
  queue   the queue, default crossword
  days    how many days back one list request covers, default 10 (Puzzmo serves up to 50)

- GET https://api.puzzmo.com/team/v1/<team>/queues/<queue>/puzzles?startDate=<date>&days=<n>
  lists the queue's puzzles from that date back (`days` must be positive; up to 50 are
  returned): id, name, publishDate, authors. The list is read once per run for the dates it
  covers. A queue can hold more than one series (the Globe's `crossword` queue holds its
  Sunday crossword and the Universal crossword on the other days); the row's calendar says
  which days to ask for.
- POST https://api.puzzmo.com/graphql with { puzzle(id: "<id>") { id name puzzle } } returns the
  puzzle; its `puzzle` field is the puzzle as xd text in Puzzmo's dialect. The response is
  saved as served, named <id>-YYYY-MM-DD.json by the list's publishDate.

A publisher's row needs the team slug and queue name, which its player page uses.
"""

from __future__ import annotations

import datetime as dt
import json

from ..http import FetchError, NotFound
from .base import Adapter, Fetched, Target

TEAM = "https://api.puzzmo.com/team/v1/{team}/queues/{queue}/puzzles?startDate={date}&days={days}"
GRAPHQL = "https://api.puzzmo.com/graphql"


class PuzzmoAdapter(Adapter):
    name = "puzzmo"
    interval = 3.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listed: dict[dt.date, dict] = {}
        self._asked: set[dt.date] = set()

    def list_url(self, date: dt.date) -> str:
        return TEAM.format(
            team=self.outlet.param("team"),
            queue=self.outlet.params.get("queue", "crossword"),
            date=date.isoformat(),
            days=self.outlet.params.get("days", "10"),
        )

    def listed(self, date: dt.date) -> dict | None:
        """The queue's record for the date, listing from that date back once per run."""
        if date not in self._listed and date not in self._asked:
            self._asked.add(date)
            url = self.list_url(date)
            r = self.http.get(url, interval=self.interval)
            try:
                puzzles = r.json()["puzzles"]
            except (ValueError, KeyError, TypeError) as e:
                raise FetchError(f"queue list is not as expected: {e}", url=url) from e
            for p in puzzles:
                try:
                    day = dt.date.fromisoformat(p["publishDate"])
                except (KeyError, ValueError, TypeError):
                    continue
                self._listed.setdefault(day, p)
        return self._listed.get(date)

    def targets(self, date: dt.date) -> list[Target]:
        filename = f"{self.outlet.id}-{date.isoformat()}.json"
        rec = self.listed(date)
        if rec is None:
            raise NotFound(f"no puzzle dated {date} in the {self.outlet.param('team')} queue", url=self.list_url(date))
        note = f"{date}: {rec.get('name', '')!r} by {', '.join(a.get('name', '') for a in rec.get('authors') or [])}"
        return [Target(url=GRAPHQL, filename=filename, note=note, headers={"X-Puzzle-Id": rec["id"]})]

    def fetch(self, target: Target) -> Fetched:
        puzzle_id = target.headers.get("X-Puzzle-Id", "")
        clean = puzzle_id.replace('"', "")
        query = f'{{ puzzle(id: "{clean}") {{ id name puzzle }} }}'
        r = self.http.post(target.url, json={"query": query}, interval=self.interval)
        try:
            body = json.loads(r.content)
            puzzle = body["data"]["puzzle"]
        except (ValueError, KeyError, TypeError) as e:
            raise FetchError(f"GraphQL answer is not a puzzle: {e}", url=target.url) from e
        if not puzzle or not puzzle.get("puzzle"):
            raise NotFound(f"no puzzle text for {puzzle_id}", url=target.url)
        return Fetched(data=r.content, url=target.url, content_type="application/json", filename=target.filename)

    def describe(self) -> str:
        team = self.outlet.param("team")
        queue = self.outlet.params.get("queue", "crossword")
        text = (
            f"The outlet plays its puzzles from Puzzmo. Its `{queue}` queue on Puzzmo's team API "
            f"(`https://api.puzzmo.com/team/v1/{team}/queues/{queue}/puzzles?startDate=<date>&days=<n>`) lists "
            f"the puzzles by date. Each file is the answer to the GraphQL query "
            f'`{{ puzzle(id: "<id>") {{ id name puzzle }} }}` posted to `{GRAPHQL}`, saved as served; its '
            f"`puzzle` field is the puzzle as xd text in Puzzmo's dialect. Files are named by the queue's "
            f"publishDate."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
