import datetime as dt

from conftest import present

from xdfetch.ledger import COLUMNS, Entry, Ledger
from xdfetch.store import LocalStore


def test_roundtrip(tmp_path):
    store = LocalStore(tmp_path)
    ledger = Ledger.load(store)
    assert ledger.entries == []
    ledger.append(
        Entry(
            "example.daily",
            "2026-10-28",
            "example.daily/ex261028.xml",
            "ab" * 32,
            "100",
            "https://example.com/feed/ex261028.xml",
            "2026-10-29T12:00:00Z",
            "20261029-120000-www.zip",
            "ok",
        )
    )
    ledger.append(Entry("example.daily", "2026-10-27", status="missing", detail="HTTP 404"))
    ledger.append(Entry("example.daily", "2026-10-26", "example.daily/x", status="ok", modified="2026-10-24T23:57:44Z"))
    ledger.save(store)
    again = Ledger.load(store)
    assert len(again.entries) == 3
    assert again.entries[2].modified == "2026-10-24T23:57:44Z"
    assert again.entries[0].modified == ""
    assert again.have("example.daily", dt.date(2026, 10, 28))
    assert not again.have("example.daily", dt.date(2026, 10, 27))
    assert present(again.last_attempt("example.daily", dt.date(2026, 10, 27))).status == "missing"
    assert again.fetch_count("example.daily", dt.date(2026, 10, 28)) == 1


def test_the_id_is_the_pubid_column_on_disk(tmp_path):
    ledger = Ledger([Entry("example.daily", "2026-10-28", status="ok")])
    text = ledger.format()
    assert text.splitlines()[0] == "\t".join(COLUMNS)
    assert COLUMNS[0] == "pubid"
    assert text.splitlines()[1].startswith("example.daily\t2026-10-28\t")
    assert Ledger.parse(text).entries[0].id == "example.daily"
    assert Ledger.parse(text).entries[0].day == dt.date(2026, 10, 28)


def test_versions_and_streaks():
    ledger = Ledger()
    d = dt.date(2026, 10, 28)
    ledger.append(Entry("example.daily", "2026-10-28", "a", "1", status="ok"))
    ledger.append(Entry("example.daily", "2026-10-28", "", "", status="same"))
    ledger.append(Entry("example.daily", "2026-10-28", "a.v2", "2", status="changed"))
    assert ledger.versions("example.daily", d) == 2
    assert ledger.fetch_count("example.daily", d) == 3
    assert present(ledger.latest_file("example.daily", d)).filename == "a.v2"
    ledger.append(Entry("example.daily", "2026-10-29", status="missing"))
    ledger.append(Entry("example.daily", "2026-10-30", status="error"))
    dates = [dt.date(2026, 10, 28), dt.date(2026, 10, 29), dt.date(2026, 10, 30)]
    assert ledger.consecutive_misses("example.daily", dates) == 2
