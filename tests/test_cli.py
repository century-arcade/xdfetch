import datetime as dt
import zipfile

import pytest
import responses
from conftest import ENGINE_REGISTRY, RAW
from responses import matchers

from xdfetch import __version__, adapters
from xdfetch import registry as reg
from xdfetch.adapters import Adapter, Target
from xdfetch.cli import FAILED, NOT_FOUND, OK, USAGE, latest_date, main

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
def test_get_both_keeps_the_file_as_served(in_tmp, puz_bytes):
    responses.get(URL, body=puz_bytes)
    assert main(["get", URL, "--format", "both"]) == OK
    assert (in_tmp / "tiny.puz").read_bytes() == puz_bytes
    assert (in_tmp / "tiny.xd").exists()


@responses.activate
def test_get_both_with_a_named_output(in_tmp, puz_bytes):
    responses.get(URL, body=puz_bytes)
    (in_tmp / "out").mkdir()
    assert main(["get", URL, "--format", "both", "-o", "out/mine.xd"]) == OK
    assert "Title: Tiny" in (in_tmp / "out" / "mine.xd").read_text(encoding="utf-8")
    assert (in_tmp / "out" / "tiny.puz").read_bytes() == puz_bytes


@responses.activate
def test_get_raw_writes_only_the_file_as_served(in_tmp, puz_bytes):
    responses.get(URL, body=puz_bytes)
    assert main(["get", URL, "--format", "raw"]) == OK
    assert (in_tmp / "tiny.puz").read_bytes() == puz_bytes
    assert not (in_tmp / "tiny.xd").exists()


@responses.activate
def test_get_raw_does_not_need_a_known_format(in_tmp):
    responses.get("https://example.com/today.json", body=b'{"some": "site format"}')
    assert main(["get", "https://example.com/today.json", "--format", "raw", "-o", "saved.json"]) == OK
    assert (in_tmp / "saved.json").read_bytes() == b'{"some": "site format"}'


@responses.activate
def test_get_raw_to_stdout(in_tmp, puz_bytes, capsysbinary):
    responses.get(URL, body=puz_bytes)
    assert main(["get", URL, "--format", "raw", "-o", "-"]) == OK
    assert capsysbinary.readouterr().out == puz_bytes
    assert not (in_tmp / "tiny.puz").exists()


@responses.activate
def test_get_both_writes_nothing_when_conversion_fails(in_tmp):
    responses.get(URL, body=b"<html>Please log in</html>")
    assert main(["get", URL, "--format", "both"]) == FAILED
    assert list(in_tmp.iterdir()) == []


@responses.activate
def test_get_not_a_puzzle(in_tmp):
    responses.get(URL, body=b"<html>Please log in</html>")
    assert main(["get", URL]) == FAILED
    assert not (in_tmp / "tiny.xd").exists()


@responses.activate
def test_get_http_error():
    responses.get(URL, status=403)
    assert main(["get", URL]) == FAILED


def test_get_something_neither_url_nor_id(capsys):
    assert main(["get", "nyt"]) == USAGE
    assert "neither a URL nor an outlet id" in capsys.readouterr().err


def test_convert_names_the_format_of_a_broken_file(in_tmp, puz_bytes, capsys):
    (in_tmp / "broken.puz").write_bytes(puz_bytes[:60])
    (in_tmp / "broken.json").write_bytes(b'{"publicationDate": "2026-10-28", "cells": [], "body": [{}]}')
    assert main(["convert", "broken.puz", "broken.json"]) == FAILED
    err = capsys.readouterr().err
    assert "broken.puz: not a valid puz file (" in err
    assert "broken.json: not a valid nytjson file (KeyError: 'dimensions')" in err


# --- outlets: list and get ID --------------------------------------------------------------

