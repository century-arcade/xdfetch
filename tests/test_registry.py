import datetime as dt

import pytest

from xdfetch import adapters
from xdfetch import registry as reg

HEADER = "id\tadapter\tparams\tdays\thomepage\tnotes\n"


def tsv_file(path, *rows: str):
    path.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def test_parse_days():
    assert reg.parse_days("daily") == frozenset(range(7))
    assert reg.parse_days("") == frozenset(range(7))
    assert reg.parse_days("sun") == frozenset({6})
    assert reg.parse_days("mon-sat") == frozenset(range(6))
    assert reg.parse_days("mon,thu") == frozenset({0, 3})
    assert reg.parse_days("fri-mon") == frozenset({4, 5, 6, 0})
    assert reg.format_days(reg.parse_days("mon,thu")) == "mon,thu"
    assert reg.format_days(reg.parse_days("daily")) == "daily"
    with pytest.raises(reg.RegistryError):
        reg.outlet_from_row({"id": "x", "adapter": "url", "days": "someday"})


def test_params():
    assert reg.parse_params("url=https://a/b%y.xml set='two words'") == {"url": "https://a/b%y.xml", "set": "two words"}
    with pytest.raises(reg.RegistryError):
        reg.parse_params("novalue")


def test_outlet_dates_and_since():
    o = reg.outlet_from_row({"id": "w", "adapter": "url", "days": "sun", "since": "2026-10-11"})
    days = o.dates(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert days == [dt.date(2026, 10, 11), dt.date(2026, 10, 18), dt.date(2026, 10, 25)]


def test_latest_available_respects_tz_and_delay():
    o = reg.outlet_from_row({"id": "w", "adapter": "url", "tz": "America/Los_Angeles", "available_after": "6"})
    # 2026-10-29 10:00 UTC is 03:00 Pacific: with a 6 h delay, the 29th isn't available yet
    now = dt.datetime(2026, 10, 29, 10, 0, tzinfo=dt.UTC)
    assert o.latest_available(now) == dt.date(2026, 10, 28)
    now = dt.datetime(2026, 10, 29, 14, 0, tzinfo=dt.UTC)
    assert o.latest_available(now) == dt.date(2026, 10, 29)


def test_unknown_tz():
    with pytest.raises(reg.RegistryError, match="unknown tz"):
        reg.outlet_from_row({"id": "w", "adapter": "url", "tz": "Mars/Olympus_Mons"})


PUBLIC_IDS = [
    "universal.daily",
    "usatoday.daily",
    "universal.sunday",
    "nytimes.daily",
    "nytimes.mini",
    "nytimes.midi",
    "newyorker.daily",
    "newyorker.mini",
    "washingtonpost.sunday",
    "arkadium.mini",
    "arkadium.two-minute-mini",
    "brendanemmettquigley.blog",
    "dailyprincetonian.daily",
    "dailyprincetonian.mini",
]


def test_builtin_registry_loads(registry):
    up = registry["universal.daily"]
    assert up.adapter == "url"
    assert up.homepage.startswith("https://")
    for o in registry.outlets:
        assert o.homepage.startswith("https://"), f"{o.id}: every outlet needs a homepage"
        assert o.enabled is True
        assert o.notes, f"{o.id}: every outlet needs notes"


def test_every_builtin_row_has_a_builtin_adapter(registry):
    for o in registry.outlets:
        assert adapters.get(o.adapter).name == o.adapter


def test_builtin_rows_are_the_public_list(registry):
    assert [o.id for o in registry.outlets] == PUBLIC_IDS


@pytest.mark.parametrize("bad", ["nyt", "NYTimes.daily", "nytimes.daily.extra", "nytimes_daily", ".daily", "a.b-"])
def test_builtin_ids_must_be_two_parts(bad, tmp_path, monkeypatch):
    f = tsv_file(tmp_path / "o.tsv", f"{bad}\turl\t\t\t\t")
    monkeypatch.setattr(reg, "BUILTIN", f)
    with pytest.raises(reg.RegistryError, match=r"publisher.series"):
        reg.builtin()


def test_roundtrip(tmp_path, registry):
    path = tmp_path / "o.tsv"
    reg.write(path, registry.outlets)
    again = reg.Registry.load(path)
    assert [o.to_row() for o in again.outlets] == [o.to_row() for o in registry.outlets]
    assert path.read_text(encoding="utf-8").splitlines()[0].split("\t") == reg.COLUMNS


def test_duplicate_id():
    rows = [{"id": "a", "adapter": "url"}, {"id": "a", "adapter": "url"}]
    with pytest.raises(reg.RegistryError):
        reg.Registry([reg.outlet_from_row(r) for r in rows])


def test_duplicate_id_within_one_overlay_file(tmp_path, plugins):
    f = tsv_file(tmp_path / "o.tsv", "x\turl\turl=https://a.test/1\t\t\t", "x\turl\turl=https://a.test/2\t\t\t")
    with pytest.raises(reg.RegistryError, match="duplicate id rows: x"):
        reg.effective([f])


# --- overlays ---


def test_effective_without_plugins_is_the_builtin(plugins, registry):
    assert [o.to_row() for o in reg.effective().outlets] == [o.to_row() for o in registry.outlets]


def test_overlay_order(tmp_path, plugins):
    """Built-in, then plugin registries by entry-point name, then explicit files; later rows replace earlier."""
    up, nyt = "universal.daily", "nytimes.daily"
    a = tsv_file(
        tmp_path / "a.tsv", f"{up}\turl\turl=https://a.test/up\tsun\thttps://a.test/\tfrom a", "new\turl\t\t\t\t"
    )
    b = tsv_file(tmp_path / "b.tsv", f"{up}\turl\turl=https://b.test/up\t\t\tfrom b")
    c = tsv_file(tmp_path / "c.tsv", f"{nyt}\turl\turl=https://c.test/nyt\t\t\tfrom c")
    plugins(reg.ENTRY_POINT_GROUP, "zz-second", str(b))  # registered first, but named later
    plugins(reg.ENTRY_POINT_GROUP, "aa-first", a)
    r = reg.effective([c])
    assert r[up].notes == "from b"
    assert r[up].params == {"url": "https://b.test/up"}
    # replaced whole: b's row has no days or homepage, so a's sun and homepage don't survive
    assert r[up].days == frozenset(range(7))
    assert r[up].homepage == ""
    assert r[nyt].adapter == "url"
    assert r[nyt].notes == "from c"
    assert "new" in r  # ids from other files are opaque: no shape required
    # replaced rows keep their place; new rows go at the end
    ids = [o.id for o in r.outlets]
    assert ids[0] == up
    assert ids[-1] == "new"
    assert ids.index(nyt) == PUBLIC_IDS.index(nyt)


def test_plugin_registry_overrides_a_builtin_row(tmp_path, plugins):
    nyt = "nytimes.daily"
    f = tsv_file(tmp_path / "theirs.tsv", f"{nyt}\tnyt\tkind=daily\tmon\thttps://example.org/\ttheir operating choice")
    plugins(reg.ENTRY_POINT_GROUP, "theirs", lambda: f)  # a callable returning the path
    r = reg.effective()
    assert r[nyt].notes == "their operating choice"
    assert r[nyt].days == frozenset({0})
    assert r[nyt].refetch == ()  # their row has no refetch column: the default, not ours


def test_plugin_registry_as_a_resource(plugins):
    from importlib.resources import files

    plugins(reg.ENTRY_POINT_GROUP, "resource", files("xdfetch").joinpath("outlets.tsv"))
    assert "nytimes.daily" in reg.effective()


def test_from_files_only(tmp_path, plugins):
    """A program with a registry of its own: only its files, its own short ids, no built-ins, no plugins."""
    plugins(reg.ENTRY_POINT_GROUP, "theirs", tsv_file(tmp_path / "plugin.tsv", "fromplugin\turl\t\t\t\t"))
    one = tsv_file(
        tmp_path / "one.tsv", "nyt\tnyt\tkind=daily\t\t\tone", "up\turl\turl=https://a.test/%y%m%d.xml\t\t\t"
    )
    two = tsv_file(tmp_path / "two.tsv", "nyt\tnyt\tkind=daily\t\t\ttwo")
    r = reg.from_files([one, two])
    assert [o.id for o in r.outlets] == ["nyt", "up"]
    assert r["nyt"].notes == "two"
    assert reg.from_files([]).outlets == []


def test_broken_registry_plugins_say_which(tmp_path, plugins):
    plugins(reg.ENTRY_POINT_GROUP, "broken", ImportError("no module named fakepkg"))
    with pytest.raises(reg.RegistryError, match=r"registry plugin 'broken'.*failed to load.*fakepkg"):
        reg.effective()


def test_registry_plugin_naming_a_missing_file(tmp_path, plugins):
    plugins(reg.ENTRY_POINT_GROUP, "missing", tmp_path / "nope.tsv")
    with pytest.raises(reg.RegistryError, match=r"registry plugin 'missing'.*no such file"):
        reg.effective()


def test_registry_plugin_of_the_wrong_kind(plugins):
    plugins(reg.ENTRY_POINT_GROUP, "odd", 42)
    with pytest.raises(reg.RegistryError, match=r"registry plugin 'odd'.*int, not a path"):
        reg.effective()


def test_row_naming_an_adapter_nobody_provides(tmp_path, plugins):
    f = tsv_file(tmp_path / "o.tsv", "mystery\tnosuch\t\t\t\t")
    r = reg.effective([f])  # loading is fine; asking for the adapter says what's missing
    with pytest.raises(adapters.AdapterError, match=r"no adapter named 'nosuch'.*no installed package provides it"):
        adapters.get(r["mystery"].adapter)
