import pytest
import responses

from xdfetch import __version__
from xdfetch.cli import FAILED, OK, USAGE, main

URL = "https://example.com/puzzles/tiny.puz"


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_convert(in_tmp, puz_bytes, ipuz_bytes):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    (in_tmp / "b.ipuz").write_bytes(ipuz_bytes)
    assert main(["convert", "a.puz", "b.ipuz"]) == OK
    for name in ("a.xd", "b.xd"):
        xd = (in_tmp / name).read_text(encoding="utf-8")
        assert "A1. Café pet ~ CAT" in xd


def test_convert_writes_lf_utf8(in_tmp, puz_bytes):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    main(["convert", "a.puz"])
    raw = (in_tmp / "a.xd").read_bytes()
    assert b"\r\n" not in raw
    assert "Café".encode() in raw


def test_convert_to_stdout(in_tmp, puz_bytes, capsys):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    assert main(["convert", "a.puz", "-o", "-"]) == OK
    assert "Title: Tiny" in capsys.readouterr().out
    assert not (in_tmp / "a.xd").exists()


def test_convert_into_directory(in_tmp, puz_bytes):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    (in_tmp / "out").mkdir()
    assert main(["convert", "a.puz", "-o", "out"]) == OK
    assert (in_tmp / "out" / "a.xd").exists()


def test_convert_several_to_one_file_is_usage_error(in_tmp, puz_bytes):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    assert main(["convert", "a.puz", "a.puz", "-o", "x.xd"]) == USAGE


def test_convert_keeps_existing_without_force(in_tmp, puz_bytes):
    (in_tmp / "a.puz").write_bytes(puz_bytes)
    (in_tmp / "a.xd").write_text("mine")
    assert main(["convert", "a.puz"]) == FAILED
    assert (in_tmp / "a.xd").read_text() == "mine"
    assert main(["convert", "a.puz", "--force"]) == OK
    assert "Title: Tiny" in (in_tmp / "a.xd").read_text(encoding="utf-8")


def test_convert_carries_on_after_a_bad_file(in_tmp, puz_bytes):
    (in_tmp / "bad.puz").write_bytes(b"<html>nope</html>")
    (in_tmp / "good.puz").write_bytes(puz_bytes)
    assert main(["convert", "bad.puz", "good.puz"]) == FAILED
    assert (in_tmp / "good.xd").exists()


def test_convert_missing_file():
    assert main(["convert", "nope.puz"]) == FAILED


@responses.activate
def test_get_url(in_tmp, puz_bytes):
    responses.get(URL, body=puz_bytes)
    assert main(["get", URL]) == OK
    assert "A1. Café pet ~ CAT" in (in_tmp / "tiny.xd").read_text(encoding="utf-8")
    assert not (in_tmp / "tiny.puz").exists()


@responses.activate
def test_get_raw_keeps_the_file_as_served(in_tmp, puz_bytes):
    responses.get(URL, body=puz_bytes)
    assert main(["get", URL, "--raw"]) == OK
    assert (in_tmp / "tiny.puz").read_bytes() == puz_bytes
    assert (in_tmp / "tiny.xd").exists()


@responses.activate
def test_get_not_a_puzzle(in_tmp):
    responses.get(URL, body=b"<html>Please log in</html>")
    assert main(["get", URL]) == FAILED
    assert not (in_tmp / "tiny.xd").exists()


@responses.activate
def test_get_http_error():
    responses.get(URL, status=403)
    assert main(["get", URL]) == FAILED


def test_get_name_is_not_supported_yet():
    assert main(["get", "nyt"]) == USAGE
