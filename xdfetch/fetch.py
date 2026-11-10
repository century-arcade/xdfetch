"""Plan and run a fetch: expected puzzles minus the ledger, then fetch, archive, record.

`run()` is the whole thing against a store (see xdfetch.store):

    ledger.tsv                                   updated: one row per fetch (xdfetch.ledger)
    <archive_prefix>/<YYYY>/<YYYYMMDD-HHMMSS>-www.zip   the files fetched, if any (xdfetch.archive)
    reports/<YYYY>/<YYYYMMDD-HHMMSS>-report.md   the run's report (RunReport.markdown)

A program built on xdfetch shapes the archive with `archive=` (a factory such as
`functools.partial(Archive, producer=..., extra_files=...)`), titles the report with
`report_title=`, and does anything more with a new archive in `on_archive`, which is
called once it is stored and before the ledger is saved.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from . import adapters
from .archive import Archive, Item, iso, session_name, sha256, utcnow
from .http import FetchError, Http, NotFound
from .ledger import Entry, Ledger
from .registry import Outlet, Registry
from .store import Store

log = logging.getLogger("xdfetch")

RETRY_MISSING_DAYS = 3  # keep retrying a missing/errored date this long after it
REPORT_TITLE = "xdfetch run"

# Builds the run's archive from its name and items (Archive itself, or a partial of it).
ArchiveFactory = Callable[[str, list[Item]], Archive]
# Called with (store, key, archive bytes, the run's `now`) once the archive is stored.
OnArchive = Callable[[Store, str, bytes, dt.datetime], None]


@dataclass
class Job:
    outlet: Outlet
    date: dt.date
    reason: str  # new | refetch | retry | forced


@dataclass
class Result:
    job: Job
    status: str  # ok | same | changed | missing | error | skipped | companion
    detail: str = ""
    item: Item | None = None


@dataclass
class RunReport:
    archive_name: str = ""
    archive_key: str = ""  # where the archive is, for a person (Store.describe)
    results: list[Result] = field(default_factory=list)
    title: str = REPORT_TITLE

    def by_status(self, status: str) -> list[Result]:
        return [r for r in self.results if r.status == status]

    @property
    def errored(self) -> bool:
        return any(r.status == "error" for r in self.results)

    def markdown(self) -> str:
        lines = [f"# {self.title}: {self.archive_name or 'nothing fetched'}", ""]
        counts = {}
        for r in self.results:
            if r.status != "companion":
                counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "nothing to do")
        if self.archive_key:
            lines.append(f"\nArchive: `{self.archive_key}`")
        lines.append("")
        by_id: dict[str, list[Result]] = {}
        for r in self.results:
            by_id.setdefault(r.job.outlet.id, []).append(r)
        lines.append("| outlet | ok | same | changed | missing | error | skipped |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|")
        for oid in sorted(by_id):
            rs = by_id[oid]
            c = {
                s: sum(1 for r in rs if r.status == s) for s in ("ok", "same", "changed", "missing", "error", "skipped")
            }
            lines.append(f"| {oid} | " + " | ".join(str(c[s]) for s in c) + " |")
        problems = [r for r in self.results if r.status in ("error", "missing", "changed")]
        if problems:
            lines += ["", "## Details", ""]
            for r in problems:
                lines.append(f"- {r.job.outlet.id} {r.job.date} {r.status}: {r.detail}")
        return "\n".join(lines) + "\n"


def plan(
    registry: Registry,
    ledger: Ledger,
    start: dt.date,
    end: dt.date,
    ids: list[str] | None = None,
    now: dt.datetime | None = None,
    refetch: bool = True,
    force: bool = False,
) -> list[Job]:
    """Which (outlet, date) pairs to fetch for [start, end]."""
    now = now or utcnow()
    today = now.date()
    jobs: list[Job] = []
    for outlet in registry.select(ids):
        latest = outlet.latest_available(now)
        for day in outlet.dates(start, min(end, latest)):
            if force:
                jobs.append(Job(outlet, day, "forced"))
                continue
            last = ledger.last_attempt(outlet.id, day)
            if last is None:
                jobs.append(Job(outlet, day, "new"))
            elif last.status in ("missing", "error"):
                if (today - day).days <= RETRY_MISSING_DAYS:
                    jobs.append(Job(outlet, day, "retry"))
            elif refetch and outlet.refetch:
                # the registry names offsets (days after publication) to look again on;
                # a puzzle wants 1 + (offsets reached so far) fetches while inside that window
                age = (today - day).days
                if age <= max(outlet.refetch):
                    due = [d for d in outlet.refetch if d <= age]
                    if ledger.fetch_count(outlet.id, day) < 1 + len(due):
                        jobs.append(Job(outlet, day, "refetch"))
    return jobs


def run_jobs(
    jobs: list[Job],
    ledger: Ledger,
    http: Http,
    secrets: dict[str, str] | None = None,
    now: dt.datetime | None = None,
    stop_after_errors: int = 3,
) -> list[Result]:
    """Fetch every job. Errors are recorded, not raised. An outlet that errors
    `stop_after_errors` times in a row is skipped for the rest of the run."""
    results: list[Result] = []
    adapter_cache: dict[str, adapters.Adapter] = {}
    errors_in_a_row: dict[str, int] = {}
    for job in jobs:
        outlet = job.outlet
        if errors_in_a_row.get(outlet.id, 0) >= stop_after_errors:
            results.append(Result(job, "skipped", f"{stop_after_errors} errors in a row"))
            continue
        try:
            adapter = adapter_cache.get(outlet.id)
            if adapter is None:
                adapter = adapters.get(outlet.adapter)(outlet, http, secrets)
                adapter_cache[outlet.id] = adapter
            targets = adapter.targets(job.date)
        except NotFound as e:  # the picker or the outlet's page has nothing for the date: a miss, not an error
            results.append(Result(job, "missing", f"{e}" + (f" at {e.url}" if e.url else "")))
            errors_in_a_row[outlet.id] = 0
            continue
        except Exception as e:  # a registry/adapter problem: report it, move on
            results.append(Result(job, "error", f"{e.__class__.__name__}: {e}"))
            errors_in_a_row[outlet.id] = errors_in_a_row.get(outlet.id, 0) + 1
            continue
        archived_puzzle = False  # a companion is kept only beside a puzzle archived in this job
        for target in targets:
            fetched_at = now or utcnow()
            if target.companion and not archived_puzzle:
                continue
            try:
                got = adapter.fetch(target)
            except NotFound as e:
                results.append(Result(job, "missing", f"{e} at {e.url}"))
                errors_in_a_row[outlet.id] = 0
                continue
            except FetchError as e:
                results.append(Result(job, "error", f"{e} at {e.url}"))
                errors_in_a_row[outlet.id] = errors_in_a_row.get(outlet.id, 0) + 1
                continue
            except Exception as e:
                results.append(Result(job, "error", f"{e.__class__.__name__}: {e}"))
                errors_in_a_row[outlet.id] = errors_in_a_row.get(outlet.id, 0) + 1
                continue
            errors_in_a_row[outlet.id] = 0
            filename = f"{outlet.id}/{got.filename or target.filename}"
            digest = sha256(got.data)
            if target.companion:
                # kept beside the puzzle it came with; never counted as a fetch of the puzzle
                item = Item(outlet.id, job.date, filename, got.data, got.url, fetched_at, outlet.homepage, target.note)
                results.append(Result(job, "companion", "", item))
                continue
            previous = ledger.latest_file(outlet.id, job.date)
            if previous is not None:
                if previous.sha256 == digest:
                    results.append(Result(job, "same", previous.sha256[:12]))
                    continue
                n = ledger.versions(outlet.id, job.date) + 1
                stem, dot, ext = filename.rpartition(".")
                filename = f"{stem}.v{n}.{ext}" if dot else f"{filename}.v{n}"
                status, detail = "changed", f"was {previous.sha256[:12]} in {previous.archive}"
            else:
                status, detail = "ok", ""
            archived_puzzle = True
            item = Item(
                id=outlet.id,
                date=job.date,
                filename=filename,
                data=got.data,
                source_url=got.url,
                fetched_at=fetched_at,
                homepage=outlet.homepage,
                note=target.note,
                modified=got.modified,
            )
            results.append(Result(job, status, detail, item))
    return results


def record(results: list[Result], ledger: Ledger, archive_name: str, now: dt.datetime | None = None) -> None:
    """Append this run's results to the ledger."""
    ts = iso(now or utcnow())
    for r in results:
        if r.status == "skipped":
            continue
        job = r.job
        if r.item:
            ledger.append(
                Entry(
                    job.outlet.id,
                    job.date.isoformat(),
                    r.item.filename,
                    r.item.sha256,
                    str(len(r.item.data)),
                    r.item.source_url,
                    iso(r.item.fetched_at),
                    archive_name,
                    r.status,
                    r.detail,
                    r.item.modified,
                )
            )
        else:
            ledger.append(Entry(job.outlet.id, job.date.isoformat(), "", "", "", "", ts, "", r.status, r.detail))


