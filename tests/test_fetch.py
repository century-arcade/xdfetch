"""End to end against mocked HTTP: plan, run, archive, ledger, refetch, and the hooks."""

import datetime as dt
import functools
import io
import zipfile

import responses
from conftest import NOW, RAW, YESTERDAY, present

from xdfetch import adapters, archive, fetch
from xdfetch.archive import Archive
from xdfetch.http import NotFound
from xdfetch.ledger import Ledger
from xdfetch.store import LocalStore

DAILY = "https://example.com/feed/ex261028.xml"
OTHER = "https://example.com/other/oth261028.xml"


def zip_names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return sorted(z.namelist())


@responses.activate
def test_run_fetches_archives_and_records(tmp_path, engine_registry, http):
    responses.add(responses.GET, DAILY, body=RAW, headers={"Last-Modified": "Mon, 26 Oct 2026 23:57:44 GMT"})
    responses.add(responses.GET, OTHER, status=404)
    store = LocalStore(tmp_path)
    ids = ["example.daily", "example.other"]
    report = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW)
    assert [r.status for r in report.results] == ["ok", "missing"]
    assert report.archive_name == "20261029-120000-www.zip"
    assert store.list("downloads") == ["downloads/2026/20261029-120000-www.zip"]  # nothing beside it
    data = present(store.get("downloads/2026/20261029-120000-www.zip"))
    assert zip_names(data) == ["MANIFEST.tsv", "NOTES.md", "example.daily/ex261028.xml"]
    assert archive.verify(data) == []
    rows = archive.read_manifest(data)
    assert rows[0]["source_url"] == DAILY
    assert rows[0]["fetched_at"] == "2026-10-29T12:00:00Z"
    assert present(Ledger.load(store).latest_file("example.daily", YESTERDAY)).modified == "2026-10-26T23:57:44Z"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        notes = z.read("NOTES.md").decode()
    assert "**example.daily**" in notes
    assert "from https://example.com/daily/." in notes
    assert "A made-up daily feed." in notes
    assert "by xdfetch " in notes
    assert "`xdfetch convert`" in notes

    ledger = Ledger.load(store)
    assert [(e.id, e.status) for e in ledger.entries] == [("example.daily", "ok"), ("example.other", "missing")]
    assert ledger.entries[0].archive == report.archive_name
    assert (
        present(store.get("reports/2026/20261029-120000-report.md"))
        .decode()
        .startswith("# xdfetch run: 20261029-120000-www.zip\n")
    )

    # a second run the same day: example.daily is re-fetched (refetch offset 1 is due) and unchanged,
    # example.other retried
    responses.calls.reset()
    responses.add(responses.GET, DAILY, body=RAW)
    responses.add(responses.GET, OTHER, status=404)
    report2 = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW)
    assert [(r.job.outlet.id, r.status) for r in report2.results] == [
        ("example.daily", "same"),
        ("example.other", "missing"),
    ]
    assert report2.archive_name == ""


@responses.activate
def test_refetch_same_and_changed(tmp_path, engine_registry, http):
    responses.add(responses.GET, DAILY, body=RAW)
    store = LocalStore(tmp_path)
    ids = ["example.daily"]
    fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW)

    # same day, later: refetch offset 1 is due; same bytes -> "same", no new file
    responses.add(responses.GET, DAILY, body=RAW)
    r = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW + dt.timedelta(hours=6))
    assert [x.status for x in r.results] == ["same"]
    assert r.archive_name == ""

    # next day: offset 2 due; different bytes -> "changed", kept as .v2
    responses.add(responses.GET, DAILY, body=RAW.replace(b"Bird Words", b"Bird Words, corrected"))
    day2 = NOW + dt.timedelta(days=1)
    r = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=day2)
    assert [x.status for x in r.results] == ["changed"]
    data = present(store.get(f"downloads/2026/{r.archive_name}"))
    assert "example.daily/ex261028.v2.xml" in zip_names(data)
    ledger = Ledger.load(store)
    assert ledger.versions("example.daily", YESTERDAY) == 2

    # outside the refetch window: nothing to do
    r = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW + dt.timedelta(days=5))
    assert r.results == []


def test_plan_respects_calendar_and_availability(engine_registry):
    ledger = Ledger()
    # 06:00 UTC on the 28th is 02:00 Eastern; with available_after=3 the 28th isn't due yet
    early = dt.datetime(2026, 10, 28, 6, 0, tzinfo=dt.UTC)
    jobs = fetch.plan(engine_registry, ledger, YESTERDAY, YESTERDAY, ["example.daily"], now=early)
    assert jobs == []
    jobs = fetch.plan(engine_registry, ledger, YESTERDAY, YESTERDAY, ["example.daily"], now=NOW)
    assert [(j.date, j.reason) for j in jobs] == [(YESTERDAY, "new")]


def test_plan_through_today_takes_only_what_is_up(engine_registry):
    """A nightly's range of yesterday..today (08:30 UTC = 03:30 Eastern in winter): today's
    puzzle from a 3-hour outlet, only yesterday's from a 6-hour one; nothing is a miss."""
    ledger = Ledger()
    today = dt.date(2026, 11, 2)
    now = dt.datetime(2026, 11, 2, 8, 30, tzinfo=dt.UTC)
    yesterday = today - dt.timedelta(days=1)
    three = fetch.plan(engine_registry, ledger, yesterday, today, ["example.daily"], now=now)
    assert [j.date for j in three] == [yesterday, today]
    six = fetch.plan(engine_registry, ledger, yesterday, today, ["example.late"], now=now)
    assert [j.date for j in six] == [yesterday]


