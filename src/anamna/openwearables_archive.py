"""Compact archive of OpenWearables raw samples.

One zlib-compressed JSON blob per (owner, server, remote account, UTC day,
series type) holds the exact former per-sample rows
``[sample_key, timestamp, received_at, payload_json]``, so device, source app,
original timestamp and every unmapped field survive byte for byte.

From migration 040 on nothing writes to the per-sample table
(``openwearables_raw_samples``, migration 027).  :func:`run_conversion` copies
it out in the background, a batch of account-days per short write
transaction, each day read back tuple-for-tuple before it is *claimed* in
``openwearables_raw_conversion`` together with the old rows' fingerprint.  A
claimed day's old rows are superseded and never read again; write paths claim
the days they touch first.  The ledger *is* the progress, so a restart carries
on where it stopped.

The old rows are never deleted one by one: their primary key is a hash, so
every deleted row dirties a random page of a 1.6 GB index (measured: a 0.5 s
batch then took 14 s to commit).  Once everything is copied, ``reclaim`` drops
the whole table and vacuums, a documented maintenance step.

    uv run python -m anamna.openwearables_archive status
    uv run python -m anamna.openwearables_archive convert
    uv run python -m anamna.openwearables_archive verify
    uv run python -m anamna.openwearables_archive fingerprint OUT.json [--db PATH]
    uv run python -m anamna.openwearables_archive compare BEFORE.json AFTER.json
    uv run python -m anamna.openwearables_archive reclaim --yes
"""
from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import sqlite3
import sys
import threading
import time
import zlib
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from .config import Settings, get_settings
from .db import connect, transaction, utc_now

logger = logging.getLogger("anamna.openwearables_archive")

LEGACY = "openwearables_raw_samples"
#: Work per write transaction, then the write lock is released for this long.
#: Measured on a copy of the 7.4 M-row record at 0.5 s steps: 237 s in all,
#: other writers waited 38 ms median but 5.1 s at worst on a contended disk,
#: against a 5 s busy timeout; a shorter step halves that tail.
STEP_SECONDS = 0.25
PAUSE_SECONDS = 0.25

Row = tuple[str, str, str, str]  # sample_key, timestamp (UTC ISO), received_at, payload_json
_ACCOUNT = "owner_user_id=? AND server_url=? AND remote_user_id=?"
#: Old rows of days the archive has not claimed: the only ones still read.
_UNCLAIMED = """NOT EXISTS (SELECT 1 FROM openwearables_raw_conversion c WHERE c.owner_user_id=l.owner_user_id
    AND c.server_url=l.server_url AND c.remote_user_id=l.remote_user_id AND c.day=substr(l.timestamp,1,10))"""


class ArchiveMismatch(RuntimeError):
    """What was written does not read back as what was there."""


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _value(payload_json: str) -> float:
    value = json.loads(payload_json).get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def fingerprint(rows: Iterable[Row]) -> tuple[int, float, str]:
    """Count, exact (order-independent) value sum and digest of every field."""
    rows = sorted(rows)
    digest = hashlib.sha256()
    for row in rows:
        digest.update("\x1f".join(row).encode() + b"\n")
    return len(rows), math.fsum(_value(row[3]) for row in rows), digest.hexdigest()


def _encode(rows: Iterable[Row]) -> bytes:
    ordered = sorted(rows, key=lambda row: (row[1], row[0]))
    return zlib.compress(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode(), 6)


def _decode(blob: bytes) -> list[Row]:
    return [tuple(row) for row in json.loads(zlib.decompress(blob))]


def legacy_present(db) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (LEGACY,)).fetchone() is not None


def _read(db, account: tuple, day: str, series: str) -> dict[str, Row]:
    row = db.execute(f"SELECT samples FROM openwearables_raw_days WHERE {_ACCOUNT} AND day=? AND series_type=?",
                     (*account, day, series)).fetchone()
    return {r[0]: r for r in _decode(row[0])} if row else {}


