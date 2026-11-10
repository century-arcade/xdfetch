"""Downloading, politely: our own User-Agent, a timeout, retries with backoff."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import USER_AGENT

TIMEOUT = 30  # seconds
MAX_BYTES = 20 * 1024 * 1024  # no puzzle file is anywhere near this


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class Download:
    url: str  # where the bytes finally came from, after redirects
    data: bytes  # as served
    filename: str  # the name the site gave it, or the last part of the URL


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods={"GET"},
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def download(url: str, s: requests.Session | None = None) -> Download:
    s = s or session()
    try:
        with s.get(url, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            data = b""
            for chunk in r.iter_content(64 * 1024):
                data += chunk
                if len(data) > MAX_BYTES:
                    raise DownloadError(f"{url}: more than {MAX_BYTES // 1024 // 1024} MB; not a puzzle")
            return Download(r.url, data, filename_for(r.url, r.headers.get("Content-Disposition", "")))
    except requests.RequestException as e:
        raise DownloadError(str(e)) from e


def filename_for(url: str, disposition: str = "") -> str:
    """The name the site gave the file, else the last part of the URL's path."""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disposition, re.IGNORECASE)
    name = unquote(m.group(1)) if m else unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()  # never a path
    return name if name not in ("", ".", "..") else "puzzle"
