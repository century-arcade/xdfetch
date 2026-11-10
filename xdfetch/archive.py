"""Archives: a zip of the files a run fetched, as served, with MANIFEST.tsv and NOTES.md.

    MANIFEST.tsv      one row per file: filename, sha256, bytes, source_url, fetched_at
    NOTES.md          for a person opening the archive years from now: what's in it,
                      where each outlet's files came from, how to convert them
    <id>/<file>       each file under its outlet's id, named as the outlet named it

A caller can add files of its own beside MANIFEST.tsv and NOTES.md (`extra_files`), for
another tool that reads the archive. An archive is never rewritten once stored: a later
run that fetches a changed file puts it in a new archive, next to the first copy's name
(`.v2`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from . import __version__, tsv
from .registry import Outlet

MANIFEST = "MANIFEST.tsv"
NOTES = "NOTES.md"
MANIFEST_COLUMNS = ["filename", "sha256", "bytes", "source_url", "fetched_at"]

PRODUCER = f"xdfetch {__version__}"  # NOTES.md: "fetched ... by <producer>"
CONVERSION = (
    "Not converted inside this archive: each file is kept as the outlet served it. "
    "`xdfetch convert` turns a file into `.xd`, choosing the converter from the file's content."
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def session_name(ts: dt.datetime, kind: str = "www") -> str:
    """A run's archive name: 20261029-120000-www.zip, the run's start in UTC and a kind."""
    return ts.astimezone(dt.UTC).strftime("%Y%m%d-%H%M%S") + f"-{kind}.zip"


def batch_name(oid: str, first: dt.date, last: dt.date, suffix: str = "") -> str:
    """An archive name for one outlet's files over a span of months: <id>-202601-202610.zip."""
    name = f"{oid}-{first:%Y%m}-{last:%Y%m}"
    if suffix:
        name += f"-{suffix}"
    return name + ".zip"


@dataclass
class Item:
    """One file going into an archive."""

    id: str  # the outlet's id
    date: dt.date
    filename: str  # path inside the archive
    data: bytes
    source_url: str
    fetched_at: dt.datetime
    homepage: str  # the outlet's homepage when it was fetched (not written by xdfetch; for extra_files)
    note: str = ""
    modified: str = ""  # the server's Last-Modified, ISO 8601 UTC, where it sent one (ledger only)

    @property
    def sha256(self) -> str:
        return sha256(self.data)


# Given the archive's items, the files to add beside MANIFEST.tsv and NOTES.md: {name: text or bytes}.
ExtraFiles = Callable[[list[Item]], Mapping[str, str | bytes]]


@dataclass
class Archive:
    """An archive being built. `producer` and `conversion` are NOTES.md's words for who
    fetched the files and how to convert them; `extra_files` adds files of the caller's
    own, written after NOTES.md and before the fetched files, in the order given."""

    name: str
    items: list[Item] = field(default_factory=list)
    extra_notes: str = ""
    producer: str = PRODUCER
    conversion: str = CONVERSION
    extra_files: ExtraFiles | None = None

    def manifest_rows(self) -> list[dict[str, str]]:
        return [
            {
                "filename": it.filename,
                "sha256": it.sha256,
                "bytes": str(len(it.data)),
                "source_url": it.source_url,
                "fetched_at": iso(it.fetched_at),
            }
            for it in sorted(self.items, key=lambda i: i.filename)
        ]

    def manifest(self) -> str:
        return tsv.format_rows(MANIFEST_COLUMNS, self.manifest_rows())

    def notes(self, outlets: Mapping[str, Outlet], describe: Mapping[str, str] | None = None) -> str:
        """NOTES.md for a person opening the archive years from now. `outlets` maps id to
        outlet; `describe` overrides an outlet's notes with its adapter's description."""
        describe = describe or {}
        by_id: dict[str, list[Item]] = {}
        for it in self.items:
            by_id.setdefault(it.id, []).append(it)
        fetched = sorted(iso(it.fetched_at)[:10] for it in self.items)
        lines = [f"# {self.name}", ""]
        if self.items:
            span = fetched[0] if fetched[0] == fetched[-1] else f"{fetched[0]} to {fetched[-1]}"
            lines.append(
                f"{len(self.items)} files from {len(by_id)} outlets, fetched {span} (UTC) by "
                f"{self.producer}. `MANIFEST.tsv` has each file's URL, sha256 and fetch time."
            )
        else:
            lines.append("No files: every outlet was already fetched or failed. See the ledger.")
        lines += ["", "## Where the files came from", ""]
        for oid in sorted(by_id):
            items = sorted(by_id[oid], key=lambda i: i.date)
            outlet = outlets.get(oid)
            dates = f"{items[0].date}" if len(items) == 1 else f"{items[0].date} to {items[-1].date}"
            head = f"- **{oid}** ({len(items)} file{'s' if len(items) != 1 else ''}, {dates})"
            if outlet and outlet.homepage:
                head += f", from {outlet.homepage}"
            lines.append(head + ".")
            text = describe.get(oid) or (outlet.notes if outlet else "")
            if text:
                lines.append(f"  {text}")
            notes = sorted({it.note for it in items if it.note})
            for n in notes:
                lines.append(f"  {n}")
        lines += ["", "## How they were converted", "", self.conversion, "", "## Known issues", ""]
        lines.append(self.extra_notes.strip() if self.extra_notes.strip() else "None recorded at fetch time.")
        return "\n".join(lines) + "\n"

    def build(self, outlets: Mapping[str, Outlet], describe: Mapping[str, str] | None = None) -> bytes:
        names = [it.filename for it in self.items]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate filenames in archive: {dupes}")
        extra = dict(self.extra_files(list(self.items))) if self.extra_files else {}
        clash = sorted(set(extra) & ({MANIFEST, NOTES} | set(names)))
        if clash:
            raise ValueError(f"extra files would replace archive files: {clash}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, self.manifest())
            z.writestr(NOTES, self.notes(outlets, describe))
            for name, data in extra.items():
                z.writestr(name, data)
            for it in sorted(self.items, key=lambda i: i.filename):
                z.writestr(it.filename, it.data)
        return buf.getvalue()


def read_manifest(zip_bytes: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        _, rows = tsv.parse(z.read(MANIFEST).decode("utf-8"))
    return rows


def verify(zip_bytes: bytes, extra_files: Iterable[str] | None = None) -> list[str]:
    """Check every manifest row against the file in the zip. Returns problems (empty = fine).

    Files the manifest doesn't list are problems, except MANIFEST.tsv, NOTES.md and the
    caller's own files: those named in `extra_files`, or, when it is None, any file at the
    archive's top level (fetched files are always under their outlet's folder)."""
    problems = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = set(z.namelist())
        _, rows = tsv.parse(z.read(MANIFEST).decode("utf-8"))
        listed = set()
        for r in rows:
            fn = r["filename"]
            listed.add(fn)
            if fn not in names:
                problems.append(f"{fn}: in manifest, not in archive")
                continue
            data = z.read(fn)
            if sha256(data) != r["sha256"]:
                problems.append(f"{fn}: sha256 differs from manifest")
            if str(len(data)) != r["bytes"]:
                problems.append(f"{fn}: size differs from manifest")
        own = {MANIFEST, NOTES}
        if extra_files is None:
            own |= {n for n in names if "/" not in n}
        else:
            own |= set(extra_files)
        for fn in sorted(names - listed - own):
            problems.append(f"{fn}: in archive, not in manifest")
    return problems
