"""The nyt adapter against a mocked feed. The payload is made up, in the feed's shape."""

import datetime as dt
import json

import pytest
import responses

from xdfetch.adapters import nyt as adapter
from xdfetch.http import FetchError, NotFound

DAY = dt.date(2026, 10, 28)
URL = "https://www.nytimes.com/svc/crosswords/v6/puzzle/daily/2026-10-28.json"


def payload(date="2026-10-28") -> dict:
    cells = [{"answer": c, "type": 1} if c != "#" else {} for c in "CATA#OBOW"]
    return {
        "publicationDate": date,
        "title": "",
        "constructors": ["A. Setter"],
        "body": [{"cells": cells, "dimensions": {"width": 3, "height": 3}, "clues": []}],
    }


RAW = json.dumps(payload()).encode()


@responses.activate
def test_fetch_sends_cookie_and_checks_date(registry, http):
    responses.add(responses.GET, URL, body=RAW)
    a = adapter.NytAdapter(registry["nyt"], http, secrets={"NYT_S": "session-cookie"})
    (t,) = a.targets(DAY)
    assert t.url == URL
    assert t.filename == "nyt-2026-10-28.json"
    got = a.fetch(t)
    assert got.data == RAW
    assert "NYT-S=session-cookie" in str(responses.calls[0].request.headers["Cookie"])


@responses.activate
def test_secret_missing_is_a_warning(registry, http, caplog):
    responses.add(responses.GET, URL, body=RAW)
    a = adapter.NytAdapter(registry["nyt"], http, secrets={})
    a.fetch(a.targets(DAY)[0])
    assert "Cookie" not in responses.calls[0].request.headers
    assert "NYT_S is not set" in caplog.text


@responses.activate
def test_wrong_date_is_not_found(registry, http):
    responses.add(responses.GET, URL, json=payload("2026-10-27"))
    a = adapter.NytAdapter(registry["nyt"], http, secrets={"NYT_S": "x"})
    with pytest.raises(NotFound, match="dated 2026-10-27"):
        a.fetch(a.targets(DAY)[0])


@responses.activate
def test_no_answers_is_an_error(registry, http):
    body = payload()
    for c in body["body"][0]["cells"]:
        c.pop("answer", None)
    responses.add(responses.GET, URL, json=body)
    a = adapter.NytAdapter(registry["nyt"], http, secrets={"NYT_S": "x"})
    with pytest.raises(FetchError, match="no answers"):
        a.fetch(a.targets(DAY)[0])


@responses.activate
def test_no_body_is_not_found(registry, http):
    responses.add(responses.GET, URL, json={"status": "ERROR"})
    a = adapter.NytAdapter(registry["nyt"], http, secrets={})
    with pytest.raises(NotFound, match="no puzzle body"):
        a.fetch(a.targets(DAY)[0])


def test_mini_url(registry, http):
    a = adapter.NytAdapter(registry["nytmini"], http, secrets={"NYT_S": "x"})
    (t,) = a.targets(DAY)
    assert t.url == "https://www.nytimes.com/svc/crosswords/v6/puzzle/mini/2026-10-28.json"
    assert t.filename == "nytmini-2026-10-28.json"


def test_registry_rows(registry):
    assert registry["nyt"].adapter == "nyt"
    assert registry["nyt"].auth == "NYT_S"
    assert registry["nytmini"].param("kind") == "mini"
    assert registry["nytmidi"].param("kind") == "midi"
