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


def test_builtins():
    assert set(adapters.ADAPTERS) == {"url", "amuse", "nyt", "conde", "page", "princetonian"}
    assert adapters.get("url") is adapters.ADAPTERS["url"]


@responses.activate
def test_plugin_adapter_resolves_and_fetches(tmp_path, plugins, http):
    plugins(adapters.ENTRY_POINT_GROUP, "example", ExampleAdapter)
    assert adapters.get("example") is ExampleAdapter
    assert adapters.plugin_names() == ["example"]

    f = tmp_path / "o.tsv"
    f.write_text("pubid\tadapter\nex\texample\n", encoding="utf-8")
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
