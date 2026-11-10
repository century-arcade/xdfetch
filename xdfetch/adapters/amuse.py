"""The `amuse` adapter: Amuse Labs (PuzzleMe), the player behind the LA Times, the
Atlantic, Newsday, the Daily Beast, Vox, Vulture, the Walrus, the Crossword Club,
Defector and many more.

params:
  host      the player's base, e.g. https://lat.amuselabs.com/lat (the date picker and the
            crossword page live under it)
  set       the series on that player, e.g. latimes
  id        optional strftime template for the player's puzzle id, when the id encodes the
            date (tca%y%m%d, atlantic_%Y%m%d). Without it, the id is looked up by
            publication date on the set's date picker, which lists only recent puzzles.
  page      optional template for the outlet's own page for a date, when the picker can't be
            trusted (Vulture's lists several puzzles under one date): the page embeds the
            player as `crossword?id=<id>&set=<set>`, and the id is read from that. strftime
            fields, plus {month} (the month's name in lowercase) and {d} (the day of the
            month without a leading zero).
  fallback  optional undated page tried when the dated `page` is missing (an outlet that
            posts the day's puzzle only at a fixed address), taken only when the page's
            <title> names the date ("October 30").

How a fetch works (the player's protocol as worked out by xword-dl and kotwords):

1. GET {host}/date-picker?set={set}. Its <script id="params"> JSON has `rawsps`, base64 of a
   JSON with a `loadToken` (a short-lived JWT), and `streakInfo`, the recent puzzles with
   their ids and publication times. The response sets a `uid` cookie.
2. GET {host}/crossword?id={id}&set={set}&loadToken={token}&fvlt={fvlt}, where fvlt (the
   player's first-visit load token) is the XOR of the 32-bit character sums of the set, the
   id and the uid cookie. Without the load token the player redirects to the outlet's site.
3. The crossword page's <script id="params"> JSON has `rawc`: the puzzle JSON in base64, with
   successive chunks of it reversed, the chunks' lengths cycling through a 7-digit key.
   `unscramble()` finds the key and recovers the JSON.

The file kept is the unscrambled JSON exactly as it decodes, nothing added or removed, named
by the puzzle id (<id>.json). The URL recorded for it is the plain crossword URL (id and
set), without the session's tokens.

The unscrambling algorithm is adapted from kotwords (Apache-2.0,
https://github.com/jpd236/kotwords) by way of xword-dl (MIT,
https://github.com/thisisparker/xword-dl).
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import json
import logging
import re
from collections import deque
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from zoneinfo import ZoneInfo

from ..http import FetchError, NotFound
from .base import Adapter, Fetched, Target

log = logging.getLogger("xdfetch")

PARAMS = re.compile(r'<script[^>]*id="params"[^>]*>(.*?)</script>', re.S)
# the player embedded in an outlet's own page: crossword?id=<id>&set=<set>
EMBED = re.compile(r"crossword\?id=([^&\"'\s]+)&(?:amp;)?set=([^&\"'\s]+)")


class AmuseAdapter(Adapter):
    name = "amuse"
    interval = 3.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._picker: dict[str, Any] | None = None
        self._uid = ""

    # --- the picker ---

    @property
    def host(self) -> str:
        return self.outlet.param("host").rstrip("/")

    @property
    def set(self) -> str:
        return self.outlet.param("set")

    @property
    def set_q(self) -> str:
        """The set as it goes in a URL (a set's name can hold a space: `nymag-vulture 10x10`)."""
        return quote(self.set, safe="")

    def picker(self) -> dict[str, Any]:
        """The date picker's params JSON (fetched once in this adapter's life: one run)."""
        if self._picker is None:
            url = f"{self.host}/date-picker?set={self.set_q}"
            r = self.http.get(url, interval=self.interval)
            self._picker = parse_params(r.text, url)
            self._uid = r.cookies.get("uid") or self.http.session(url).cookies.get("uid") or ""
        return self._picker

    def load_token(self) -> str:
        rawsps = self.picker().get("rawsps")
        if not rawsps:
            raise FetchError("date picker has no rawsps (load token)", url=self.host)
        try:
            sps = json.loads(base64.b64decode(rawsps))
        except Exception as e:
            raise FetchError(f"rawsps is not base64 JSON: {e}", url=self.host) from e
        token = sps.get("loadToken", "") if isinstance(sps, dict) else ""
        if not token:
            raise FetchError("date picker params carry no loadToken", url=self.host)
        return token

    def listed(self) -> list[dict[str, Any]]:
        """Recent puzzles from the picker: [{id, title, date}], newest first."""
        out = []
        for item in self.picker().get("streakInfo") or []:
            d = item.get("puzzleDetails") or {}
            pid = d.get("puzzleId")
            if not pid:
                continue
            ts = d.get("publicationTime")
            tz = d.get("publicationTimeZone") or self.outlet.tz
            day = dt.datetime.fromtimestamp(int(ts) / 1000, ZoneInfo(tz)).date() if ts else None
            out.append({"id": pid, "title": d.get("title", ""), "date": day})
        return out

    def id_from_page(self, date: dt.date) -> str:
        """The puzzle id from the outlet's own page for the date (the `page` param)."""
        template = self.outlet.param("page")
        url = date.strftime(template).replace("{month}", date.strftime("%B").lower()).replace("{d}", str(date.day))
        try:
            r = self.http.get(url, interval=self.interval)
        except NotFound:
            fallback = self.outlet.params.get("fallback")
            if not fallback:
                raise
            r = self.http.get(fallback, interval=self.interval)
            # the page's title names its day ("The Puzzle — October 30"); links to other days
            # name theirs, so only the title counts
            stamp = f"{date:%B} {date.day}"
            title = re.search(r"<title>([^<]*)", html.unescape(r.text))
            if not title or not re.search(rf"\b{stamp}\b", title.group(1)):
                raise NotFound(f"no page for {date}, and the undated page isn't titled {stamp}", url=url) from None
            url = fallback
        text = html.unescape(r.text)
        for m in EMBED.finditer(text):
            if unquote(m.group(2)) == self.set:
                return m.group(1)
        raise FetchError(f"page has no {self.set} embed", url=url)

    def id_for(self, date: dt.date) -> str:
        template = self.outlet.params.get("id")
        if template:
            return date.strftime(template)
        if self.outlet.params.get("page"):
            return self.id_from_page(date)
        listed = self.listed()
        matches = [p for p in listed if p["date"] == date]
        if not matches:
            span = f"{listed[-1]['date']} to {listed[0]['date']}" if listed else "nothing"
            raise NotFound(
                f"no {self.set} puzzle dated {date} on the date picker (it lists {span})",
                url=f"{self.host}/date-picker?set={self.set_q}",
            )
        if len(matches) > 1:
            log.warning(
                "%s: %d puzzles dated %s on the picker; taking %s", self.outlet.id, len(matches), date, matches[0]["id"]
            )
        return matches[0]["id"]

    # --- the puzzle ---

    def clean_url(self, puzzle_id: str) -> str:
        return f"{self.host}/crossword?id={puzzle_id}&set={self.set_q}"

    def targets(self, date: dt.date) -> list[Target]:
        pid = self.id_for(date)
        return [Target(url=self.clean_url(pid), filename=f"{pid}.json")]

    def fetch(self, target: Target) -> Fetched:
        pid = dict(parse_qsl(urlsplit(target.url).query))["id"]
        token = self.load_token()
        uid = self._uid or self.http.session(self.host).cookies.get("uid") or ""
        url = f"{target.url}&loadToken={token}"
        if uid:
            url += f"&fvlt={fvlt(self.set, pid, uid)}"
        r = self.http.get(url, interval=self.interval)
        if urlsplit(r.url).netloc != urlsplit(self.host).netloc:
            raise FetchError(f"player redirected to {r.url}: load token rejected", url=target.url)
        text = r.text
        if "PuzzleMe Error" in text[:2000] or "was not found" in text:
            raise NotFound("player page says the puzzle was not found", url=target.url)
        params = parse_params(text, target.url)
        rawc = params.get("rawc") or ""
        if not rawc:
            m = re.search(r"window\.(?:puzzleEnv\.)?rawc\s*=\s*'([^']+)'", text)
            rawc = m.group(1) if m else ""
        if not rawc:
            raise FetchError("player page has no rawc", url=target.url)
        data = unscramble(rawc)
        if data is None:
            raise FetchError("could not unscramble rawc", url=target.url)
        return Fetched(
            data=data.encode("utf-8"), url=target.url, content_type="application/json", filename=target.filename
        )

    def describe(self) -> str:
        text = (
            f"The outlet plays its puzzles in an Amuse Labs (PuzzleMe) player, set `{self.set}` on "
            f"`{urlsplit(self.host).netloc}`. Each `.json` file is one puzzle's data from its player page "
            f"(`{self.clean_url('<id>')}`): the page carries that JSON as a scrambled string, and the file is "
            f"the same JSON unscrambled, with nothing added or removed. Files are named by the puzzle id."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text


def parse_params(page: str, url: str) -> dict[str, Any]:
    m = PARAMS.search(page)
    if not m:
        raise FetchError('page has no <script id="params">', url=url)
    try:
        params = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise FetchError(f"params script is not JSON: {e}", url=url) from e
    if not isinstance(params, dict):
        raise FetchError("params script is not a JSON object", url=url)
    return params


def fvlt(set_name: str, puzzle_id: str, uid: str) -> str:
    """The player's first-visit load token: the XOR of the 32-bit character sums of set, id and uid."""

    def charsum(s: str) -> int:
        return sum(ord(c) for c in s) & 0xFFFFFFFF

    return format((charsum(set_name) ^ charsum(puzzle_id) ^ charsum(uid)) & 0xFFFFFFFF, "x")


# --- unscrambling rawc ---

BASE64 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
MAX_CANDIDATES = 200_000  # the search is quick on real payloads; this stops it on garbage


def _reverse_chunks(s: str, key: list[int]) -> str:
    """Reverse successive chunks of s, their lengths cycling through the key. Its own inverse."""
    buf = list(s)
    i = n = 0
    while i < len(buf) - 1:
        length = min(key[n % len(key)], len(buf) - i)
        n += 1
        buf[i : i + length] = buf[i : i + length][::-1]
        i += length
    return "".join(buf)


def unscramble_with_key(rawc: str, key: list[int]) -> str | None:
    """Undo the chunk reversal with this key and base64-decode; None if that isn't UTF-8 text."""
    try:
        return base64.b64decode(_reverse_chunks(rawc, key), validate=True).decode("utf-8")
    except ValueError:
        return None


def _prefix_plausible(rawc: str, prefix: list[int], spacing: int) -> bool:
    """Could `prefix` be the start of the key? Reverse the first chunks of each stretch and
    check that the base64 under them decodes to plausible UTF-8."""
    pos = 0
    while pos < len(rawc):
        start = pos
        chunk = []
        for length in prefix:
            if pos >= len(rawc):
                break
            length = min(length, len(rawc) - pos)
            chunk.append(rawc[pos : pos + length][::-1])
            pos += length
        s = "".join(chunk)
        b_start = ((start + 3) // 4) * 4 - start
        b_end = (pos // 4) * 4 - start
        if b_start >= len(s) or b_end <= b_start:
            pos += spacing
            continue
        try:
            decoded = base64.b64decode(s[b_start:b_end], validate=True)
        except ValueError:
            return False
        for b in decoded:
            if (b < 32 and b not in (9, 10, 13)) or b in (0xC0, 0xC1) or b >= 0xF5:
                return False
        pos += spacing
    return True


def unscramble(rawc: str) -> str | None:
    """Find the 7-digit key (each digit 2..20) by breadth-first search, and decode. None if no key works."""
    if not rawc or any(c not in BASE64 for c in rawc):
        return None
    ye, we = rawc.find("ye"), rawc.find("we")  # reversed starts of base64 '{"' and '{\n'
    ye = ye if ye != -1 else len(rawc)
    we = we if we != -1 else len(rawc)
    first = min(ye, we) + 2
    queue: deque[list[int]] = deque([[first]] if first <= 20 else [[]])
    seen = 0
    while queue:
        seen += 1
        if seen > MAX_CANDIDATES:
            return None
        prefix = queue.popleft()
        if len(prefix) == 7:
            s = unscramble_with_key(rawc, prefix)
            if s is None:
                continue
            try:
                json.loads(s)
            except ValueError:
                continue
            return s
        for digit in range(2, 21):
            cand = [*prefix, digit]
            remaining = 7 - len(cand)
            if any(_prefix_plausible(rawc, cand, sp) for sp in range(2 * remaining, 20 * remaining + 1)):
                queue.append(cand)
    return None


def scramble(text: str, key: list[int]) -> str:
    """The inverse of unscramble_with_key, for tests."""
    return _reverse_chunks(base64.b64encode(text.encode("utf-8")).decode("ascii"), key)
