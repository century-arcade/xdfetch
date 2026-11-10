"""The `url` adapter: a URL template with strftime fields. Most outlets that serve a
file at a predictable address are a registry row on this adapter, not code.

params:
  url       the template, e.g. https://picayune.uclick.com/comics/fcx/data/fcx%y%m%d-data.xml
  filename  optional: name to keep the file under, also strftime; default is the URL's last path segment
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlsplit

from .base import Adapter, Target


class UrlAdapter(Adapter):
    name = "url"

    def targets(self, date: dt.date) -> list[Target]:
        template = self.outlet.param("url")
        url = date.strftime(template)
        fn_template = self.outlet.params.get("filename")
        if fn_template:
            filename = date.strftime(fn_template)
        else:
            filename = urlsplit(url).path.rsplit("/", 1)[-1] or f"{self.outlet.id}{date.isoformat()}"
        return [Target(url=url, filename=filename)]

    def describe(self) -> str:
        template = self.outlet.param("url")
        text = (
            f"Each file is fetched from `{template}` (strftime fields filled with the puzzle's date), saved as served."
        )
        if self.outlet.notes:
            text += " " + self.outlet.notes
        return text
