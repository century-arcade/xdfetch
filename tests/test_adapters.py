"""Finding adapters: the built-ins, then the `xdfetch.adapters` entry points."""

import datetime as dt

import pytest
import responses

from xdfetch import adapters
from xdfetch import registry as reg
from xdfetch.adapters import Adapter, Target


class ExampleAdapter(Adapter):
    name = "example"

    def targets(self, date: dt.date) -> list[Target]:
        return [Target(url=f"https://example.test/{date:%Y%m%d}.puz", filename=f"{date:%Y%m%d}.puz")]


@responses.activate
def test_ids_from_another_registry_are_used_as_given(tmp_path, http):
    """A registry of short ids from elsewhere: file names come out as <id>-<date>, the id untouched."""
    f = tmp_path / "theirs.tsv"
    f.write_text(
        "id\tadapter\tparams\n"
        "nyt\tnyt\tkind=daily\n"
        "tny\tconde\tpage=https://www.newyorker.com/puzzles-and-games-dept/crossword/%Y/%m/%d\n"
        "prncmini\tprincetonian\tmini=true\n"
        "odd\turl\turl=https://example.test/feed/\n",
        encoding="utf-8",
    )
    r = reg.from_files([f])
    day = dt.date(2026, 10, 28)
    responses.get(
        "https://www.newyorker.com/puzzles-and-games-dept/crossword/2026/10/28",
        body='{"id":"00000000-1111-4222-8333-444444444444"}',
    )
    responses.get(
        "https://crossword.dailyprincetonian.com/api/crosswords?mini=true",
        json=[{"id": "x", "date": "2026-10-28T00:00:00+00:00"}],
    )

    def filename(oid: str) -> str:
        (t,) = adapters.get(r[oid].adapter)(r[oid], http, secrets={}).targets(day)
        return t.filename

    assert filename("nyt") == "nyt-2026-10-28.json"
    assert filename("tny") == "tny-2026-10-28.json"
    assert filename("prncmini") == "prncmini-2026-10-28.json"
    assert filename("odd") == "odd2026-10-28"  # a URL with no file name of its own


@responses.activate
def test_fetch_returns_bytes_in_hand_without_a_request(registry, http):
    a = adapters.get("url")(registry["universal.daily"], http)
    t = Target(url="https://example.test/listing#7", filename="meta/7.json", companion=True, data=b'{"id": 7}')
    got = a.fetch(t)
    assert (got.data, got.url, got.filename) == (b'{"id": 7}', "https://example.test/listing#7", "meta/7.json")
    assert len(responses.calls) == 0
    assert Target(url="u", filename="f").companion is False


def test_builtins():
    assert set(adapters.ADAPTERS) == {"url", "nyt", "conde", "page", "princetonian", "amuse"}
    assert adapters.get("url") is adapters.ADAPTERS["url"]


@responses.activate
def test_plugin_adapter_resolves_and_fetches(tmp_path, plugins, http):
    plugins(adapters.ENTRY_POINT_GROUP, "example", ExampleAdapter)
    assert adapters.get("example") is ExampleAdapter
    assert adapters.plugin_names() == ["example"]

    f = tmp_path / "o.tsv"
    f.write_text("id\tadapter\nex\texample\n", encoding="utf-8")
    outlet = reg.effective([f])["ex"]
    responses.get("https://example.test/20261028.puz", body=b"bytes")
    a = adapters.get(outlet.adapter)(outlet, http)
    (t,) = a.targets(dt.date(2026, 10, 28))
    assert a.fetch(t).data == b"bytes"


def test_builtin_name_wins_over_a_plugin(plugins):
    plugins(adapters.ENTRY_POINT_GROUP, "url", ExampleAdapter)
    assert adapters.get("url") is adapters.ADAPTERS["url"]
    assert adapters.plugin_names() == []


def test_unknown_adapter_is_a_clear_key_error(plugins):
    plugins(adapters.ENTRY_POINT_GROUP, "example", ExampleAdapter)
    with pytest.raises(KeyError) as e:
        adapters.get("nosuch")
    assert isinstance(e.value, adapters.AdapterError)
    msg = str(e.value)
    assert msg.startswith("no adapter named 'nosuch'")
    assert "example (plugin)" in msg
    assert "url" in msg


def test_plugin_that_fails_to_import(plugins):
    plugins(adapters.ENTRY_POINT_GROUP, "broken", ImportError("No module named 'fakepkg'"), "fakepkg.adapters:Broken")
    with pytest.raises(adapters.AdapterError, match=r"adapter plugin 'broken' \(fakepkg.adapters:Broken\) failed"):
        adapters.get("broken")


def test_plugin_that_is_not_an_adapter(plugins):
    plugins(adapters.ENTRY_POINT_GROUP, "notone", object)
    with pytest.raises(adapters.AdapterError, match=r"'notone'.*not an xdfetch.adapters.Adapter subclass"):
        adapters.get("notone")


def test_two_packages_claiming_one_name(plugins):
    plugins(adapters.ENTRY_POINT_GROUP, "dup", ExampleAdapter, "one:A")
    plugins(adapters.ENTRY_POINT_GROUP, "dup", ExampleAdapter, "two:B")
    with pytest.raises(adapters.AdapterError, match="more than one installed package"):
        adapters.get("dup")
