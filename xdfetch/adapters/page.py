"""The `page` adapter: a dated page (a blog's post or day archive) that links the puzzle file.

params:
  page   strftime template for the page that lists the day's puzzle, e.g. a WordPress day
         archive https://example.com/%Y/%m/%d/
  link   regex that must match a whole href on the page; each distinct match (resolved against
         the page's URL) is one file to fetch. E.g. [^"']*\\.puz for the post's .puz.

A page that 404s, or has no matching link, is a miss for the date (no puzzle that day), not
an error. Files are kept under the name the outlet serves them by (the URL's last segment).
"""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import unquote, urljoin, urlsplit

from ..http import NotFound
from .base import Adapter, Target

HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


class PageAdapter(Adapter):
    name = "page"
    interval = 2.0

    def targets(self, date: dt.date) -> list[Target]:
        page = date.strftime(self.outlet.param("page"))
        link = re.compile(self.outlet.param("link"))
        r = self.http.get(page, interval=self.interval)
        urls: list[str] = []
        for href in HREF.findall(r.text):
            if link.fullmatch(href):
                url = urljoin(r.url or page, href)
                if url not in urls:
                    urls.append(url)
        if not urls:
            raise NotFound("the page links no puzzle file", url=page)
        return [
            Target(url=u, filename=unquote(urlsplit(u).path.rsplit("/", 1)[-1]), note=f"Linked from {page}.")
            for u in urls
        ]

    def describe(self) -> str:
        text = (
            f"Each file is the puzzle linked from the page for its date (`{self.outlet.param('page')}`), "
            f"fetched from the link and saved as served, under the outlet's own file name."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
