import pytest
import responses

from xdfetch import USER_AGENT
from xdfetch.http import MAX_BYTES, DownloadError, FetchError, Http, NotFound, download, filename_for, iso_http_date


@pytest.mark.parametrize(
    ("url", "disposition", "expected"),
    [
        ("https://example.com/puzzles/tiny.puz", "", "tiny.puz"),
        ("https://example.com/get?id=7", 'attachment; filename="tiny.ipuz"', "tiny.ipuz"),
        ("https://example.com/get", "attachment; filename*=UTF-8''caf%C3%A9.puz", "café.puz"),
        ("https://example.com/get", 'attachment; filename="../../etc/evil.puz"', "evil.puz"),
        ("https://example.com/get", 'attachment; filename="..\\..\\evil.puz"', "evil.puz"),
        ("https://example.com/", "", "puzzle"),
        ("https://example.com/a%20b.puz", "", "a b.puz"),
    ],
)
def test_filename_for(url, disposition, expected):
    assert filename_for(url, disposition) == expected


@responses.activate
def test_download_sends_our_user_agent():
    responses.get("https://example.com/tiny.puz", body=b"bytes")
    got = download("https://example.com/tiny.puz")
    assert got.data == b"bytes"
    assert got.filename == "tiny.puz"
    assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT


@responses.activate
def test_download_follows_redirects():
    responses.get("https://example.com/today", status=302, headers={"Location": "https://cdn.example.com/x.puz"})
    responses.get("https://cdn.example.com/x.puz", body=b"bytes")
    got = download("https://example.com/today")
    assert (got.url, got.filename) == ("https://cdn.example.com/x.puz", "x.puz")


@responses.activate
def test_download_not_found():
    responses.get("https://example.com/gone.puz", status=404)
    with pytest.raises(DownloadError, match="404") as e:
        download("https://example.com/gone.puz")
    assert isinstance(e.value, NotFound)
    assert "https://example.com/gone.puz" in str(e.value)


@responses.activate
def test_download_too_big():
    responses.get("https://example.com/huge", body=b"x" * (MAX_BYTES + 1))
    with pytest.raises(DownloadError, match="not a puzzle"):
        download("https://example.com/huge")


@responses.activate
def test_download_uses_the_given_client():
    responses.get("https://example.com/tiny.puz", body=b"bytes")
    download("https://example.com/tiny.puz", Http(interval=0, user_agent="other-tool/1.0"))
    assert responses.calls[0].request.headers["User-Agent"] == "other-tool/1.0"


# --- Http ---


@responses.activate
def test_user_agent_and_rate_limit():
    responses.add(responses.GET, "https://example.test/a", body=b"x")
    responses.add(responses.GET, "https://example.test/b", body=b"y")
    slept = []
    clock = [100.0]
    h = Http(interval=2.0, sleep=slept.append, clock=lambda: clock[0])
    h.get("https://example.test/a")
    h.get("https://example.test/b")  # same host, no time passed: must wait the interval
    assert slept == [2.0]
    assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT
    assert USER_AGENT.startswith("xdfetch/")


@responses.activate
def test_rate_limit_is_per_host():
    responses.add(responses.GET, "https://one.test/a", body=b"x")
    responses.add(responses.GET, "https://two.test/a", body=b"y")
    slept = []
    h = Http(interval=2.0, sleep=slept.append, clock=lambda: 100.0)
    h.get("https://one.test/a")
    h.get("https://two.test/a")
    assert slept == []
    assert h.requests_made == 2


@responses.activate
def test_user_agent_is_a_parameter():
    responses.add(responses.GET, "https://example.test/a", body=b"x")
    Http(interval=0, user_agent="other-tool/1.0 (+https://example.org)").get("https://example.test/a")
    assert responses.calls[0].request.headers["User-Agent"] == "other-tool/1.0 (+https://example.org)"


@responses.activate
def test_404_is_not_found(http):
    responses.add(responses.GET, "https://example.test/missing", status=404)
    with pytest.raises(NotFound):
        http.get("https://example.test/missing")


@responses.activate
def test_empty_body_is_not_found(http):
    responses.add(responses.GET, "https://example.test/empty", body=b"", status=200)
    with pytest.raises(NotFound):
        http.get("https://example.test/empty")
    assert http.get("https://example.test/empty", allow_empty=True).content == b""


@responses.activate
def test_retries_then_succeeds(http):
    responses.add(responses.GET, "https://example.test/flaky", status=503)
    responses.add(responses.GET, "https://example.test/flaky", body=b"ok")
    assert http.get("https://example.test/flaky").content == b"ok"


@responses.activate
def test_backoff_honours_retry_after():
    responses.add(responses.GET, "https://example.test/busy", status=429, headers={"Retry-After": "30"})
    responses.add(responses.GET, "https://example.test/busy", body=b"ok")
    slept = []
    Http(interval=0, sleep=slept.append).get("https://example.test/busy")
    assert slept == [30.0]


@responses.activate
def test_gives_up(http):
    for _ in range(5):
        responses.add(responses.GET, "https://example.test/down", status=503)
    with pytest.raises(FetchError) as e:
        http.get("https://example.test/down")
    assert e.value.status == 503
    assert len(responses.calls) == 3  # the first try and two retries


@responses.activate
def test_forbidden_is_error(http):
    responses.add(responses.GET, "https://example.test/blocked", status=403)
    with pytest.raises(FetchError) as e:
        http.get("https://example.test/blocked")
    assert not isinstance(e.value, NotFound)


def test_iso_http_date():
    assert iso_http_date("Wed, 28 Oct 2026 07:30:00 GMT") == "2026-10-28T07:30:00Z"
    assert iso_http_date("Wed, 28 Oct 2026 03:30:00 -0400") == "2026-10-28T07:30:00Z"
    assert iso_http_date("") == iso_http_date(None) == iso_http_date("not a date") == ""