def _write(db, account: tuple, day: str, series: str, rows: dict[str, Row]) -> None:
    if not rows:
        db.execute(f"DELETE FROM openwearables_raw_days WHERE {_ACCOUNT} AND day=? AND series_type=?",
                   (*account, day, series))
        return
    values = list(rows.values())
    db.execute("""INSERT INTO openwearables_raw_days(owner_user_id,server_url,remote_user_id,day,series_type,
            sample_count,value_sum,received_at,samples) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner_user_id,server_url,remote_user_id,day,series_type) DO UPDATE SET
            sample_count=excluded.sample_count,value_sum=excluded.value_sum,
            received_at=excluded.received_at,samples=excluded.samples""",
        (*account, day, series, len(values), math.fsum(_value(r[3]) for r in values),
         max(r[2] for r in values), _encode(values)))


def _legacy_day(db, account: tuple, day: str, columns: str = "count(*)"):
    # A range on the bare column, never substr(): it stays on ow_samples_window.
    return db.execute(f"SELECT {columns} FROM {LEGACY} WHERE {_ACCOUNT} AND timestamp >= ? AND timestamp < ?",
                      (*account, day, _next_day(day)))


def _claimed(db, account: tuple, day: str) -> bool:
    return db.execute(f"SELECT 1 FROM openwearables_raw_conversion WHERE {_ACCOUNT} AND day=?",
                      (*account, day)).fetchone() is not None


def _claim(db, account: tuple, day: str, before: tuple | None = None, legacy_count: int | None = None) -> None:
    """Make the archive the owner of an account-day while the old table exists.

    ``before`` is the old rows' fingerprint (conversion); a write path passes
    nothing, which also clears a fingerprint the day no longer matches.
    """
    if _claimed(db, account, day):
        db.execute(f"""UPDATE openwearables_raw_conversion SET sample_count=NULL,value_sum=NULL,digest=NULL,
            converted_at=? WHERE {_ACCOUNT} AND day=?""", (utc_now(), *account, day))
        return
    count = _legacy_day(db, account, day).fetchone()[0] if legacy_count is None else legacy_count
    if not count:
        return  # nothing old to supersede
    db.execute("INSERT INTO openwearables_raw_conversion VALUES (?,?,?,?,?,?,?,?)",
               (*account, day, *(before or (None, None, None)), utc_now()))
    db.execute("UPDATE openwearables_raw_totals SET legacy_done=legacy_done+? WHERE owner_user_id=?", (count, account[0]))


def convert_day(db, account: tuple, day: str) -> int:
    """Copy one unclaimed account-day into the archive; returns old rows copied.

    Runs inside the caller's write transaction, so a failed read-back rolls
    the whole batch back and nothing is claimed.
    """
    if _claimed(db, account, day):
        return 0
    legacy = _legacy_day(db, account, day, "series_type,sample_key,timestamp,received_at,payload_json").fetchall()
    if not legacy:
        return 0
    by_series: dict[str, dict[str, Row]] = defaultdict(dict)
    for series, *row in legacy:
        by_series[series][row[0]] = tuple(row)
    for series, rows in by_series.items():
        existing = _read(db, account, day, series)
        # Only a write path could have put an archive copy here, so it is newer.
        _write(db, account, day, series, rows | existing)
        stored = _read(db, account, day, series)
        if any(stored.get(key) != row for key, row in rows.items() if key not in existing):
            raise ArchiveMismatch(f"{account[0]} {day} {series}")
    _claim(db, account, day, fingerprint(tuple(r[1:]) for r in legacy), len(legacy))
    return len(legacy)


