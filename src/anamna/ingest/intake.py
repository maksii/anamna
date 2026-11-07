"""The intake queue: what happens between "upload" and "it is in the record".

A submission is no longer one file the browser waits for.  It can be a dozen
scans, a zip of a clinic's whole folder, or a vendor export that unpacks into
tens of thousands of files and takes minutes to read.  Holding an HTTP request
open for that is not an option, and neither is a spinner that says nothing, so
each unit of work becomes a row in `upload_jobs` that the page can watch.

Three jobs do the work and one of them makes more of itself:

* `document`      one scan through the extraction pipeline
* `archive`       a zip, expanded into more jobs in the same batch
* `device_export` a vendor export directory handed to its adapter
* `rescan`        a stored document re-read by today's parser

A single worker thread drains the queue in order.  Extraction is CPU-bound and
this is one person's own machine, so parallelism would buy contention rather
than speed.

# ponytail: one worker thread per database, serial. If a household ever shares
# an instance and queues collide, claim jobs by worker id and run N threads.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Callable, Iterable

from .. import paperless
from ..config import Settings, resolve_source_path
from ..db import connect, transaction, utc_now
from .extract import file_sha256
from .pipeline import SUPPORTED_SUFFIXES, RereadRefused, ingest_file, record_document_relations, reingest_document


logger = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = {".zip"}
#: Everything the upload form will take.
INTAKE_SUFFIXES = SUPPORTED_SUFFIXES | ARCHIVE_SUFFIXES

#: An archive arrives from outside, so it is bounded before it is trusted: a
#: few kilobytes can otherwise declare terabytes.  A real Apple Health export
#: is one 2-3 GB XML file plus a few thousand small ones, which sets the shape
#: of these limits - generous on total size, generous on count, finite in both.
MAX_ARCHIVE_ENTRIES = 200_000
MAX_ARCHIVE_EXPANDED_BYTES = 32 * 1024**3
#: Zips inside zips are expanded too, but not forever.
MAX_ARCHIVE_DEPTH = 3

DONE_DEVICE = "intake.done_device"
FAILED_MISSING = "intake.failed_missing"

#: Every value `upload_jobs.detail_key` may hold.  Job detail is rendered into
#: a page, and an exception string carries absolute paths and sometimes the
#: patient's own filenames, so what the queue reports is a key from this list
#: and never a message from the failure itself.
DETAIL_KEYS = (
    "intake.step_waiting",
    "intake.step_unpacking",
    "intake.step_reading",
    "intake.done_imported",
    "intake.done_no_values",
    "intake.done_duplicate",
    "intake.done_unchanged",
    "intake.done_expanded",
    DONE_DEVICE,
    "intake.done_rescanned",
    FAILED_MISSING,
    "intake.failed_unreadable",
    "intake.failed_unsupported",
    "intake.failed_empty",
    "intake.failed_too_big",
    "intake.failed_error",
    "intake.failed_device_archive_member",
    "intake.failed_reread_empty",
    "intake.failed_reread_ocr",
)

#: Structural giveaways in an export's own layout.
_NAME_SIGNATURES = (
    ("export.xml", "apple_health"),
    ("di_connect", "garmin"),
)
#: Field names only one vendor's export uses, checked against the first slice
#: of a bounded number of files when the layout alone is not decisive.
_CONTENT_SIGNATURES = {
    "oura": (b"readiness_score", b"total_sleep_duration", b"bedtime_start", b"average_hrv"),
    "garmin": (b"bodyBatteryHighestValue", b"restingHeartRate", b"summarizedActivities", b"UDSFile"),
}
_PEEK_FILES = 40
_PEEK_BYTES = 8192


# --- detection --------------------------------------------------------------


def _detect(names: Iterable[str], read: Callable[[str], bytes]) -> tuple[str | None, str]:
    """Which device adapter an export belongs to, and the root it starts at.

    Returns `(None, "")` for an ordinary bundle of documents.  The second value
    is the path within the export that the adapter should be pointed at: Apple
    zips its export one directory down, and `AppleHealthAdapter` looks for
    `export.xml` beside the root it is given, not beneath it.
    """
    listed = [name.replace("\\", "/") for name in names]
    folded = {name.casefold().strip("/") for name in listed}
    # Official Oura Takeout archives are rooted at ``App Data`` and contain no
    # filename with "oura" in it.  Its paired daily/sleep tables are a stronger
    # structural signature than peeking for old API field names, and occur
    # after the bounded content-peek window in a full 2026 account export.
    if {
        "app data/dailyactivity.csv",
        "app data/dailyreadiness.csv",
        "app data/dailysleep.csv",
        "app data/sleepmodel.csv",
    }.issubset(folded):
        return "oura", ""
    named = _name_signature(listed)
    if named:
        return named
    if any("oura" in PurePath(name).name.casefold() for name in listed):
        return "oura", ""
    scores = _content_scores(listed, read)
    if scores:
        return max(scores, key=lambda key: scores[key]), ""
    return None, ""


def _name_signature(listed: list[str]) -> tuple[str, str] | None:
    for needle, adapter in _NAME_SIGNATURES:
        for name in listed:
            parts = name.casefold().split("/")
            if needle in parts:
                index = parts.index(needle)
                return adapter, "/".join(name.split("/")[:index])
    return None


def _content_scores(listed: list[str], read: Callable[[str], bytes]) -> dict[str, int]:
    scores: dict[str, int] = {}
    peeked = 0
    for name in listed:
        if PurePath(name).suffix.casefold() not in {".json", ".csv"}:
            continue
        if peeked >= _PEEK_FILES:
            break
        peeked += 1
        try:
            head = read(name)
        except (OSError, KeyError, zipfile.BadZipFile):
            continue
        for adapter, markers in _CONTENT_SIGNATURES.items():
            hits = sum(1 for marker in markers if marker in head)
            if hits:
                scores[adapter] = scores.get(adapter, 0) + hits
    return scores


def detect_archive_adapter(archive: Path) -> tuple[str | None, str]:
    """Read a zip's directory and a slice of its files, without unpacking it."""
    with zipfile.ZipFile(archive) as bundle:
        names = [info.filename for info in bundle.infolist() if not info.is_dir()]

        def read(name: str) -> bytes:
            with bundle.open(name) as handle:
                return handle.read(_PEEK_BYTES)

        return _detect(names, read)


