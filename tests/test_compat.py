"""Stores written before xdfetch: the ledger, archives and reports keep their exact format.

tests/compat/store/ is what the code xdfetch's engine was ported from wrote for the scenario
below (two runs, made-up outlets and bytes), with that tool's name given as `othertool`.
`othertool` adds a sources.tsv to each archive and a register file beside it; here it does
so through `archive=` and `on_archive`, and every file in the store must come out the same,
byte for byte. The report's archive path is compared with `/` separators, and the archives
with the OS byte zipfile records set for this platform (see made_here).
"""

import datetime as dt
import functools
import io
import struct
import types
import zipfile
import zlib
from pathlib import Path

import pytest
import responses
from conftest import present

from xdfetch import archive, fetch, tsv
from xdfetch import registry as reg
from xdfetch.archive import Archive, Item
from xdfetch.ledger import COLUMNS, Entry, Ledger
from xdfetch.store import LocalStore

EXPECTED = Path(__file__).parent / "compat" / "store"
# the zlib that compressed the expected archives; another zlib may deflate differently
EXPECTED_ZLIB = "1.3.1"

NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
REGISTRY = """\
id\tadapter\tparams\tdays\tsince\ttz\tavailable_after\trefetch\thomepage\tauth\tenabled\tnotes
example.daily\turl\turl=https://example.com/feed/ex%y%m%d.xml\tdaily\t\tAmerica/New_York\t3\t1,2\thttps://example.com/daily/\t\tyes\tA made-up daily feed. Named exYYMMDD.xml.
example.weekly\turl\turl=https://example.org/w/%Y-%m-%d.puz\twed\t\tAmerica/New_York\t6\t\thttps://example.org/\t\tyes\t
other.broken\turl\turl=https://broken.example.net/%Y%m%d.json filename=b-%Y-%m-%d.json\tdaily\t\tAmerica/Chicago\t0\t\t\t\tyes\tAlways refuses.
"""  # noqa: E501

TOOL = "othertool"
CONVERSION = (
    f"Not converted inside this archive. {TOOL}'s `convert` step reads the archive and writes `.xd` files; "
    f"the converter used is chosen from each file's content. "
    f"The version of {TOOL} that converted a file is recorded in the commit that added it."
)
SOURCES_COLUMNS = ["ReceiptId", "SourceFilename", "DownloadTime", "ExternalSource"]


def sources(items: list[Item]) -> dict[str, str]:
    rows = [
        {
            "ReceiptId": "",
            "SourceFilename": it.filename,
            "DownloadTime": it.fetched_at.astimezone(dt.UTC).strftime("%Y-%m-%d"),
            "ExternalSource": it.homepage,
        }
        for it in sorted(items, key=lambda i: i.filename)
    ]
    return {"sources.tsv": tsv.format_rows(SOURCES_COLUMNS, rows)}


def register(store, key: str, data: bytes, now: dt.datetime) -> None:
    row = {
        "name": key.rsplit("/", 1)[-1],
        "sha256": archive.sha256(data),
        "bytes": str(len(data)),
        "producer": TOOL,
        "kind": "session",
        "received": now.date().isoformat(),
        "fixity_recorded": "at receipt",
        "notes": "",
    }
    store.put(f"{key}.register.tsv", ("\t".join(row) + "\n" + "\t".join(row.values()) + "\n").encode())


@pytest.fixture
def frozen_zip_clock(monkeypatch):
    """zipfile stamps each member with the local time; the expected archives were made at this one."""
    fake = types.SimpleNamespace(time=lambda: 0.0, localtime=lambda t=None: (2026, 10, 29, 8, 0, 0, 3, 302, 0))
    monkeypatch.setattr(zipfile, "time", fake)


