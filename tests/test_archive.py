"""Archives: the zip, MANIFEST.tsv, NOTES.md, files a caller adds, and verify()."""

import datetime as dt
import io
import zipfile

import pytest
from conftest import NOW

from xdfetch import archive
from xdfetch.archive import Archive, Item


def item(oid="example.daily", day=28, name=None, data=b"bytes", note=""):
    date = dt.date(2026, 10, day)
    return Item(
        oid,
        date,
        name or f"{oid}/ex2610{day}.xml",
        data,
        f"https://example.com/feed/ex2610{day}.xml",
        NOW,
        "https://example.com/daily/",
        note,
    )


def test_names():
    assert archive.session_name(NOW) == "20261029-120000-www.zip"
    assert archive.session_name(NOW, "report") == "20261029-120000-report.zip"
    assert archive.batch_name("example.daily", dt.date(2026, 1, 5), dt.date(2026, 10, 1)) == (
        "example.daily-202601-202610.zip"
    )
    assert archive.batch_name("x", dt.date(2026, 1, 5), dt.date(2026, 1, 9), "fix") == "x-202601-202601-fix.zip"
    assert archive.iso(NOW) == "2026-10-29T12:00:00Z"


def test_build_and_verify(engine_registry):
    a = Archive("t.zip", [item(day=28), item(day=27, note="from the listing")])
    data = a.build(engine_registry.by_id, {"example.daily": "Described by its adapter."})
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.namelist() == ["MANIFEST.tsv", "NOTES.md", "example.daily/ex261027.xml", "example.daily/ex261028.xml"]
        notes = z.read("NOTES.md").decode()
    assert notes.startswith("# t.zip\n\n2 files from 1 outlets, fetched 2026-10-29 (UTC) by xdfetch ")
    assert "- **example.daily** (2 files, 2026-10-27 to 2026-10-28), from https://example.com/daily/.\n" in notes
    assert "  Described by its adapter.\n  from the listing\n" in notes
    assert notes.endswith("## Known issues\n\nNone recorded at fetch time.\n")
    assert [r["filename"] for r in archive.read_manifest(data)] == [
        "example.daily/ex261027.xml",
        "example.daily/ex261028.xml",
    ]
    assert archive.verify(data) == []


def test_notes_for_an_empty_archive_and_known_issues():
    notes = Archive("e.zip", extra_notes="  The feed was down at 03:00.\n").notes({})
    assert "No files: every outlet was already fetched or failed." in notes
    assert notes.endswith("## Known issues\n\nThe feed was down at 03:00.\n")


def test_extra_files_go_after_notes_in_order(engine_registry):
    got = []

    def extra(items):
        got.append([it.filename for it in items])
        return {"z.txt": "text", "a.bin": b"\xff"}

    data = Archive("t.zip", [item()], extra_files=extra).build(engine_registry.by_id)
    assert got == [["example.daily/ex261028.xml"]]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.namelist() == ["MANIFEST.tsv", "NOTES.md", "z.txt", "a.bin", "example.daily/ex261028.xml"]
        assert z.read("z.txt") == b"text"
        assert z.read("a.bin") == b"\xff"
    assert archive.verify(data) == []
    assert archive.verify(data, extra_files=["z.txt", "a.bin"]) == []
    assert archive.verify(data, extra_files=["z.txt"]) == ["a.bin: in archive, not in manifest"]


@pytest.mark.parametrize("name", ["MANIFEST.tsv", "NOTES.md", "example.daily/ex261028.xml"])
def test_extra_files_cannot_replace_the_archives_own(engine_registry, name):
    with pytest.raises(ValueError, match="extra files would replace"):
        Archive("t.zip", [item()], extra_files=lambda items: {name: "x"}).build(engine_registry.by_id)


def test_duplicate_filenames_are_refused(engine_registry):
    with pytest.raises(ValueError, match="duplicate filenames"):
        Archive("t.zip", [item(), item()]).build(engine_registry.by_id)


def test_verify_finds_problems():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "MANIFEST.tsv",
            "filename\tsha256\tbytes\tsource_url\tfetched_at\n"
            f"a/one\t{archive.sha256(b'one')}\t3\t\t\n"
            f"a/two\t{archive.sha256(b'two')}\t3\t\t\n"
            f"a/gone\t{archive.sha256(b'')}\t0\t\t\n",
        )
        z.writestr("a/one", b"one")
        z.writestr("a/two", b"TWO!")
        z.writestr("a/stray", b"")
    assert archive.verify(buf.getvalue()) == [
        "a/two: sha256 differs from manifest",
        "a/two: size differs from manifest",
        "a/gone: in manifest, not in archive",
        "a/stray: in archive, not in manifest",
    ]
