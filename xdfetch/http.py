"""Downloading, politely: one session per host, a User-Agent that names the tool, a rate
limit per host, and retries with backoff.

`Http` is what adapters use. `download()` is the one-shot fetch behind `xdfetch get URL`:
the same client, plus a size cap and a file name that can never be a path.

The User-Agent is a constructor parameter. It defaults to xdfetch's own; a program built
on xdfetch passes its own so that sites see who is really asking.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import email.utils
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import requests

from . import USER_AGENT

log = logging.getLogger("xdfetch")

DEFAULT_INTERVAL = 2.0  # seconds between requests to one host
RETRY_STATUSES = {429, 500, 502, 503, 504}
TIMEOUT = 30.0  # seconds
MAX_BYTES = 20 * 1024 * 1024  # no puzzle file is anywhere near this


def iso_http_date(value: str | None) -> str:
    """An HTTP date (a Last-Modified header) as ISO 8601 UTC, or '' when absent or unreadable."""
    if not value:
        return ""
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.UTC)
    return d.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FetchError(Exception):
    """A request that failed after retries, or a response we can't use."""

    def __init__(self, message: str, status: int | None = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class NotFound(FetchError):
    """The outlet has nothing at this address: a 404 or 410, or an empty body where a file was expected."""


DownloadError = FetchError  # the name `xdfetch get` has always caught


class Http:
    """GET with a per-host session, a per-host rate limit and retries.

    `interval` is the least time between two requests to one host; an adapter can ask for
    more per call. A connection error or a 429/5xx is retried `retries` times, waiting 2,
    4, 8... seconds (or the server's Retry-After, if longer). `sleep` and `clock` are there
    so tests never wait.
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
        retries: int = 3,
        timeout: float = TIMEOUT,
        sleep: Callable[[float], object] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        user_agent: str = USER_AGENT,
    ):
        self.interval = interval
        self.retries = retries
        self.timeout = timeout
        self.user_agent = user_agent
        self._sleep = sleep
        self._clock = clock
        self._sessions: dict[str, requests.Session] = {}
        self._last: dict[str, float] = {}
        self.requests_made = 0

    def session(self, url: str) -> requests.Session:
        host = urlsplit(url).netloc
        if host not in self._sessions:
            s = requests.Session()
            s.headers["User-Agent"] = self.user_agent
            self._sessions[host] = s
        return self._sessions[host]

    def _wait(self, url: str, interval: float | None) -> None:
        host = urlsplit(url).netloc
        gap = self.interval if interval is None else interval
        last = self._last.get(host)
        if last is not None:
            due = last + gap
            now = self._clock()
            if now < due:
                self._sleep(due - now)
        self._last[host] = self._clock()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        interval: float | None = None,
        allow_empty: bool = False,
        stream: bool = False,
    ) -> requests.Response:
        """GET with rate limiting and retries. Raises NotFound on 404/410 or an empty body,
        FetchError otherwise. With `stream`, the body is left unread (and not checked for
        being empty); the caller reads it and closes the response."""
        s = self.session(url)
        attempt = 0
        while True:
            attempt += 1
            self._wait(url, interval)
            self.requests_made += 1
            try:
                r = s.get(url, headers=headers, cookies=cookies, params=params, timeout=self.timeout, stream=stream)
            except requests.RequestException as e:
                if attempt > self.retries:
                    raise FetchError(f"{e.__class__.__name__}: {e}", url=url) from e
                self._backoff(attempt, None)
                continue
            if r.status_code in (404, 410):
                r.close()
                raise NotFound(f"HTTP {r.status_code}", status=r.status_code, url=url)
            if r.status_code in RETRY_STATUSES and attempt <= self.retries:
                r.close()
                self._backoff(attempt, r.headers.get("Retry-After"))
                continue
            if r.status_code >= 400:
                r.close()
                raise FetchError(f"HTTP {r.status_code}", status=r.status_code, url=url)
            if not stream and not r.content and not allow_empty:
                raise NotFound("empty response", status=r.status_code, url=url)
            return r

    def post(
        self,
        url: str,
        *,
        json: dict | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        interval: float | None = None,
    ) -> requests.Response:
        """POST with the same rate limiting and retries as get(). Raises NotFound on 404/410
        or an empty body, FetchError otherwise."""
        s = self.session(url)
        attempt = 0
        while True:
            attempt += 1
            self._wait(url, interval)
            self.requests_made += 1
            try:
                r = s.post(url, json=json, data=data, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt > self.retries:
                    raise FetchError(f"{e.__class__.__name__}: {e}", url=url) from e
                self._backoff(attempt, None)
                continue
            if r.status_code in (404, 410):
                raise NotFound(f"HTTP {r.status_code}", status=r.status_code, url=url)
            if r.status_code in RETRY_STATUSES and attempt <= self.retries:
                self._backoff(attempt, r.headers.get("Retry-After"))
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}", status=r.status_code, url=url)
            if not r.content:
                raise NotFound("empty response", status=r.status_code, url=url)
            return r

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = 2.0**attempt
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(delay, float(retry_after))
        log.info("retrying in %.0fs (attempt %d)", delay, attempt)
        self._sleep(delay)


@dataclass(frozen=True)
class Download:
    url: str  # where the bytes finally came from, after redirects
    data: bytes  # as served
    filename: str  # the name the site gave it, or the last part of the URL; never a path


def download(url: str, http: Http | None = None, max_bytes: int = MAX_BYTES) -> Download:
    """Fetch one file whole, refusing anything bigger than `max_bytes`."""
    http = http or Http()
    try:
        r = http.get(url, stream=True)
    except FetchError as e:
        raise e.__class__(f"{url}: {e}", status=e.status, url=e.url) from e
    with r:
        data = bytearray()
        try:
            for chunk in r.iter_content(64 * 1024):
                data += chunk
                if len(data) > max_bytes:
                    raise FetchError(f"{url}: more than {max_bytes // 1024 // 1024} MB; not a puzzle", url=url)
        except requests.RequestException as e:
            raise FetchError(f"{url}: {e.__class__.__name__}: {e}", url=url) from e
        if not data:
            raise NotFound(f"{url}: empty response", status=r.status_code, url=url)
        return Download(r.url, bytes(data), filename_for(r.url, r.headers.get("Content-Disposition", "")))


def filename_for(url: str, disposition: str = "") -> str:
    """The name the site gave the file, else the last part of the URL's path. Never a path."""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disposition, re.IGNORECASE)
    name = unquote(m.group(1)) if m else unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name not in ("", ".", "..") else "puzzle"