def detect_directory_adapter(root: Path) -> tuple[str | None, str]:
    files = [path for path in root.rglob("*") if path.is_file()]
    names = [str(path.relative_to(root)) for path in files]

    def read(name: str) -> bytes:
        with (root / name).open("rb") as handle:
            return handle.read(_PEEK_BYTES)

    return _detect(names, read)


# --- expansion --------------------------------------------------------------


def _unsafe(name: str) -> bool:
    """Reject anything that would write outside the extraction directory.

    `ZipFile.extract` already neutralises these, but a skipped entry that is
    named in the audit trail beats a silently relocated one.
    """
    candidate = PurePath(name.replace("\\", "/"))
    return candidate.is_absolute() or ".." in candidate.parts or name.startswith("/")


@dataclass
class _ExpansionBudget:
    entries: int = 0
    bytes: int = 0
    destinations: set[Path] = field(default_factory=set)


class _ArchiveCollisionError(zipfile.BadZipFile):
    """Two archive members would publish different bytes at one source path."""


def expand_archive(
    archive: Path,
    target: Path,
    progress: Callable[[int, int], None] | None = None,
    depth: int = 0,
    *,
    _budget: _ExpansionBudget | None = None,
) -> list[Path]:
    """Unpack `archive` into `target` and return the files it produced."""
    budget = _budget if _budget is not None else _ExpansionBudget()
    produced: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        entries = [info for info in bundle.infolist() if not info.is_dir()]
        # The bound applies to the entire upload, including every nested zip.
        # A fresh allowance at each level multiplies the advertised limit.
        budget.entries += len(entries)
        budget.bytes += sum(info.file_size for info in entries)
        if budget.entries > MAX_ARCHIVE_ENTRIES:
            raise ValueError("archive declares too many entries")
        if budget.bytes > MAX_ARCHIVE_EXPANDED_BYTES:
            raise ValueError("archive declares too many bytes")
        target.mkdir(parents=True, exist_ok=True)
        produced.extend(_extract_entries(bundle, entries, target, budget, progress))
    nested = [path for path in produced if path.suffix.casefold() in ARCHIVE_SUFFIXES]
    if depth + 1 < MAX_ARCHIVE_DEPTH:
        for inner in nested:
            produced.extend(_expand_nested(inner, depth, budget))
    return produced


