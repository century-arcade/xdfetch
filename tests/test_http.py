import pytest
import responses

from xdfetch import USER_AGENT
from xdfetch.http import MAX_BYTES, DownloadError, download, filename_for


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
    with pytest.raises(DownloadError, match="404"):
        download("https://example.com/gone.puz")


@responses.activate
def test_download_too_big():
    responses.get("https://example.com/huge", body=b"x" * (MAX_BYTES + 1))
    with pytest.raises(DownloadError, match="not a puzzle"):
        download("https://example.com/huge")