def scenario(store: LocalStore, registry: reg.Registry, http) -> None:
    run = functools.partial(
        fetch.run,
        registry,
        store,
        dt.date(2026, 10, 27),
        dt.date(2026, 10, 28),
        http=http,
        archive=functools.partial(Archive, producer=f"{TOOL} 0.1.0", conversion=CONVERSION, extra_files=sources),
        on_archive=register,
        report_title=f"{TOOL} run",
    )
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        rsps.get(
            "https://example.com/feed/ex261027.xml",
            body=b"<feed>twenty-seventh</feed>",
            headers={"Last-Modified": "Mon, 26 Oct 2026 23:57:44 GMT"},
        )
        rsps.get("https://example.com/feed/ex261028.xml", body="<feed>twenty-eighth é</feed>".encode())
        rsps.get("https://example.org/w/2026-10-28.puz", status=404)
        rsps.get("https://broken.example.net/20261027.json", status=403)
        rsps.get("https://broken.example.net/20261028.json", status=403)
        run(now=NOW)
    # a day later: the 28th is re-fetched (refetch 2) and has changed; the 27th is past its window
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        rsps.get("https://example.com/feed/ex261028.xml", body=b"<feed>twenty-eighth, fixed</feed>")
        rsps.get("https://example.org/w/2026-10-28.puz", status=404)
        rsps.get("https://broken.example.net/20261027.json", status=403)
        rsps.get("https://broken.example.net/20261028.json", status=403)
        run(now=NOW + dt.timedelta(days=1, hours=1))


def zip_members(data: bytes) -> list[tuple]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [(i.filename, i.date_time, i.compress_type, i.CRC, i.file_size, z.read(i)) for i in z.infolist()]


def made_here(data: bytes) -> bytes:
    """The zip as it would be written on this platform. zipfile records the OS a zip was made
    on (0, Windows, where the expected archives were written; 3 elsewhere) in each central
    directory entry's "version made by"; nothing else in the bytes depends on the OS."""
    os_byte = zipfile.ZipInfo().create_system
    out = bytearray(data)
    _, _, _, _, count, _, offset, _ = struct.unpack("<4s4H2LH", data[-22:])  # end of central directory
    for _ in range(count):
        assert out[offset : offset + 4] == b"PK\x01\x02"
        out[offset + 5] = os_byte
        name_len, extra_len, comment_len = struct.unpack("<3H", data[offset + 28 : offset + 34])
        offset += 46 + name_len + extra_len + comment_len
    return bytes(out)


def test_a_run_writes_the_store_byte_for_byte(tmp_path, monkeypatch, frozen_zip_clock, http):
    f = tmp_path / "outlets.tsv"
    f.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    store = LocalStore("store")
    scenario(store, reg.from_files([f]), http)

    expected = sorted(p.relative_to(EXPECTED).as_posix() for p in EXPECTED.rglob("*") if p.is_file())
    assert store.list("") == expected
    shas: dict[bytes, bytes] = {}  # an expected zip's sha256 -> the same zip's made here
    for key in expected:
        want, got = (EXPECTED / key).read_bytes(), store.get(key)
        assert got is not None
        if key.startswith("reports/"):
            got = got.replace(b"\\", b"/")
        if key.endswith(".zip"):
            assert zip_members(got) == zip_members(want), key
            here = made_here(want)
            shas[archive.sha256(want).encode()] = archive.sha256(here).encode()
            if zlib.ZLIB_RUNTIME_VERSION == EXPECTED_ZLIB:
                assert got == here, key
        elif key.endswith(".register.tsv") and zlib.ZLIB_RUNTIME_VERSION == EXPECTED_ZLIB:
            for old, new in shas.items():
                want = want.replace(old, new)
            assert got == want, key
        elif key.endswith(".register.tsv"):
            # all but the zip's sha256 and size, which depend on the zlib
            g, w = tsv.parse(got.decode())[1][0], tsv.parse(want.decode())[1][0]
            assert {k: v for k, v in g.items() if k not in ("sha256", "bytes")} == {
                k: v for k, v in w.items() if k not in ("sha256", "bytes")
            }, key
        else:
            assert got == want, key


