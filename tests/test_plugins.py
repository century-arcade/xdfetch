"""Converter plugins, through the `xdfetch.converters` entry-point group. Nothing is
installed: importlib.metadata.entry_points is replaced with a list of fakes."""

import importlib.metadata
import re
import types

import pytest
from conftest import make_ipuz

from xdfetch import convert, xd
from xdfetch.cli import FAILED, main
from xdfetch.convert import ipuz

TOY = b"TOY:"


class FakeEntryPoint:
    def __init__(self, name, obj=None, error=None):
        self.name, self.value, self.group = name, f"toyplugin:{name}", convert.PLUGIN_GROUP
        self.obj, self.error = obj, error

    def load(self):
        if self.error:
            raise self.error
        return self.obj


def toy_sniff(data: bytes) -> bool:
    return data.startswith(TOY)


def toy_convert(data: bytes, ctx: convert.Context) -> xd.Puzzle:
    p = xd.Puzzle()
    p.grid = [data[len(TOY) :].decode()]
    p.set("Title", "Toy")
    return p


@pytest.fixture
def plugins(monkeypatch):
    """Install these fake entry points for the test, with the converter list rebuilt."""

    def install(*eps):
        def entry_points(**kw):
            assert kw == {"group": convert.PLUGIN_GROUP}
            return list(eps)

        monkeypatch.setattr(importlib.metadata, "entry_points", entry_points)
        monkeypatch.setattr(convert, "_CONVERTERS", None)

    yield install
    convert._CONVERTERS = None


def test_tuple_plugin(plugins):
    plugins(FakeEntryPoint("toy", ("toy", toy_sniff, toy_convert)))
    assert convert.detect(b"TOY:AB") == "toy"
    fmt, p = convert.convert(b"TOY:AB")
    assert fmt == "toy"
    assert p.grid == ["AB"]
    assert [n for n, _, _ in convert.converters()][:2] == ["toy", "uclick"]


def test_module_plugin_named_by_its_entry_point(plugins):
    module = types.ModuleType("toyplugin")
    setattr(module, "sniff", toy_sniff)  # noqa: B010
    setattr(module, "convert", toy_convert)  # noqa: B010
    plugins(FakeEntryPoint("toymod", module))
    assert convert.convert(b"TOY:AB")[0] == "toymod"


def test_object_with_a_name(plugins):
    plugins(FakeEntryPoint("ep", types.SimpleNamespace(name="named", sniff=toy_sniff, convert=toy_convert)))
    assert convert.detect(b"TOY:AB") == "named"
    assert convert.convert(b"TOY:AB", fmt="named")[0] == "named"


def test_plugins_are_sniffed_before_builtins(plugins, ipuz_bytes):
    def mine(data, ctx):
        p = ipuz.convert(data, ctx)
        p.set("Title", "Overlaid")
        return p

    plugins(FakeEntryPoint("over", ("over", ipuz.sniff, mine)))
    fmt, p = convert.convert(ipuz_bytes)
    assert fmt == "over"
    assert p.headers["Title"] == "Overlaid"


def test_a_plugin_can_pass(plugins, ipuz_bytes):
    """A plugin that adds an outlet's conventions to a built-in converter, and returns None
    when the context isn't that outlet's: the built-in then converts as usual."""

    def outlet(data, ctx):
        if "record.json" not in ctx.companions:
            return None
        p = ipuz.convert(data, ctx)
        p.set("Title", ctx.companions["record.json"].decode())
        return p

    plugins(FakeEntryPoint("outlet", ("outlet", ipuz.sniff, outlet)))
    assert convert.convert(ipuz_bytes) == ("ipuz", convert.convert(ipuz_bytes, fmt="ipuz")[1])
    fmt, p = convert.convert(ipuz_bytes, convert.Context(companions={"record.json": b"From the record"}))
    assert fmt == "outlet"
    assert p.headers["Title"] == "From the record"
    assert p.to_xd().replace("From the record", "Tiny") == ipuz.convert(ipuz_bytes, convert.Context()).to_xd()


def test_plugins_load_in_name_order(plugins):
    plugins(
        FakeEntryPoint("zed", ("zed", toy_sniff, toy_convert)),
        FakeEntryPoint("abe", ("abe", toy_sniff, toy_convert)),
    )
    assert convert.detect(b"TOY:A") == "abe"


def test_nothing_loads_at_import(plugins):
    plugins(FakeEntryPoint("broken", error=ImportError("no module named toyplugin")))
    import xdfetch.convert.ipuz  # noqa: F401  (importing never touches plugins)


@pytest.mark.parametrize(
    ("ep", "message"),
    [
        (
            FakeEntryPoint("broken", error=ImportError("no module named toyplugin")),
            "converter plugin 'broken' (toyplugin:broken) failed to load: ImportError: no module named toyplugin",
        ),
        (FakeEntryPoint("pair", ("pair", toy_sniff)), "converter plugin 'pair' (toyplugin:pair) is a tuple of 2"),
        (FakeEntryPoint("nosniff", types.SimpleNamespace(convert=toy_convert)), "converter plugin 'nosniff'"),
        (FakeEntryPoint("badname", (3, toy_sniff, toy_convert)), "converter plugin 'badname'"),
    ],
)
def test_broken_plugin_is_named(plugins, ep, message):
    plugins(ep)
    with pytest.raises(convert.PluginError, match="^" + re.escape(message)):
        convert.converters()
    with pytest.raises(convert.PluginError):
        convert.detect(b"anything")


def test_real_entry_point_that_cannot_be_imported(plugins):
    ep = importlib.metadata.EntryPoint("ghost", "xdfetch_no_such_module:convert", convert.PLUGIN_GROUP)
    plugins(ep)
    with pytest.raises(convert.PluginError, match=r"converter plugin 'ghost'.*failed to load: ModuleNotFoundError"):
        convert.converters()


def test_a_sniff_that_raises_is_named(plugins):
    def bad_sniff(data):
        raise RuntimeError("oops")

    plugins(FakeEntryPoint("touchy", ("touchy", bad_sniff, toy_convert)))
    with pytest.raises(convert.PluginError, match="converter 'touchy': sniff failed: RuntimeError: oops"):
        convert.detect(b"x")


def test_cli_reports_a_broken_plugin(plugins, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.ipuz").write_text(str(make_ipuz()))
    plugins(FakeEntryPoint("broken", error=ImportError("no module named toyplugin")))
    assert main(["convert", "a.ipuz"]) == FAILED
    err = capsys.readouterr().err
    assert "converter plugin 'broken'" in err
    assert "Traceback" not in err
