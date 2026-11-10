"""The conde adapter against a mocked page and service. The payload is made up."""

import datetime as dt
import json

import pytest
import responses

from xdfetch.adapters import Target
from xdfetch.adapters import conde as adapter
from xdfetch.http import FetchError, NotFound

ID = "00000000-1111-4222-8333-444444444444"
RAW = json.dumps(
    {
        "id": ID,
        "data": "## Metadata\n\ntitle: Tiny\nauthor: A. Setter\n\n## Grid\n\nCAT\nA#O\nBOW\n\n"
        "## Clues\n\nA1. Café pet ~ CAT\nA3. Ribbon knot ~ BOW\n\nD1. Taxi ~ CAB\nD2. Pull a barge ~ TOW\n",
    },
    ensure_ascii=False,
).encode("utf-8")
PAGE = "https://www.newyorker.com/puzzles-and-games-dept/crossword/2026/10/28"
API = adapter.DEFAULT_API + ID
DAY = dt.date(2026, 10, 28)


@responses.activate
def test_fetch_reads_id_from_page(registry, http):
    responses.add(responses.GET, PAGE, body=f'<html><script>{{"id":"{ID}"}}</script></html>')
    responses.add(responses.GET, API, body=RAW)
    a = adapter.CondeAdapter(registry["tny"], http)
    (t,) = a.targets(DAY)
    assert t.url == API
    assert t.filename == "tny-2026-10-28.json"
    assert PAGE in t.note
    assert a.fetch(t).data == RAW


@responses.activate
def test_missing_page_and_bad_page(registry, http):
    responses.add(responses.GET, PAGE, status=404)
    a = adapter.CondeAdapter(registry["tny"], http)
    with pytest.raises(NotFound):
        a.targets(DAY)
    responses.replace(responses.GET, PAGE, body="<html>no puzzle here</html>")
    with pytest.raises(FetchError, match="no puzzle id"):
        a.targets(DAY)


@responses.activate
def test_record_without_data_is_not_found(registry, http):
    responses.add(responses.GET, API, json={"id": ID, "error": "gone"})
    a = adapter.CondeAdapter(registry["tny"], http)
    with pytest.raises(NotFound):
        a.fetch(Target(url=API, filename="tny-2026-10-28.json"))


def test_mini_page_template(registry):
    assert "mini-crossword/%Y/%m/%d" in registry["tnymini"].param("page")