OVERLAY = (
    "id\tadapter\tparams\tdays\tsince\ttz\tavailable_after\thomepage\tauth\tenabled\n"
    "example.tiny\turl\turl=https://example.com/puzzles/tiny%y%m%d.puz\tdaily\t\tAmerica/New_York\t0\t"
    "https://example.com/tiny/\t\tyes\n"
    "example.wed\turl\turl=https://example.com/wed/%Y%m%d.puz\twed\t2026-01-07\tAmerica/New_York\t0\t\t\tyes\n"
    "example.secret\tsecretive\t\tdaily\t\tAmerica/New_York\t0\t\tEXAMPLE_TOKEN\tyes\n"
)
TINY = "https://example.com/puzzles/tiny261028.puz"


@pytest.fixture
def overlay(in_tmp):
    (in_tmp / "mine.tsv").write_text(OVERLAY, encoding="utf-8")
    return "mine.tsv"


def test_list_shows_the_builtin_outlets(capsys):
    assert main(["list"]) == OK
    lines = capsys.readouterr().out.splitlines()
    nyt = next(line for line in lines if line.startswith("nytimes.daily "))
    assert nyt.split() == ["nytimes.daily", "daily", "https://www.nytimes.com/crosswords"]
    assert any(line.split()[:2] == ["newyorker.daily", "mon,tue,wed"] for line in lines)


def test_list_with_registry_overlays(in_tmp, overlay, capsys):
    (in_tmp / "second.tsv").write_text(
        "id\tadapter\tdays\thomepage\tenabled\nnytimes.daily\turl\tsun\thttps://example.com/replaced/\tno\n",
        encoding="utf-8",
    )
    assert main(["list", "--registry", overlay, "--registry", "second.tsv"]) == OK
    lines = capsys.readouterr().out.splitlines()
    assert next(x for x in lines if x.startswith("example.tiny ")).split() == [
        "example.tiny",
        "daily",
        "https://example.com/tiny/",
    ]
    assert next(x for x in lines if x.startswith("example.wed ")).split() == ["example.wed", "wed"]
    assert next(x for x in lines if x.startswith("nytimes.daily ")).split() == [
        "nytimes.daily",
        "sun",
        "https://example.com/replaced/",
        "(disabled)",
    ]


def test_registry_file_that_is_missing_is_a_usage_error(capsys):
    assert main(["list", "--registry", "nope.tsv"]) == USAGE
    assert "nope.tsv" in capsys.readouterr().err


@responses.activate
def test_get_id_for_a_date(in_tmp, overlay, puz_bytes):
    responses.get(TINY, body=puz_bytes)
    assert main(["get", "example.tiny", "--date", "2026-10-28", "--registry", overlay]) == OK
    xd = (in_tmp / "example.tiny-2026-10-28.xd").read_text(encoding="utf-8")
    assert "A1. Café pet ~ CAT" in xd
    assert "Date: 2026-10-28" in xd
    assert not (in_tmp / "tiny261028.puz").exists()


@responses.activate
def test_get_id_formats_and_output(in_tmp, overlay, puz_bytes, capsys):
    responses.get(TINY, body=puz_bytes)
    args = ["get", "example.tiny", "--date", "2026-10-28", "--registry", overlay]
    assert main([*args, "--format", "both"]) == OK
    assert (in_tmp / "tiny261028.puz").read_bytes() == puz_bytes
    assert (in_tmp / "example.tiny-2026-10-28.xd").exists()
    assert main(args) == FAILED  # exists
    assert main([*args, "--force"]) == OK
    (in_tmp / "out").mkdir()
    assert main([*args, "--format", "raw", "-o", "out"]) == OK
    assert (in_tmp / "out" / "tiny261028.puz").read_bytes() == puz_bytes
    capsys.readouterr()
    assert main([*args, "-o", "-"]) == OK
    assert "Title: Tiny" in capsys.readouterr().out


@responses.activate
def test_get_id_defaults_to_the_latest_date(in_tmp, overlay, puz_bytes, monkeypatch):
    monkeypatch.setattr(reg.Outlet, "latest_available", lambda self, now=None: dt.date(2026, 10, 28))
    responses.get(TINY, body=puz_bytes)
    assert main(["get", "example.tiny", "--registry", overlay]) == OK
    assert (in_tmp / "example.tiny-2026-10-28.xd").exists()