def merge_samples(db, account: tuple, rows: Iterable[tuple[str, str, str, str, str]]) -> None:
    """Upsert ``(sample_key, timestamp, series_type, received_at, payload_json)``
    by identity, the receipt path: a correction replaces, never accumulates."""
    groups: dict[tuple[str, str], dict[str, Row]] = defaultdict(dict)
    days: set[str] = set()
    for key, stamp, series, received, payload in rows:
        groups[(stamp[:10], series)][key] = (key, stamp, received, payload)
        days.add(stamp[:10])
    legacy = groups and legacy_present(db)
    if legacy:
        for day in sorted(days):
            convert_day(db, account, day)
    for (day, series), new in groups.items():
        _write(db, account, day, series, _read(db, account, day, series) | new)
    if legacy:
        for day in days:
            _claim(db, account, day)


def replace_window(db, account: tuple, start: str, end: str,
                   rows: Iterable[tuple[str, str, str, str, str]]) -> None:
    """Make UTC days ``start..end`` exactly ``rows`` (the sync path).

    ``rows`` arrive ordered by series then timestamp, so one group is held in
    memory at a time.  Old rows of these days are superseded by claiming the
    days, not deleted (see the module note).
    """
    if legacy_present(db):
        day = start
        while day <= end:
            _claim(db, account, day)
            day = _next_day(day)
    db.execute(f"DELETE FROM openwearables_raw_days WHERE {_ACCOUNT} AND day BETWEEN ? AND ?", (*account, start, end))
    group, held = None, {}
    for key, stamp, series, received, payload in rows:
        if (stamp[:10], series) != group:
            if group:
                _write(db, account, *group, _read(db, account, *group) | held)
            group, held = (stamp[:10], series), {}
        held[key] = (key, stamp, received, payload)
    if group:
        _write(db, account, *group, _read(db, account, *group) | held)


def purge_owner(db, owner_user_id: str) -> None:
    """Erase every archived sample of a local account (relink to another person)."""
    if legacy_present(db):
        # Another person's measurements must not linger even superseded.
        db.execute(f"DELETE FROM {LEGACY} WHERE owner_user_id=?", (owner_user_id,))
    for table in ("openwearables_raw_days", "openwearables_raw_conversion"):
        db.execute(f"DELETE FROM {table} WHERE owner_user_id=?", (owner_user_id,))
    db.execute("UPDATE openwearables_raw_totals SET legacy_base=0,legacy_done=0 WHERE owner_user_id=?", (owner_user_id,))


def iter_samples(db, owner_user_id: str, server_url: str, remote_user_id: str, start_day: str, end_day: str,
                 series_type: str | None = None) -> Iterator[dict]:
    """Every archived sample payload of one account in UTC days
    ``start_day..end_day``, ordered by (day, series, timestamp, identity).

    The one reader of the archive: while the background copy runs it also
    reads the old rows of days not yet claimed.
    """
    account = (owner_user_id, server_url, remote_user_id)
    series_clause = " AND series_type=?" if series_type else ""
    extra = (series_type,) if series_type else ()

    def compact():
        for day, series, blob in db.execute(f"""SELECT day,series_type,samples FROM openwearables_raw_days
                WHERE {_ACCOUNT} AND day BETWEEN ? AND ?{series_clause} ORDER BY day,series_type""",
                (*account, start_day, end_day, *extra)):
            for key, stamp, _received, payload in _decode(blob):
                yield day, series, stamp, key, payload

    def legacy():
        if not legacy_present(db):
            return
        yield from sorted(
            (stamp[:10], series, stamp, key, payload) for series, key, stamp, payload in db.execute(
                f"""SELECT series_type,sample_key,timestamp,payload_json FROM {LEGACY} l WHERE {_ACCOUNT}
                AND timestamp >= ? AND timestamp < ?{series_clause} AND {_UNCLAIMED}""",
                (*account, start_day, _next_day(end_day), *extra)))

    for *_ignored, payload in heapq.merge(compact(), legacy()):
        yield json.loads(payload)