def _extract_entries(
    bundle: zipfile.ZipFile,
    entries: list[zipfile.ZipInfo],
    target: Path,
    budget: _ExpansionBudget,
    progress: Callable[[int, int], None] | None,
) -> list[Path]:
    produced: list[Path] = []
    total = len(entries)
    for index, info in enumerate(entries, 1):
        if _unsafe(info.filename):
            logger.warning("intake: skipped unsafe archive entry %r", info.filename)
            continue
        written = Path(bundle.extract(info, target))
        destination = written.resolve()
        if destination in budget.destinations:
            # Nothing is queued until expansion succeeds. Reject the
            # ambiguous bundle and retain its original zip for recovery,
            # instead of silently importing only the last overwritten file.
            raise _ArchiveCollisionError("archive members share a destination")
        budget.destinations.add(destination)
        produced.append(written)
        if progress and (index % 200 == 0 or index == total):
            progress(index, total)
    return produced


def _expand_nested(inner: Path, depth: int, budget: _ExpansionBudget) -> list[Path]:
    try:
        return expand_archive(inner, inner.with_suffix(""), depth=depth + 1, _budget=budget)
    except _ArchiveCollisionError:
        raise
    except (zipfile.BadZipFile, OSError):
        logger.warning("intake: nested archive %s could not be expanded", inner.name)
        return []


# --- the queue --------------------------------------------------------------


def enqueue(
    settings: Settings,
    *,
    owner_user_id: str,
    patient_id: str,
    batch_id: str,
    kind: str,
    filename: str,
    source_path: Path | str | None = None,
    byte_size: int | None = None,
    adapter_key: str | None = None,
    document_id: str | None = None,
    start: bool = True,
) -> str:
    job_id = str(uuid.uuid4())
    with transaction(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, adapter_key, filename,
                   source_path, byte_size, state, detail_key, document_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'intake.step_waiting', ?, ?)""",
            (
                job_id, owner_user_id, patient_id, batch_id, kind, adapter_key, filename,
                str(source_path) if source_path else None, byte_size, document_id, utc_now(),
            ),
        )
    if start:
        start_worker(settings)
    return job_id


def record_rejected(
    settings: Settings,
    *,
    owner_user_id: str,
    patient_id: str,
    batch_id: str,
    filename: str,
    detail_key: str,
    byte_size: int | None = None,
    source_path: Path | None = None,
) -> str:
    """A file the door turned away, written into the queue rather than counted.

    With one file an error banner was enough.  With forty, "3 files were
    rejected" is not an answer - the reader needs to know which three and why,
    beside the ones that worked.

    ``source_path`` is set when the rejected file stays on disk: the extraction
    validator treats a kept file with no row naming it as a lost import, and
    the recorded path is what turns that error into a documented rejection.
    """
    assert detail_key in DETAIL_KEYS, detail_key
    job_id = str(uuid.uuid4())
    with transaction(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, filename, byte_size,
                   state, detail_key, source_path, created_at, finished_at
               ) VALUES (?, ?, ?, ?, 'document', ?, ?, 'failed', ?, ?, ?, ?)""",
            (
                job_id, owner_user_id, patient_id, batch_id, filename, byte_size,
                detail_key, str(source_path) if source_path else None,
                utc_now(), utc_now(),
            ),
        )
    return job_id


