"""The `page` adapter: a dated page that links the puzzle file."""

import datetime as dt

import pytest
import responses
from conftest import make_puz

from xdfetch.adapters import page
from xdfetch.http import NotFound

PUZ = make_puz()
DAY = dt.date(2026, 11, 5)
POST = "https://brendanemmettquigley.com/2026/11/05/"
FILES = "https://brendanemmettquigley.com/files/"

POST_HTML = f"""<html><body>
<h2><a href="https://brendanemmettquigley.com/2026/11/05/crossword-9999-tiny-test/">CROSSWORD #9999</a></h2>
<a href="/files/9999TinyTest.puz">Across Lite</a> <a href="/files/9999TinyTest.pdf">PDF</a>
<a href="/solve/?file=/files/9999TinyTest.puz">Solve online</a>
<a href='{FILES}9999TinyTest.puz'>again</a> <a href="https://example.com/x.puz">elsewhere</a>
</body></html>"""


@responses.activate
def test_post_links_the_puz(registry, http):
    responses.add(responses.GET, POST, body=POST_HTML)
    responses.add(responses.GET, f"{FILES}9999TinyTest.puz", body=PUZ)
    a = page.PageAdapter(registry["brendanemmettquigley.blog"], http)
    (t,) = a.targets(DAY)  # the relative and absolute links are one file; the player and PDF are not
    assert t.url == f"{FILES}9999TinyTest.puz"
    assert t.filename == "9999TinyTest.puz"
    assert POST in t.note
    assert a.fetch(t).data == PUZ


@responses.activate
def test_no_post_or_no_link_is_a_miss(registry, http):
    responses.add(responses.GET, POST, status=404)
    with pytest.raises(NotFound):
        page.PageAdapter(registry["brendanemmettquigley.blog"], http).targets(DAY)
    responses.replace(responses.GET, POST, body="<a href='/files/Oct3126.pdf'>pdf</a>")
    with pytest.raises(NotFound):
        page.PageAdapter(registry["brendanemmettquigley.blog"], http).targets(DAY)


def test_number_param(registry):
    assert registry["brendanemmettquigley.blog"].params["number"] == r"(\d{4})"