def archive_key(name: str, now: dt.datetime, archive_prefix: str = "downloads") -> str:
    """The store key a run's archive is put under."""
    return f"{archive_prefix}/{now:%Y}/{name}"


def report_key(now: dt.datetime) -> str:
    """The store key a run's report is put under."""
    return f"reports/{now:%Y}/{session_name(now, 'report').removesuffix('.zip')}.md"


def run(
    registry: Registry,
    store: Store,
    start: dt.date,
    end: dt.date,
    ids: list[str] | None = None,
    http: Http | None = None,
    secrets: dict[str, str] | None = None,
    now: dt.datetime | None = None,
    archive_prefix: str = "downloads",
    refetch: bool = True,
    force: bool = False,
    dry_run: bool = False,
    *,
    archive: ArchiveFactory = Archive,
    on_archive: OnArchive | None = None,
    report_title: str = REPORT_TITLE,
) -> RunReport:
    """The whole thing: plan, fetch, build the archive, store it, update the ledger, store
    the report. See the module docstring for `archive`, `on_archive` and `report_title`."""
    now = now or utcnow()
    http = http or Http()
    ledger = Ledger.load(store)
    jobs = plan(registry, ledger, start, end, ids, now=now, refetch=refetch, force=force)
    report = RunReport(title=report_title)
    if dry_run:
        report.results = [Result(j, "skipped", j.reason) for j in jobs]
        return report
    results = run_jobs(jobs, ledger, http, secrets, now=now)
    report.results = results
    items = [r.item for r in results if r.item]
    name = session_name(now)
    if items:
        built = archive(name, items)
        describe = {}
        for oid in {it.id for it in items}:
            outlet = registry[oid]
            try:
                describe[oid] = adapters.get(outlet.adapter)(outlet, http, secrets).describe()
            except Exception as e:  # a description must never sink the archive
                log.warning("%s: describe() failed: %s", oid, e)
        data = built.build(registry.by_id, describe)
        key = archive_key(name, now, archive_prefix)
        store.put(key, data)
        report.archive_name = name
        report.archive_key = store.describe(key)
        if on_archive:
            on_archive(store, key, data, now)
    record(results, ledger, name if items else "", now=now)
    ledger.save(store)
    store.put(report_key(now), report.markdown().encode())
    return report