def record_duplicate(
    settings: Settings,
    *,
    owner_user_id: str,
    patient_id: str,
    batch_id: str,
    filename: str,
    document_id: str,
    byte_size: int | None = None,
) -> str:
    """A file already held, recorded so the queue can link to the copy on file."""
    job_id = str(uuid.uuid4())
    with transaction(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, filename, byte_size,
                   state, detail_key, document_id, created_at, finished_at
               ) VALUES (?, ?, ?, ?, 'document', ?, ?, 'skipped', 'intake.done_duplicate', ?, ?, ?)""",
            (
                job_id, owner_user_id, patient_id, batch_id, filename, byte_size,
                document_id, utc_now(), utc_now(),
            ),
        )
    return job_id


def _mark(settings: Settings, job_id: str, detail_key: str) -> None:
    assert detail_key in DETAIL_KEYS, detail_key
    with transaction(settings) as connection:
        connection.execute(
            "UPDATE upload_jobs SET detail_key=? WHERE id=?", (detail_key, job_id)
        )


def _finish(
    settings: Settings,
    job_id: str,
    state: str,
    detail_key: str,
    *,
    document_id: str | None = None,
    import_id: str | None = None,
    observations: int = 0,
) -> None:
    assert detail_key in DETAIL_KEYS, detail_key
    with transaction(settings) as connection:
        connection.execute(
            """UPDATE upload_jobs SET state=?, detail_key=?, finished_at=?,
                   document_id=COALESCE(?, document_id), import_id=COALESCE(?, import_id),
                   observation_count=? WHERE id=?""",
            (state, detail_key, utc_now(), document_id, import_id, observations, job_id),
        )


def _claim(settings: Settings):
    """Take the oldest queued job, or None.

    Claiming with a conditional update rather than a plain read means a second
    process running the same database cannot start the same file twice.
    """
    with transaction(settings, immediate=True) as connection:
        row = connection.execute(
            "SELECT * FROM upload_jobs WHERE state='queued' ORDER BY created_at, rowid LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        taken = connection.execute(
            """UPDATE upload_jobs SET state='running', started_at=?, detail_key='intake.step_reading'
               WHERE id=? AND state='queued'""",
            (utc_now(), row["id"]),
        ).rowcount
        return row if taken else False


def reclaim_abandoned_jobs(settings: Settings) -> int:
    """Return jobs whose worker died to the queue, at application start.

    `_claim` moves a job to `running` and only ever looks for `queued` again, so
    a job in flight when the process ends is claimed by a worker that no longer
    exists and nothing will ever pick it up.  It stops being work and becomes a
    row that reads "Reading..." in the processing area for good -- one is
    sitting on the sandbox right now, from the container being recreated
    mid-rescan.

    Safe because this runs before any worker starts and the queue is drained by
    one thread per database: nothing else can be legitimately `running` yet.
    Re-reading a document that had already finished is idempotent, so the worst
    case of reclaiming one job too many is that it is read twice.
    """
    with transaction(settings) as connection:
        reclaimed = connection.execute(
            """UPDATE upload_jobs SET state='queued', started_at=NULL,
                   detail_key='intake.step_waiting' WHERE state='running'"""
        ).rowcount
    if reclaimed:
        logger.info("intake: returned %d abandoned job(s) to the queue", reclaimed)
    return reclaimed


def _pending(settings: Settings) -> bool:
    with connect(settings) as connection:
        return (
            connection.execute("SELECT 1 FROM upload_jobs WHERE state='queued' LIMIT 1").fetchone()
            is not None
        )


# --- job handlers -----------------------------------------------------------


def _discard_upload_copy(settings: Settings, path: Path) -> None:
    """Remove arrived bytes that nothing in the record points at any more.

    Two callers.  `unchanged` means the pipeline recognised these exact bytes
    under this exact name and wrote nothing, so the copy is referenced by no
    document row -- and `validate_source_extraction.py` reports every such file
    as an error, correctly, because a file in `sources/` that no document points
    at is indistinguishable from an upload that was lost.  Re-uploading a zip
    produced one of these per document inside it.  An expanded archive is the
    other: once it is unpacked, every byte of it is on disk in the expansion,
    which is what the record's rows actually name.

    Only under `sources/uploads`, and never the dated arrivals folder itself.
    The CLI hands `ingest_file` curated files from the sources root, which are
    the record's own evidence and are not this function's to delete, and the
    upload handler may be writing into this month's folder right now.
    `duplicate` is deliberately not included: that path creates a document row
    pointing at the new file, so those bytes are still the record's.
    """
    uploads = (settings.source_dir / "uploads").resolve()
    path = path.resolve()
    if not path.is_relative_to(uploads):
        return
    # The worker can die after ingestion commits but before the job finishes.
    # Retrying then returns `unchanged` for the *original* source path, rather
    # than a new upload copy. Never delete evidence a document still names.
    with connect(settings) as connection:
        for row in connection.execute("SELECT source_path FROM documents"):
            if resolve_source_path(settings, str(row["source_path"])).resolve() == path:
                return
    try:
        path.unlink(missing_ok=True)
        folder = path.parent
        while folder.parent != uploads and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    except OSError:
        logger.warning("intake: could not remove the re-uploaded copy of %s", path.name)


def discard_upload_tree(settings: Settings, path: Path) -> None:
    """Remove an expansion directory nothing points at any more.

    A device export is re-read from the directory it was unpacked into, so the
    tree has to survive the import that created it -- `device_events.source_file`
    names an ECG waveform inside it, and the viewer reads that file.  What does
    not have to survive is the tree a *superseded* import was read from: when
    the same export is uploaded again it unpacks to a new directory and the
    import row moves to it, leaving two or three gigabytes of Apple Health that
    nothing in the database mentions.

    Same containment rule as `_discard_upload_copy`, and the same reason.
    """
    uploads = (settings.source_dir / "uploads").resolve()
    path = path.resolve()
    if not path.is_dir() or not path.is_relative_to(uploads) or path == uploads:
        return
    try:
        shutil.rmtree(path)
        folder = path.parent
        while folder.parent != uploads and folder != uploads and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    except OSError:
        logger.warning("intake: could not remove the superseded expansion of %s", path.name)


def _run_document(settings: Settings, job) -> None:
    path = Path(str(job["source_path"]))
    if not path.is_file():
        _finish(settings, job["id"], "failed", FAILED_MISSING)
        return
    # The upload doors check SHA-256 against the record, but not against files
    # still in the queue: the same scan sent twice in one Telegram album, or
    # sent again while the first copy waited its turn, reached the pipeline
    # second and was filed as another document.  The queue is drained in
    # order, so by now the first copy is in the record and this one is not.
    digest = file_sha256(path)
    with connect(settings) as connection:
        held = connection.execute(
            """SELECT id FROM documents WHERE owner_user_id=? AND sha256=? AND original_filename<>?
               ORDER BY imported_at LIMIT 1""",
            (job["owner_user_id"], digest, path.name),
        ).fetchone()
    # Same bytes under the same name is ingest_file's own "unchanged" case,
    # which also covers a retried job whose import had already committed.
    if held:
        _discard_upload_copy(settings, path)
        _finish(settings, job["id"], "skipped", "intake.done_duplicate", document_id=str(held["id"]))
        return
    result = ingest_file(settings, job["owner_user_id"], job["patient_id"], path)
    action = str(result.get("action"))
    count = int(result.get("observations") or 0) + int(result.get("immunizations") or 0)
    if action == "unchanged":
        _discard_upload_copy(settings, path)
    detail = {
        "duplicate": "intake.done_duplicate",
        "unchanged": "intake.done_unchanged",
    }.get(action, "intake.done_imported" if count else "intake.done_no_values")
    _finish(
        settings,
        job["id"],
        "done",
        detail,
        document_id=str(result["document_id"]),
        observations=count,
    )
    if action == "ingested":
        _relate_upload_parts(settings, str(job["owner_user_id"]), str(result["document_id"]))
        # After _finish, so a slow or absent Paperless never holds the queue's
        # progress display; push_document checks the feature and the person's
        # opt-in itself.
        #
        # Guarded here as well as inside push_document because this call sits
        # *after* the job was marked done, inside run_job's blanket handler:
        # anything escaping would re-finish the job as failed with zero
        # observations, reporting a good import — values already in the record
        # — as broken, and inviting the person to upload it again.  Mirroring
        # to an optional external archive is never worth that.
        try:
            paperless.push_document(settings, str(result["document_id"]))
        except Exception:  # noqa: BLE001
            logger.warning(
                "paperless: mirroring document %s failed after a successful ingest",
                result["document_id"], exc_info=True,
            )


def _relate_upload_parts(settings: Settings, owner_user_id: str, document_id: str) -> None:
    """Relate an image once its upload job names it.

    Screenshots of one report are recognised by the upload batch they came in
    (`part_of`), and the import itself runs before the job is linked to the
    document, so an image is related again here.  Best effort: a failure
    leaves the document imported and unlinked, never the job failed."""
    try:
        with transaction(settings) as connection:
            row = connection.execute("SELECT mime_type FROM documents WHERE id=?", (document_id,)).fetchone()
            if row and str(row["mime_type"] or "").startswith("image/"):
                record_document_relations(connection, owner_user_id, document_id)
    except Exception:  # noqa: BLE001
        logger.warning("intake: relating upload %s to its batch failed", document_id, exc_info=True)


def _run_device_export(settings: Settings, job) -> None:
    from ..devices import import_device_export

    source = Path(str(job["source_path"]))
    if not source.exists():
        _finish(settings, job["id"], "failed", FAILED_MISSING)
        return
    result = import_device_export(
        settings,
        owner_user_id=str(job["owner_user_id"]),
        patient_id=str(job["patient_id"]),
        vendor_key=str(job["adapter_key"]),
        source=source,
    )
    _finish(
        settings,
        job["id"],
        "done",
        DONE_DEVICE,
        import_id=str(result["import_id"]),
        observations=int(result.get("daily_metrics") or 0),
    )


def _hand_on_device_export(
    settings: Settings, job, archive: Path, root: Path, adapter: str, produced: list[Path]
) -> None:
    """Queue the unpacked device export for its adapter and close this archive row."""
    enqueue(
        settings,
        owner_user_id=str(job["owner_user_id"]),
        patient_id=str(job["patient_id"]),
        batch_id=str(job["batch_id"]),
        kind="device_export",
        adapter_key=adapter,
        filename=str(job["filename"]),
        source_path=root,
        byte_size=job["byte_size"],
        start=False,
    )
    # A device export can carry document-shaped files the import never
    # reads (Garmin ships the account's avatar PNGs). They stay on disk
    # with the rest of the export, so each needs a row naming it — a kept
    # file with no row is what a lost import looks like to the validator.
    for path in produced:
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES:
            record_rejected(
                settings,
                owner_user_id=str(job["owner_user_id"]),
                patient_id=str(job["patient_id"]),
                batch_id=str(job["batch_id"]),
                filename=path.name,
                detail_key="intake.failed_device_archive_member",
                byte_size=path.stat().st_size,
                source_path=path,
            )
    _discard_upload_copy(settings, archive)
    # No count: this row recognised the export and handed it on. The job it
    # created is the one that reports how many measurements arrived, and
    # claiming a number here read as "this archive produced 1 measurement".
    _finish(settings, job["id"], "done", DONE_DEVICE)


def _run_archive(settings: Settings, job) -> None:
    archive = Path(str(job["source_path"]))
    if not archive.is_file():
        _finish(settings, job["id"], "failed", FAILED_MISSING)
        return
    _mark(settings, job["id"], "intake.step_unpacking")
    target = archive.with_name(f"{archive.stem}-{str(job['id'])[:8]}")
    named = str(job["adapter_key"] or "")
    try:
        # A reader who chose the vendor on the form has said something detection
        # can only guess at. Detection still runs, but only to locate the root
        # inside the zip - it does not get to overrule the answer it was given.
        adapter, relative_root = detect_archive_adapter(archive)
        if named:
            relative_root = relative_root if adapter == named else ""
            adapter = named
        produced = expand_archive(archive, target)
    except zipfile.BadZipFile:
        discard_upload_tree(settings, target)
        _finish(settings, job["id"], "failed", "intake.failed_unreadable")
        return
    except ValueError:
        discard_upload_tree(settings, target)
        _finish(settings, job["id"], "failed", "intake.failed_too_big")
        return

    if adapter:
        _hand_on_device_export(settings, job, archive, target / relative_root if relative_root else target,
                               adapter, produced)
        return

    documents = sorted(
        path for path in produced
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
    )
    if not documents:
        # The zip is kept: it is the only evidence of what was uploaded, and a
        # reader looking at "nothing in this archive could be read" will want to
        # open it. Its expansion is what goes, having produced nothing.
        discard_upload_tree(settings, target)
        _finish(settings, job["id"], "failed", "intake.failed_empty")
        return
    for path in documents:
        enqueue(
            settings,
            owner_user_id=str(job["owner_user_id"]),
            patient_id=str(job["patient_id"]),
            batch_id=str(job["batch_id"]),
            kind="document",
            filename=path.name,
            source_path=path,
            byte_size=path.stat().st_size,
            start=False,
        )
    # Every byte of the zip is now on disk unpacked, and it is the expansion the
    # document rows will name. Keeping both doubles the storage of every upload
    # for no second copy of anything -- and for a vendor export that is gigabytes.
    _discard_upload_copy(settings, archive)
    _finish(settings, job["id"], "done", "intake.done_expanded", observations=len(documents))


def _run_rescan(settings: Settings, job) -> None:
    result = reingest_document(settings, str(job["owner_user_id"]), str(job["document_id"]))
    _finish(
        settings,
        job["id"],
        "done",
        "intake.done_rescanned",
        document_id=str(result["document_id"]),
        observations=int(result.get("observations") or 0) + int(result.get("immunizations") or 0),
    )


_HANDLERS = {
    "document": _run_document,
    "archive": _run_archive,
    "device_export": _run_device_export,
    "rescan": _run_rescan,
}


def run_job(settings: Settings, job) -> None:
    """One job, start to finish.  Never raises: a bad file stops itself, not the batch.

    `LookupError` and `ValueError` used to be reported as "that format is not
    accepted here", which reads as a job for the person holding the file.  They
    are not: the deliberate rejections raise where they are decided - the door
    checks the suffix, `_run_archive` catches its own limits - so what is left
    arriving here is `zip(..., strict=True)` disagreeing about page counts, a
    bare `int()` on something that is not a number, a page missing from
    `page_to_report`.  Every one of those is this software's bug, and telling
    the reader to convert their file sends them to fix it in the one place it
    cannot be fixed.
    """
    try:
        _HANDLERS[str(job["kind"])](settings, job)
    except FileNotFoundError:
        # The one failure that said nothing anywhere.  A server whose database
        # had been placed on the volume without `sources/` beside it failed 124
        # re-reads in a row, wrote not one line about it, and the only visible
        # effect was that the "files read by an older parser" count never moved.
        # The job id, not the filename: a person's own filenames are diagnostic
        # of what they were tested for, and `upload_jobs` already holds it.
        logger.warning(
            "intake: %s job %s found no file to read (document %s)",
            job["kind"], job["id"], job["document_id"],
        )
        _finish(settings, job["id"], "failed", FAILED_MISSING)
    except RereadRefused as refused:
        # A re-read that stopped itself before it could damage the record:
        # the person is told why, and that nothing was changed.
        logger.warning("intake: %s job %s refused: %s", job["kind"], job["id"], refused)
        _finish(settings, job["id"], "failed", refused.detail_key)
    except Exception:
        logger.exception("intake: job %s failed", job["id"])
        _finish(settings, job["id"], "failed", "intake.failed_error")


# --- the worker -------------------------------------------------------------


_WORKERS: dict[str, threading.Thread] = {}
_LOCK = threading.Lock()


def _drain(settings: Settings, key: str) -> None:
    while True:
        job = _claim(settings)
        if job is False:  # another worker took it first
            continue
        if job is None:
            # Deciding to stop happens under the same lock that starts a
            # worker, so a job enqueued at this instant either is seen here or
            # starts a replacement thread; it cannot fall between the two.
            with _LOCK:
                if _pending(settings):
                    continue
                _WORKERS.pop(key, None)
                return
        run_job(settings, job)


def start_worker(settings: Settings) -> None:
    """Make sure something is draining this database's queue."""
    key = str(settings.database_path)
    with _LOCK:
        existing = _WORKERS.get(key)
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(target=_drain, args=(settings, key), name="anamna-intake", daemon=True)
        _WORKERS[key] = thread
        thread.start()