def test_latest_date_follows_the_calendar(overlay):
    outlet = reg.effective([overlay])["example.wed"]
    thursday = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
    assert latest_date(outlet, thursday) == dt.date(2026, 10, 28)
    assert latest_date(outlet, dt.datetime(2026, 1, 6, 12, 0, tzinfo=dt.UTC)) is None  # before `since`


@responses.activate
def test_get_id_when_the_outlet_has_nothing_exits_3(in_tmp, overlay, capsys):
    responses.get(TINY, status=404)
    assert main(["get", "example.tiny", "--date", "2026-10-28", "--registry", overlay]) == NOT_FOUND == 3
    assert "example.tiny has no puzzle for 2026-10-28: HTTP 404" in capsys.readouterr().err
    assert list(in_tmp.iterdir()) == [in_tmp / "mine.tsv"]


def test_get_id_on_a_day_it_doesnt_run_exits_3_without_asking(overlay, capsys):
    with responses.RequestsMock():  # any request would fail the test
        assert main(["get", "example.wed", "--date", "2026-10-29", "--registry", overlay]) == NOT_FOUND
    assert "example.wed has no puzzle on 2026-10-29 (runs wed, since 2026-01-07)" in capsys.readouterr().err


@responses.activate
def test_get_id_other_failures_exit_1(overlay):
    responses.get(TINY, status=403)
    assert main(["get", "example.tiny", "--date", "2026-10-28", "--registry", overlay]) == FAILED
    responses.replace(responses.GET, TINY, body=b"<html>Please log in</html>")
    assert main(["get", "example.tiny", "--date", "2026-10-28", "--registry", overlay]) == FAILED


class SecretiveAdapter(Adapter):
    name = "secretive"

    def targets(self, date):
        return [Target(url="https://example.com/s.puz", filename="s.puz", headers={"X-Token": self.secret()})]


def test_get_id_with_its_secret_unset_names_the_variable(overlay, plugins, monkeypatch, capsys):
    plugins(adapters.ENTRY_POINT_GROUP, "secretive", SecretiveAdapter)
    monkeypatch.delenv("EXAMPLE_TOKEN", raising=False)
    assert main(["get", "example.secret", "--date", "2026-10-28", "--registry", overlay]) == FAILED
    err = capsys.readouterr().err
    assert "example.secret needs a secret: set the environment variable EXAMPLE_TOKEN" in err


@responses.activate
def test_get_id_with_its_secret_set(in_tmp, overlay, plugins, monkeypatch, puz_bytes):
    plugins(adapters.ENTRY_POINT_GROUP, "secretive", SecretiveAdapter)
    monkeypatch.setenv("EXAMPLE_TOKEN", "t0ken")
    responses.get("https://example.com/s.puz", body=puz_bytes, match=[matchers.header_matcher({"X-Token": "t0ken"})])
    assert main(["get", "example.secret", "--date", "2026-10-28", "--registry", overlay]) == OK
    assert (in_tmp / "example.secret-2026-10-28.xd").exists()


def test_get_usage_errors(overlay):
    assert main(["get", "no.such", "--registry", overlay]) == USAGE
    assert main(["get", URL, "--date", "2026-10-28"]) == USAGE
    assert main(["get", "example.tiny", "--date", "28 Oct", "--registry", overlay]) == USAGE


# --- the archive's commands ------------------------------------------------------------------

DAILY = "https://example.com/feed/ex261028.xml"


@pytest.fixture
def engine(in_tmp):
    (in_tmp / "engine.tsv").write_text(ENGINE_REGISTRY, encoding="utf-8")
    return ["--store", "store", "--registry", "engine.tsv"]


def test_plan(engine, capsys):
    assert main(["plan", *engine, "--date", "2026-10-28", "--id", "example.daily", "example.late"]) == OK
    out = capsys.readouterr()
    assert out.out == "example.daily\t2026-10-28\tnew\nexample.late\t2026-10-28\tnew\n"
    assert "2 to fetch" in out.err


