"""What an adapter is.

An adapter knows one transport: where a day's file is and how to get it. It returns the
bytes as the outlet served them. It does not parse puzzle content beyond what finding
the file needs (a date picker, a listing, an id), and it never writes a .puz unless the
outlet served a .puz. Converting to .xd is a separate step; adapters never import a
converter.

To add a transport: subclass Adapter, set `name`, implement `targets()` and, if the
default GET isn't enough, `fetch()`. A built-in adapter is listed in adapters/__init__.py;
one from another package is registered under the `xdfetch.adapters` entry-point group
(see adapters/__init__.py).
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from ..http import Http, iso_http_date
from ..registry import Outlet


@dataclass
class Target:
    """One file to fetch for one (id, date)."""

    url: str
    filename: str  # name to keep it under (the source's own name where possible)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    note: str = ""  # anything worth recording about this target (the page the id came from, say)
    companion: bool = False  # a file kept beside the puzzle, not a puzzle itself
    data: bytes | None = None  # bytes already in hand; fetch() returns them without a request


@dataclass
class Fetched:
    """What came back: the bytes as served, and where they really came from."""

    data: bytes
    url: str  # the final URL, after redirects
    content_type: str = ""
    filename: str = ""
    modified: str = ""  # the server's Last-Modified as ISO 8601 UTC, where it sends one (static feeds do)


class Adapter:
    name = ""
    # seconds between requests to this adapter's host; None = Http default
    interval: float | None = None

    def __init__(self, outlet: Outlet, http: Http, secrets: dict[str, str] | None = None):
        self.outlet = outlet
        self.http = http
        self.secrets = secrets if secrets is not None else dict(os.environ)

    def secret(self) -> str:
        """The outlet's secret (the registry's `auth` names the environment variable)."""
        name = self.outlet.auth
        if not name:
            return ""
        value = self.secrets.get(name, "")
        if not value:
            raise RuntimeError(f"{self.outlet.id}: secret {name} is not set")
        return value

    def targets(self, date: dt.date) -> list[Target]:
        """The file(s) to fetch for this date. Usually one."""
        raise NotImplementedError

    def fetch(self, target: Target) -> Fetched:
        """GET the target. Adapters override this when the bytes need unwrapping
        or more than one request. A target with its bytes already in hand is returned as is."""
        if target.data is not None:
            return Fetched(data=target.data, url=target.url, filename=target.filename)
        r = self.http.get(
            target.url, headers=target.headers or None, cookies=target.cookies or None, interval=self.interval
        )
        return Fetched(
            data=r.content,
            url=r.url,
            content_type=r.headers.get("Content-Type", ""),
            filename=target.filename,
            modified=iso_http_date(r.headers.get("Last-Modified")),
        )

    def describe(self) -> str:
        """One paragraph for a human: what the files are and how they're named."""
        return self.outlet.notes