def sample_day_span(db, owner_user_id: str, server_url: str, remote_user_id: str) -> tuple[str | None, str | None]:
    """First and last UTC day holding any archived sample of one account --
    compact days and, while the background copy runs, the old rows too."""
    account = (owner_user_id, server_url, remote_user_id)
    low, high = db.execute(f"SELECT MIN(day), MAX(day) FROM openwearables_raw_days WHERE {_ACCOUNT}", account).fetchone()
    if legacy_present(db):
        old_low, old_high = db.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM {LEGACY} WHERE {_ACCOUNT}", account).fetchone()
        days = [d for d in (low, high, old_low and old_low[:10], old_high and old_high[:10]) if d]
        return (min(days), max(days)) if days else (None, None)
    return low, high


def totals(db, owner_user_id: str | None = None) -> dict:
    """Samples retained, from maintained counters — never a table scan.

    ``samples`` is None only while the background job is still taking its
    one-off count of an owner's old rows (the first minute after deploy).
    """
    where, params = (" WHERE owner_user_id=?", (owner_user_id,)) if owner_user_id else ("", ())
    present = legacy_present(db)
    # An uncounted owner with nothing in the old table (one index seek) has
    # nothing left there; only a real backlog is "counting".
    pending = f"legacy_base IS NULL AND EXISTS (SELECT 1 FROM {LEGACY} l WHERE l.owner_user_id=t.owner_user_id)" \
        if present else "0"
    samples, unknown, remaining = db.execute(
        f"""SELECT coalesce(sum(samples),0), coalesce(sum({pending}),0),
            coalesce(sum(max(coalesce(legacy_base,0)-legacy_done,0)),0) FROM openwearables_raw_totals t{where}""",
        params).fetchone()
    if not present:
        return {"samples": samples, "compacting": False}
    return {"samples": None if unknown else samples + remaining, "compacting": bool(unknown or remaining)}


def _init_base(settings: Settings) -> None:
    """Count each uncounted owner's old rows, a read outside the write lock.

    The old table only ever shrinks by a purge, which sets the base itself,
    so the count cannot go stale.
    """
    with connect(settings) as db:
        owners = [r[0] for r in db.execute("SELECT owner_user_id FROM openwearables_raw_totals WHERE legacy_base IS NULL")]
        bases = {owner: db.execute(f"SELECT count(*) FROM {LEGACY} WHERE owner_user_id=?", (owner,)).fetchone()[0]
                 for owner in owners}
    with transaction(settings, immediate=True) as db:
        for owner, base in bases.items():
            db.execute("UPDATE openwearables_raw_totals SET legacy_base=? WHERE owner_user_id=? AND legacy_base IS NULL",
                       (base, owner))


def next_unconverted(db, after: tuple | None = None) -> tuple | None:
    """``(account, day)`` of the first unclaimed old day at or after ``after``."""
    key = after or ("", "", "", "")
    while True:
        row = db.execute(f"""SELECT owner_user_id,server_url,remote_user_id,timestamp FROM {LEGACY}
            WHERE (owner_user_id,server_url,remote_user_id,timestamp) >= (?,?,?,?)
            ORDER BY owner_user_id,server_url,remote_user_id,timestamp LIMIT 1""", key).fetchone()
        if row is None:
            return None
        account, day = tuple(row[:3]), row[3][:10]
        if not _claimed(db, account, day):
            return account, day
        key = (*account, _next_day(day))