def test_plan_skips_disabled_outlets_and_forces(engine_registry):
    ledger = Ledger()
    jobs = fetch.plan(engine_registry, ledger, YESTERDAY, YESTERDAY, now=NOW)
    assert "example.off" not in {j.outlet.id for j in jobs}
    ledger = Ledger.parse(f"pubid\tdate\tstatus\nexample.other\t{YESTERDAY}\tok\n")
    assert fetch.plan(engine_registry, ledger, YESTERDAY, YESTERDAY, ["example.other"], now=NOW) == []
    forced = fetch.plan(engine_registry, ledger, YESTERDAY, YESTERDAY, ["example.other"], now=NOW, force=True)
    assert [j.reason for j in forced] == ["forced"]


def test_nothing_for_the_date_in_targets_is_a_miss(tmp_path, engine_registry, http, monkeypatch):
    """A picker or page lookup that finds nothing for the date (NotFound from targets()) is
    `missing`, like a 404 on the file: retried for a few days, never an error."""

    class Picker(adapters.Adapter):
        def targets(self, date):
            raise NotFound(f"no puzzle dated {date} on the date picker", url="https://example.com/date-picker")

    monkeypatch.setattr(fetch.adapters, "get", lambda name: Picker)
    store = LocalStore(tmp_path)
    report = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ["example.daily"], http=http, now=NOW)
    assert [(r.status, r.detail) for r in report.results] == [
        ("missing", "no puzzle dated 2026-10-28 on the date picker at https://example.com/date-picker")
    ]
    assert not report.errored
    assert present(Ledger.load(store).last_attempt("example.daily", YESTERDAY)).status == "missing"


@responses.activate
def test_errors_are_reported_not_raised(tmp_path, engine_registry, http):
    for _ in range(4):
        responses.add(responses.GET, DAILY, status=403)
    responses.add(responses.GET, OTHER, body=RAW)
    store = LocalStore(tmp_path)
    ids = ["example.daily", "example.other"]
    report = fetch.run(engine_registry, store, YESTERDAY, YESTERDAY, ids, http=http, now=NOW)
    statuses = {r.job.outlet.id: r.status for r in report.results}
    assert statuses == {"example.daily": "error", "example.other": "ok"}
    assert report.errored
    assert "HTTP 403" in report.markdown()


@responses.activate
def test_an_outlet_that_keeps_failing_is_skipped(tmp_path, engine_registry, http):
    for day in range(24, 29):
        responses.add(responses.GET, f"https://example.com/feed/ex2610{day}.xml", status=403)
    report = fetch.run(
        engine_registry, LocalStore(tmp_path), dt.date(2026, 10, 24), YESTERDAY, ["example.daily"], http=http, now=NOW
    )
    assert [r.status for r in report.results] == ["error", "error", "error", "skipped", "skipped"]
    assert len(Ledger.load(LocalStore(tmp_path)).entries) == 3  # skipped jobs aren't recorded


def test_dry_run_plans_and_writes_nothing(tmp_path, engine_registry, http):
    store = LocalStore(tmp_path / "store")
    report = fetch.run(
        engine_registry, store, YESTERDAY, YESTERDAY, ["example.daily"], http=http, dry_run=True, now=NOW
    )
    assert [(r.status, r.detail) for r in report.results] == [("skipped", "new")]
    assert store.list("") == []


@responses.activate
def test_hooks_shape_the_archive_and_see_it_stored(tmp_path, engine_registry, http):
    """What a program built on xdfetch adds: its own words in NOTES.md, its own files in the
    archive, its own record of the archive, its own report title."""
    responses.add(responses.GET, DAILY, body=RAW)
    store = LocalStore(tmp_path)
    seen = []

    def extra_files(items):
        return {"listing.txt": "".join(f"{it.filename} {it.homepage}\n" for it in items), "blob.bin": b"\x00\x01"}

    def on_archive(store_, key, data, now):
        seen.append((key, archive.sha256(data), now))
        assert store_.get(key) == data  # stored before the hook runs
        assert Ledger.load(store_).entries == []  # and before the ledger is saved

    factory = functools.partial(Archive, producer="mytool 2.0", conversion="Run mytool.", extra_files=extra_files)
    report = fetch.run(
        engine_registry,
        store,
        YESTERDAY,
        YESTERDAY,
        ["example.daily"],
        http=http,
        now=NOW,
        archive=factory,
        on_archive=on_archive,
        report_title="mytool run",
    )
    key = "downloads/2026/20261029-120000-www.zip"
    data = present(store.get(key))
    assert seen == [(key, archive.sha256(data), NOW)]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.namelist() == ["MANIFEST.tsv", "NOTES.md", "listing.txt", "blob.bin", "example.daily/ex261028.xml"]
        assert z.read("listing.txt") == b"example.daily/ex261028.xml https://example.com/daily/\n"
        notes = z.read("NOTES.md").decode()
    assert "by mytool 2.0." in notes
    assert "\nRun mytool.\n" in notes
    assert "xdfetch" not in notes
    assert archive.verify(data) == []
    assert report.markdown().startswith("# mytool run: 20261029-120000-www.zip\n")
    assert store.get("reports/2026/20261029-120000-report.md") == report.markdown().encode()


def test_store_keys():
    assert fetch.archive_key("20261029-120000-www.zip", NOW) == "downloads/2026/20261029-120000-www.zip"
    assert fetch.archive_key("x.zip", NOW, "incoming") == "incoming/2026/x.zip"
    assert fetch.report_key(NOW) == "reports/2026/20261029-120000-report.md"
