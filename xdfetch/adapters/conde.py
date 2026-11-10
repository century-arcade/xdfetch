"""The `conde` adapter: Condé Nast's puzzle service, which plays The New Yorker's crosswords.

params:
  page   strftime template for the puzzle's page, e.g.
         https://www.newyorker.com/puzzles-and-games-dept/crossword/%Y/%m/%d
  api    optional: the service, default https://puzzles-games-api.gp-prod.conde.digital/api/v1/games/

The page carries the puzzle's id (a UUID) in its embedded data; the service answers
`<api><id>` with a JSON record whose `data` field is the puzzle as xd-like text
(## Metadata, ## Grid, ## Clues, and sometimes ## Design, ## Help). The record is returned as
served, named <id>-YYYY-MM-DD.json by the date asked for. The target's URL is the
service's; the page URL is in the target's note.
"""

from __future__ import annotations

import datetime as dt
import re

from ..http import FetchError, NotFound
from .base import Adapter, Target

DEFAULT_API = "https://puzzles-games-api.gp-prod.conde.digital/api/v1/games/"
UUID = re.compile(r'"id"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"')


class CondeAdapter(Adapter):
    name = "conde"
    interval = 3.0

    def targets(self, date: dt.date) -> list[Target]:
        page = date.strftime(self.outlet.param("page"))
        r = self.http.get(page, interval=self.interval)
        m = UUID.search(r.text)
        if not m:
            raise FetchError("page has no puzzle id", url=page)
        api = self.outlet.params.get("api", DEFAULT_API)
        return [
            Target(
                url=api + m.group(1),
                filename=f"{self.outlet.id}-{date.isoformat()}.json",
                note=f"The page for {date} is {page}.",
            )
        ]

    def fetch(self, target: Target):
        got = super().fetch(target)
        if b'"data"' not in got.data:
            raise NotFound("service record has no puzzle data", url=target.url)
        return got

    def describe(self) -> str:
        page = self.outlet.param("page")
        text = (
            f"Each file is one response from the magazine's puzzle service "
            f"(`{self.outlet.params.get('api', DEFAULT_API)}<puzzle id>`), saved as served: the data the puzzle's "
            f"page plays. The puzzle id is read from the page for the date (`{page}`). Files are named by the "
            f"date asked for. In each response, `data` holds the puzzle as text in sections (Metadata, Grid, "
            f"Clues, Design, Help)."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