def test_an_old_ledger_loads_and_writes_back_unchanged(tmp_path):
    text = (EXPECTED / "ledger.tsv").read_text(encoding="utf-8")
    assert text.splitlines()[0].split("\t") == COLUMNS  # the first column is still `pubid`
    ledger = Ledger.parse(text)
    first = ledger.entries[0]
    assert (first.id, first.date, first.status, first.modified) == (
        "example.daily",
        "2026-10-27",
        "ok",
        "2026-10-26T23:57:44Z",
    )
    assert (
        present(ledger.latest_file("example.daily", dt.date(2026, 10, 28))).filename == "example.daily/ex261028.v2.xml"
    )
    assert present(ledger.last_attempt("other.broken", dt.date(2026, 10, 28))).status == "error"
    assert ledger.format() == text
    store = LocalStore(tmp_path)
    ledger.save(store)
    assert store.get("ledger.tsv") == (EXPECTED / "ledger.tsv").read_bytes()


def test_a_ledger_by_hand_in_the_old_format():
    """Written the way the old code wrote it: pubid first, blank fields for a miss, LF endings."""
    text = (
        "pubid\tdate\tfilename\tsha256\tbytes\tsource_url\tfetched_at\tarchive\tstatus\tdetail\tmodified\n"
        "zz\t2026-10-28\tzz/a.xml\t" + "ab" * 32 + "\t5\thttps://example.com/a.xml\t2026-10-29T12:00:00Z\t"
        "20261029-120000-www.zip\tok\t\t\n"
        "zz\t2026-10-27\t\t\t\t\t2026-10-29T12:00:00Z\t\tmissing\tHTTP 404 at https://example.com/b.xml\t\n"
    )
    ledger = Ledger.parse(text)
    assert [(e.id, e.status) for e in ledger.entries] == [("zz", "ok"), ("zz", "missing")]
    assert ledger.have("zz", dt.date(2026, 10, 28))
    assert ledger.format() == text
    ledger.append(Entry("zz", "2026-10-26", status="error", detail="HTTP 500"))
    assert ledger.format().splitlines()[-1] == "zz\t2026-10-26\t\t\t\t\t\t\terror\tHTTP 500\t"


def test_a_ledger_from_before_the_modified_column():
    ledger = Ledger.parse("pubid\tdate\tfilename\tstatus\nzz\t2026-10-28\tzz/a.xml\tok\n")
    assert ledger.entries == [Entry("zz", "2026-10-28", "zz/a.xml", status="ok")]
    assert ledger.format().splitlines()[0] == "\t".join(COLUMNS)


def test_old_archives_verify_and_read():
    for p in sorted((EXPECTED / "downloads" / "2026").glob("*.zip")):
        data = p.read_bytes()
        assert archive.verify(data) == []  # sources.tsv is a top-level file of its producer's own
        assert archive.verify(data, extra_files=["sources.tsv"]) == []
        assert "sources.tsv: in archive, not in manifest" in archive.verify(data, extra_files=[])
        assert all(r["filename"].startswith("example.daily/") for r in archive.read_manifest(data))


def test_a_run_carries_on_from_an_old_store(tmp_path, http):
    """A run over a store written by the old code reads its ledger: what's held isn't fetched again."""
    store = LocalStore(tmp_path)
    store.put("ledger.tsv", (EXPECTED / "ledger.tsv").read_bytes())
    f = tmp_path / "outlets.tsv"
    f.write_text(REGISTRY, encoding="utf-8")
    registry = reg.from_files([f])
    later = NOW + dt.timedelta(days=2)
    jobs = fetch.plan(registry, Ledger.load(store), dt.date(2026, 10, 27), dt.date(2026, 10, 28), now=later)
    # example.daily's dates are held and past their refetch window; recent misses and errors are
    # retried, the 27th's error no longer (it is more than RETRY_MISSING_DAYS old)
    assert [(j.outlet.id, str(j.date), j.reason) for j in jobs] == [
        ("example.weekly", "2026-10-28", "retry"),
        ("other.broken", "2026-10-28", "retry"),
    ]