def convert_step(settings: Settings, budget: float = STEP_SECONDS, cursor: tuple | None = None) -> tuple | None:
    """Copy account-days (at least one) for about ``budget`` seconds in one
    write transaction; returns the cursor to resume from, None once done.

    This connection alone commits without an fsync (WAL + synchronous=NORMAL):
    a power cut can only undo the last batch, which simply runs again.
    """
    with connect(settings) as db:
        if not legacy_present(db):
            return None
        if db.execute(f"SELECT 1 FROM {LEGACY} LIMIT 1").fetchone() is None:
            # Never held anything (a fresh install): dropping it is instant.
            db.execute("DROP INDEX IF EXISTS ow_samples_window")
            db.execute(f"DROP TABLE {LEGACY}")
            return None
        uncounted = db.execute("SELECT 1 FROM openwearables_raw_totals WHERE legacy_base IS NULL LIMIT 1").fetchone()
    if uncounted:
        _init_base(settings)
    deadline = time.monotonic() + budget
    db = connect(settings)
    try:
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("BEGIN IMMEDIATE")
        while True:
            found = next_unconverted(db, cursor)
            if found is None:
                db.commit()
                logger.info("openwearables archive: every old day is copied; run `reclaim` to drop the old table")
                return None
            account, day = found
            if not convert_day(db, account, day):
                raise ArchiveMismatch(f"unconvertible day {account[0]} {day}")
            cursor = (*account, _next_day(day))
            if time.monotonic() >= deadline:
                db.commit()
                return cursor
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def run_conversion(settings: Settings, stop: threading.Event) -> None:
    """Background thread body: copy the old table out, yielding between steps."""
    cursor = None
    while not stop.is_set():
        try:
            cursor = convert_step(settings, cursor=cursor)
            if cursor is None:
                return
            pause = PAUSE_SECONDS
        except sqlite3.OperationalError as exc:
            # Busy: a missed turn, not a dead thread (sqlite-lock-killed-threads).
            logger.info("openwearables archive: step deferred: %s", exc)
            pause = 5
        except Exception:  # noqa: BLE001 — logged, retried later, never fatal
            logger.exception("openwearables archive: conversion step failed")
            pause = 600
        stop.wait(pause)


def verify(db) -> dict:
    """Compare every converted day with the fingerprint of its old rows.

    Days a sync or delivery replaced since carry no fingerprint and are
    counted as ``replaced``; every other one must match exactly.
    """
    report = {"days": 0, "samples": 0, "matching": 0, "replaced": 0, "mismatched": []}
    for row in db.execute("SELECT * FROM openwearables_raw_conversion"):
        account, day = tuple(row[:3]), row[3]
        report["days"] += 1
        if row[4] is None:
            report["replaced"] += 1
            continue
        report["samples"] += row[4]
        archived = [r for (blob,) in db.execute(f"SELECT samples FROM openwearables_raw_days WHERE {_ACCOUNT} AND day=?",
                                                (*account, day)) for r in _decode(blob)]
        if fingerprint(archived) == (row[4], row[5], row[6]):
            report["matching"] += 1
        else:
            report["mismatched"].append([account[0], day])
    return report


def day_fingerprints(db) -> dict[str, list]:
    """``owner|server|remote|day|series -> [count, value_sum]`` as the record
    reads now: the archive plus old rows of days it has not claimed."""
    result: dict[str, list] = {}
    if legacy_present(db):
        _legacy_day_fingerprints(db, result)
    for owner, server, remote, day, series, blob in db.execute(
            "SELECT owner_user_id,server_url,remote_user_id,day,series_type,samples FROM openwearables_raw_days"):
        decoded = _decode(blob)
        key = "|".join((owner, server, remote, day, series))
        if key in result:  # an unclaimed day can have no archive rows
            raise ArchiveMismatch(f"day in both formats: {key}")
        result[key] = [len(decoded), math.fsum(_value(r[3]) for r in decoded)]
    return result


def _legacy_day_fingerprints(db, result: dict[str, list]) -> None:
    # Index order (no sort of the whole table); one day's groups in memory.
    day_key, groups = None, defaultdict(list)

    def flush():
        for series, values in groups.items():
            result["|".join((*day_key, series))] = [len(values), math.fsum(values)]

    for owner, server, remote, series, stamp, payload in db.execute(
            f"""SELECT owner_user_id,server_url,remote_user_id,series_type,timestamp,payload_json FROM {LEGACY} l
            WHERE {_UNCLAIMED} ORDER BY owner_user_id,server_url,remote_user_id,timestamp"""):
        key = (owner, server, remote, stamp[:10])
        if key != day_key:
            if day_key:
                flush()
            day_key, groups = key, defaultdict(list)
        groups[series].append(_value(payload))
    if day_key:
        flush()