def drain_now(settings: Settings) -> None:
    """Run the queue to empty on this thread.  For tests and the CLI."""
    while True:
        job = _claim(settings)
        if job is None:
            return
        if job is not False:
            run_job(settings, job)


# --- reading the queue ------------------------------------------------------


def batch_progress(connection, owner_user_id: str, limit: int = 60) -> dict[str, object]:
    """The queue as the upload page shows it: newest batch first, with totals."""
    rows = [
        dict(row)
        for row in connection.execute(
            """SELECT j.*, d.title document_title, d.clinical_type, v.canonical_name vendor
               FROM upload_jobs j
               LEFT JOIN documents d ON d.id = j.document_id
               LEFT JOIN vendors v ON v.id = d.vendor_id
               WHERE j.owner_user_id=?
               ORDER BY j.created_at DESC, j.rowid DESC LIMIT ?""",
            (owner_user_id, limit),
        )
    ]
    active = sum(1 for row in rows if row["state"] in ("queued", "running"))
    return {
        "jobs": rows,
        "active": active,
        "done": sum(1 for row in rows if row["state"] == "done"),
        "failed": sum(1 for row in rows if row["state"] == "failed"),
        "total": len(rows),
    }


def clear_finished(settings: Settings, owner_user_id: str) -> int:
    """Drop the finished rows, and the bytes of the ones that produced nothing.

    A file that failed is deliberately kept on disk -- the queue says so, and a
    person who uploaded the wrong scan wants to see which one it was.  But the
    queue row is the only thing naming it, so clearing the queue without
    clearing the file leaves bytes under `sources/` that nothing in the record
    mentions, which `validate_source_extraction.py` reports as a blocking error
    for good.  One corrupt upload made the project's own cleanliness check
    permanently red, with no way to answer it from the interface.

    Only failed rows, and only their own upload copy: a `done` row's file is
    named by a document, and a `skipped` duplicate never had bytes of its own.
    """
    with transaction(settings) as connection:
        abandoned = [
            str(row["source_path"])
            for row in connection.execute(
                """SELECT source_path FROM upload_jobs
                   WHERE owner_user_id=? AND state='failed' AND source_path IS NOT NULL""",
                (owner_user_id,),
            )
        ]
        cleared = connection.execute(
            "DELETE FROM upload_jobs WHERE owner_user_id=? AND state IN ('done','failed','skipped')",
            (owner_user_id,),
        ).rowcount
    for path in abandoned:
        _discard_upload_copy(settings, Path(path))
    return cleared