@responses.activate
def test_run_status_availability_verify(in_tmp, engine, capsys):
    responses.get(DAILY, body=RAW)
    assert main(["run", *engine, "--date", "2026-10-28", "--id", "example.daily", "--interval", "0"]) == OK
    assert capsys.readouterr().out.startswith("# xdfetch run: ")
    (zipname,) = (in_tmp / "store" / "downloads").rglob("*.zip")
    ledger = (in_tmp / "store" / "ledger.tsv").read_text(encoding="utf-8")
    assert ledger.splitlines()[1].startswith("example.daily\t2026-10-28\texample.daily/ex261028.xml\t")

    assert main(["plan", *engine, "--date", "2026-10-28", "--id", "example.daily", "--no-refetch"]) == OK
    assert capsys.readouterr().out == ""

    assert main(["status", *engine]) == OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "id\tenabled\tlast file\tfiles\tmissing\terrors\tmisses in a row"
    assert any(x.startswith("example.daily\tyes\t2026-10-28\t1\t0\t0\t") for x in lines)
    assert any(x.startswith("nytimes.daily\tyes\t\t0\t") for x in lines)  # the built-in rows are there too

    assert main(["availability", *engine]) == OK
    assert "\nexample.daily\t3\t1\t" in capsys.readouterr().out

    assert main(["verify", str(zipname)]) == OK
    assert capsys.readouterr().out == f"{zipname}: ok\n"


@responses.activate
def test_run_with_errors_exits_1_and_writes_the_summary(in_tmp, engine):
    responses.get(DAILY, status=403)
    args = ["run", *engine, "--date", "2026-10-28", "--id", "example.daily", "--interval", "0", "--summary", "s.md"]
    assert main(args) == FAILED
    assert "HTTP 403" in (in_tmp / "s.md").read_text(encoding="utf-8")


def test_run_dry_run_fetches_nothing(in_tmp, engine, capsys):
    with responses.RequestsMock():
        assert main(["run", *engine, "--date", "2026-10-28", "--id", "example.daily", "--dry-run"]) == OK
    assert "1 skipped" in capsys.readouterr().out
    assert not (in_tmp / "store").exists()


def test_store_from_the_environment(in_tmp, engine, monkeypatch, capsys):
    monkeypatch.setenv("XDFETCH_STORE", str(in_tmp / "elsewhere"))
    assert main(["status", "--registry", "engine.tsv"]) == OK
    monkeypatch.delenv("XDFETCH_STORE")
    capsys.readouterr()
    assert main(["status", "--registry", "engine.tsv"]) == USAGE
    assert "--store" in capsys.readouterr().err


def test_unknown_id_is_a_usage_error(engine, capsys):
    assert main(["plan", *engine, "--date", "2026-10-28", "--id", "no.such"]) == USAGE
    assert "not in the registry: no.such" in capsys.readouterr().err


def test_verify_reports_problems(in_tmp, capsys):
    with zipfile.ZipFile(in_tmp / "bad.zip", "w") as z:
        z.writestr("MANIFEST.tsv", "filename\tsha256\tbytes\tsource_url\tfetched_at\nx/a\t00\t1\t\t\n")
    (in_tmp / "notzip.zip").write_bytes(b"nope")
    assert main(["verify", "bad.zip", "notzip.zip", "missing.zip"]) == FAILED
    out = capsys.readouterr().out
    assert "bad.zip: x/a: in manifest, not in archive" in out
    assert "notzip.zip: not a readable archive" in out
    assert "missing.zip: not a readable archive" in out


def test_the_pieces_can_be_reused(in_tmp, engine_registry, capsys):
    """Another program's command line built from these pieces: its own option names and store."""
    import argparse

    from xdfetch import cli
    from xdfetch.store import LocalStore

    p = argparse.ArgumentParser()
    cli.add_store_option(p, env="OTHER_STORE", default="work")
    cli.add_range_options(p, id_option="--only")
    args = p.parse_args(["--date", "2026-10-28", "--only", "example.other"])
    assert args.store == "work"
    assert args.ids == ["example.other"]
    assert cli.date_range(args) == (dt.date(2026, 10, 28), dt.date(2026, 10, 28))
    assert cli.cmd_plan(args, engine_registry, LocalStore(in_tmp / "work")) == OK
    assert capsys.readouterr().out == "example.other\t2026-10-28\tnew\n"
