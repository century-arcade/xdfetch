"""The observed availability window per outlet, read back from the ledger."""

import datetime as dt

from conftest import present

from xdfetch import availability
from xdfetch.ledger import Entry, Ledger


def test_observe_brackets_each_outlet(engine_registry):
    ledger = Ledger()
    # example.daily (America/New_York, available_after 3): on the 28th (EDT) a 06:30Z fetch found
    # nothing (02:30 local), an 08:30Z one found the file (04:30), written by the server on the 26th
    # at 23:57Z (19:57 EDT on the 26th)
    ledger.append(
        Entry("example.daily", "2026-10-28", fetched_at="2026-10-28T06:30:00Z", status="missing", detail="HTTP 404")
    )
    ledger.append(
        Entry(
            "example.daily",
            "2026-10-28",
            "example.daily/ex261028.xml",
            fetched_at="2026-10-28T08:30:00Z",
            status="ok",
            modified="2026-10-26T23:57:44Z",
        )
    )
    # a backfill days later says nothing about the hour it came up (it's just a later "seen up by")
    ledger.append(
        Entry(
            "example.daily", "2026-10-20", "example.daily/ex261020.xml", fetched_at="2026-10-28T08:30:01Z", status="ok"
        )
    )
    # a date never fetched successfully is no evidence
    ledger.append(Entry("example.daily", "2026-10-29", fetched_at="2026-10-29T07:00:00Z", status="missing"))
    # a refetch's miss after the first file (an outage) isn't about availability
    ledger.append(Entry("example.daily", "2026-10-28", fetched_at="2026-10-29T08:30:00Z", status="missing"))

    rows = {r.id: r for r in availability.observe(engine_registry, ledger)}
    daily = rows["example.daily"]
    assert daily.available_after == 3
    assert daily.dates == 2
    assert daily.seen_up == 4.5
    assert daily.seen_not_up == 2.5
    assert abs(present(daily.modified) - (-28 - 2 / 60 - 16 / 3600)) < 1e-6
    assert daily.verdict == "ok"
    other = rows["example.other"]
    assert other.dates == 0
    assert other.seen_up is None
    assert other.verdict == ""
    assert "example.off" in rows  # disabled outlets are observed too


def test_verdicts(engine_registry):
    ledger = Ledger()
    # example.other (available_after 3): found missing at 03:30 local, up at 04:30: the guess is too low
    ledger.append(Entry("example.other", "2026-11-02", fetched_at="2026-11-02T08:30:00Z", status="missing"))
    ledger.append(
        Entry("example.other", "2026-11-02", "example.other/x", fetched_at="2026-11-02T09:30:00Z", status="ok")
    )
    # example.late (available_after 6): the server says the file was written at 01:00 local: could be lower
    ledger.append(
        Entry(
            "example.late",
            "2026-11-02",
            "example.late/x.puz",
            fetched_at="2026-11-02T11:30:00Z",
            status="ok",
            modified="2026-11-02T06:00:00Z",
        )
    )
    rows = {r.id: r for r in availability.observe(engine_registry, ledger)}
    assert rows["example.other"].verdict == "raise: not up +3.5h"
    assert rows["example.late"].verdict == "could be 1.5"
    text = availability.table(list(rows.values()))
    assert text.startswith("id\tavailable_after\t")
    assert "example.other\t3\t1\t+4.5\t+3.5\t-\traise: not up +3.5h" in text
    assert "seen not up at" in text
    assert "last-modified" in text


def test_hours_count_from_local_midnight(engine_registry):
    early = engine_registry["example.early"]  # posted 22:00 Eastern the evening before: -2
    t = dt.datetime(2026, 11, 2, 3, 0, tzinfo=dt.UTC)  # 22:00 EST on Nov 1
    assert availability.hours_after(early, dt.date(2026, 11, 2), t) == -2