def compare(before: dict[str, list], after: dict[str, list]) -> dict:
    keys = set(before) | set(after)
    differing = sorted(k for k in keys if before.get(k) != after.get(k))
    return {"groups_before": len(before), "groups_after": len(after),
            "samples_before": sum(v[0] for v in before.values()), "samples_after": sum(v[0] for v in after.values()),
            "differing": len(differing), "differing_days": differing[:200]}


def status(db) -> dict:
    page = db.execute("PRAGMA page_size").fetchone()[0]
    present = legacy_present(db)
    archived = db.execute("SELECT count(*),coalesce(sum(sample_count),0),coalesce(sum(length(samples)),0) FROM openwearables_raw_days").fetchone()
    return {"legacy_table": present, "conversion_complete": not present or next_unconverted(db) is None,
            "claimed_days": db.execute("SELECT count(*) FROM openwearables_raw_conversion").fetchone()[0],
            "archive_rows": archived[0], "archive_samples": archived[1], "archive_blob_bytes": archived[2],
            "totals": totals(db), "file_bytes": db.execute("PRAGMA page_count").fetchone()[0] * page,
            "free_bytes": db.execute("PRAGMA freelist_count").fetchone()[0] * page}


def reclaim(settings: Settings) -> dict:
    """Drop the fully copied old table and VACUUM the file.

    Holds the write lock throughout (pages are still served: readers keep
    working in WAL mode) and needs free disk about the size of the live data.
    Refuses while any old day is uncopied or any copied day mismatches.
    """
    with connect(settings) as db:
        result = {"file_bytes_before": status(db)["file_bytes"]}
        if legacy_present(db):
            if next_unconverted(db) is not None:
                raise SystemExit("conversion still running: an old day is not copied yet")
            report = verify(db)
            if report["mismatched"]:
                raise SystemExit(f"verification failed on {len(report['mismatched'])} days; nothing dropped")
            began = time.monotonic()
            db.execute("DROP INDEX IF EXISTS ow_samples_window")
            db.execute(f"DROP TABLE {LEGACY}")
            result["drop_seconds"] = round(time.monotonic() - began, 1)
        began = time.monotonic()
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result["vacuum_seconds"] = round(time.monotonic() - began, 1)
        after = status(db)
    return result | {"file_bytes_after": after["file_bytes"], "free_bytes_after": after["free_bytes"]}


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "status"
    settings = get_settings()
    if "--db" in argv:
        settings = replace(settings, database_path=Path(argv[argv.index("--db") + 1]))
    out = sys.stdout
    if command == "convert":
        cursor = convert_step(settings, budget=5.0)
        while cursor:
            with connect(settings) as db:
                print(json.dumps({"cursor_day": cursor[3], "totals": totals(db)}), file=out, flush=True)
            cursor = convert_step(settings, budget=5.0, cursor=cursor)
        result = {"done": True}
    elif command == "reclaim":
        if "--yes" not in argv:
            # Reclaim drops a table and vacuums the live file: a backup comes first.
            print(
                "Refusing to reclaim without --yes. Take a backup first: "
                f"python -c \"import sqlite3;sqlite3.connect('{settings.database_path}')"
                ".backup(sqlite3.connect('backup.sqlite3'))\"",
                file=sys.stderr,
            )
            return 2
        result = reclaim(settings)
    elif command == "compare":
        result = compare(json.loads(Path(argv[1]).read_text()), json.loads(Path(argv[2]).read_text()))
    else:
        uri = f"file:{settings.database_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            if command == "verify":
                result = verify(db)
            elif command == "fingerprint":
                data = day_fingerprints(db)
                Path(argv[1]).write_text(json.dumps(data))
                result = {"groups": len(data), "samples": sum(v[0] for v in data.values()), "written": argv[1]}
            else:
                result = status(db)
    print(json.dumps(result, indent=2), file=out)
    return 0 if not result.get("mismatched") and not result.get("differing") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
