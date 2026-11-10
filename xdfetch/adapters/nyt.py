"""The `nyt` adapter: the New York Times's own puzzle data, the v6 JSON its solving page loads.

params:
  kind   the feed: daily, mini, bonus, ... (https://www.nytimes.com/svc/crosswords/v6/puzzle/<kind>/<date>.json)
  url    optional: a full strftime template instead of kind, for named puzzles
         (https://www.nytimes.com/svc/crosswords/v6/puzzle/named/%Y-%m-%d.json)

The registry's `auth` names the environment variable holding a subscriber's NYT-S
cookie, which is sent with each request. If the variable isn't set, the adapter logs a
warning once and makes the request without the cookie; it doesn't decide beforehand
whether the fetch can work. Either way the fetch is judged by what comes back: the payload
must be for the date asked for and its cells must carry answers, and one that isn't or
doesn't is an error.
The file is returned exactly as served, named <id>-YYYY-MM-DD.json.

The Times rewrites clues after the day of publication; set `refetch` on the row.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from ..http import FetchError, NotFound
from .base import Adapter, Fetched, Target

log = logging.getLogger("xdfetch")

BASE = "https://www.nytimes.com/svc/crosswords/v6/puzzle"


class NytAdapter(Adapter):
    name = "nyt"
    interval = 3.0
    _warned = False

    def targets(self, date: dt.date) -> list[Target]:
        template = self.outlet.params.get("url")
        if template:
            url = date.strftime(template)
        else:
            url = f"{BASE}/{self.outlet.param('kind', 'daily')}/{date.isoformat()}.json"
        cookies = {}
        if self.outlet.auth:
            value = self.secrets.get(self.outlet.auth, "")
            if value:
                cookies["NYT-S"] = value
            elif not self._warned:
                log.warning("%s: %s is not set; fetching without a session cookie", self.outlet.id, self.outlet.auth)
                self._warned = True
        return [Target(url=url, filename=f"{self.outlet.id}-{date.isoformat()}.json", cookies=cookies)]

    def fetch(self, target: Target) -> Fetched:
        got = super().fetch(target)
        try:
            body = json.loads(got.data)
        except ValueError as e:
            raise FetchError(f"not JSON: {e}", url=target.url) from e
        if not isinstance(body, dict) or not body.get("body"):
            raise NotFound("payload has no puzzle body", url=target.url)
        wanted = target.filename.rsplit("-", 3)[-3:]
        wanted_date = "-".join(wanted)[:10]
        if body.get("publicationDate") and body["publicationDate"] != wanted_date:
            raise NotFound(f"payload is dated {body['publicationDate']}, not {wanted_date}", url=target.url)
        cells = [c for c in body["body"][0].get("cells", []) if c]
        if cells and not any(c.get("answer") for c in cells):
            raise FetchError("payload has no answers: the NYT-S cookie is missing or expired", url=target.url)
        return got

    def describe(self) -> str:
        kind = self.outlet.params.get("kind", "daily")
        text = (
            f"Each file is the puzzle data the Times's solving page loads, `{BASE}/{kind}/<YYYY-MM-DD>.json`, "
            f"saved as served and named by the date asked for. Fetched with a subscriber's session cookie."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
