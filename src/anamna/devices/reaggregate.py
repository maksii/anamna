"""Re-cut every stored device day at the person's local midnight (OPS-03).

Idempotent and offline: OpenWearables days are rebuilt from the samples and
records already archived locally (no server request), file exports are
re-read from the copy the import kept.  Each step writes in short chunks, so
the running app keeps serving and syncing while it works.

    python -m anamna.devices.reaggregate --email owner@example.com
    python -m anamna.devices.reaggregate --all --report work/reaggregate.json

Prints a before/after content report per metric and source: day counts, the
sum over all days, how many daily values moved, and the largest monthly sum
change.  Totals of the sum metrics are the invariant to check: a re-cut moves
evening hours between neighbouring days, it never creates or loses a sample.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from ..config import Settings, get_settings
from ..db import connect, migrate, transaction
from . import exclusions
from .timezone import local_day, user_timezone_for

#: Archived OpenWearables datatypes whose days come from a timestamp and can
#: therefore be re-cut locally.  Activity and sleep summaries are dated by the
#: server itself and are left as served.
_ARCHIVED = ("scores", "body_series", "recovery")


def snapshot(settings: Settings, user_id: str) -> dict[tuple[str, str], dict[str, float]]:
    """{(metric_key, source_name): {day: value}} for one person."""
    days: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    with connect(settings) as db:
        for row in db.execute(
            "SELECT metric_key, source_name, day, value, aggregation FROM device_metric_days WHERE owner_user_id=?",
            (user_id,),
        ):
            days[(str(row["metric_key"]), str(row["source_name"]))][str(row["day"])] = float(row["value"])
    return days


def compare(before: dict, after: dict, aggregations: dict[str, str]) -> list[dict[str, object]]:
    report = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, {}), after.get(key, {})
        months_old: dict[str, float] = defaultdict(float)
        months_new: dict[str, float] = defaultdict(float)
        for day, value in old.items():
            months_old[day[:7]] += value
        for day, value in new.items():
            months_new[day[:7]] += value
        changed = sum(1 for day in set(old) | set(new) if abs(old.get(day, 0.0) - new.get(day, 0.0)) > 1e-9)
        if not changed:
            continue
        monthly = max((abs(months_old.get(m, 0.0) - months_new.get(m, 0.0)) for m in set(months_old) | set(months_new)), default=0.0)
        report.append({
            "metric_key": key[0], "source_name": key[1], "aggregation": aggregations.get(key[0], ""),
            "days_before": len(old), "days_after": len(new), "changed_days": changed,
            "sum_before": round(sum(old.values()), 3), "sum_after": round(sum(new.values()), 3),
            "max_monthly_sum_change": round(monthly, 3),
        })
    return report


def _chunks(first: str, last: str, size: int):
    start = date.fromisoformat(first)
    final = date.fromisoformat(last)
    while start <= final:
        end = min(start + timedelta(days=size - 1), final)
        yield start.isoformat(), end.isoformat()
        start = end + timedelta(days=1)


def _recut_raw_days(settings: Settings, ow, archive, user_id: str, import_id, expected, tz, chunk_days: int, pause: float) -> int:
    remote, server = expected[0], expected[1]
    with connect(settings) as db:
        bounds = archive.sample_day_span(db, user_id, server, remote)
    if not (bounds and bounds[0]):
        return 0
    # UTC days: a local day can start the UTC day before and end the UTC
    # day after, so the span is widened by one day on each side.
    first = date.fromisoformat(bounds[0]) - timedelta(days=1)
    last = date.fromisoformat(bounds[1]) + timedelta(days=1)
    chunks = 0
    for start, end in _chunks(first.isoformat(), last.isoformat(), chunk_days):
        with transaction(settings, immediate=True) as db:
            ow.recompute_raw_days(settings, db, user_id, import_id, expected, start, end, tz)
        chunks += 1
        time.sleep(pause)  # let the app's own writers in between chunks
    return chunks


def _with_resting_samples(ow, db, rows: list, user_id: str, server: str, remote: str, start: str, end: str, tz) -> list:
    # The archive kept resting heart rate as rows already cut
    # at UTC; the samples themselves carry the instant.
    rows = [row for row in rows if "recovery_score" in row]
    low, high = local_bounds(start, end, tz)
    for sample in ow._stored_samples(db, user_id, server, remote, low, high, "resting_heart_rate"):
        rows.append({"date": local_day(str(sample.get("timestamp") or ""), tz), "source": sample.get("source"),
                     "timestamp": sample.get("timestamp"), "resting_heart_rate_bpm": ow._api_quantity(sample, "bpm")})
    return rows


def _recut_archived(settings: Settings, ow, user_id: str, import_id, expected, tz, datatype: str, chunk_days: int, pause: float) -> int:
    remote, server = expected[0], expected[1]
    with connect(settings) as db:
        span = db.execute(
            "SELECT MIN(day), MAX(day) FROM openwearables_raw_records WHERE owner_user_id=? AND server_url=? AND remote_user_id=? AND datatype=?",
            (user_id, server, remote, datatype),
        ).fetchone()
    if not span or not span[0]:
        return 0
    archived_rows = 0
    for start, end in _chunks(span[0], (date.fromisoformat(span[1]) + timedelta(days=1)).isoformat(), max(chunk_days, 90)):
        # The window's records plus one day either side: a local day's
        # boundary hours sit in the neighbouring UTC days.
        lower = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        upper = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        with connect(settings) as db:
            rows = [json.loads(payload) for (payload,) in db.execute(
                """SELECT payload_json FROM openwearables_raw_records
                   WHERE owner_user_id=? AND server_url=? AND remote_user_id=? AND datatype=? AND day BETWEEN ? AND ?""",
                (user_id, server, remote, datatype, lower, upper))]
            if datatype == "recovery":
                rows = _with_resting_samples(ow, db, rows, user_id, server, remote, start, end, tz)
        bucket: dict = {}
        with transaction(settings, immediate=True) as db:
            with exclusions.applying(db, user_id):
                ow._MAPPERS[datatype](rows, bucket, tz)
            ow._write_days(settings, user_id, import_id, ow._in_window(bucket.values(), start, end),
                           ow.DATATYPE_KEYS[datatype], start, end, expected, db_connection=db)
        archived_rows += len(rows)
        time.sleep(pause)
    return archived_rows


def reaggregate_openwearables(settings: Settings, user_id: str, *, chunk_days: int = 7, pause: float = 0.2) -> dict[str, int]:
    from .. import openwearables as ow

    if not ow.configured(settings) or ow.linked(settings, user_id) is None:
        return {"skipped": 1}
    expected = ow.account_identity(settings, user_id)
    tz = user_timezone_for(settings, user_id)
    import_id = ow.ensure_envelope(settings, user_id)
    from .. import openwearables_archive as archive

    counts = {"raw_chunks": 0, "archived_rows": 0}
    counts["raw_chunks"] = _recut_raw_days(settings, ow, archive, user_id, import_id, expected, tz, chunk_days, pause)
    for datatype in _ARCHIVED:
        counts["archived_rows"] += _recut_archived(settings, ow, user_id, import_id, expected, tz, datatype, chunk_days, pause)
    return counts


def local_bounds(start: str, end: str, tz) -> tuple[str, str]:
    from .timezone import local_bounds_utc

    return local_bounds_utc(start, end, tz)


def reimport_files(settings: Settings, user_id: str) -> list[dict[str, object]]:
    """Re-read every file export that still owns rows, from the kept copy.

    The same file has the same fingerprint, so the importer updates its own
    rows in place and prunes the days it no longer produces; rows another
    import owns are left alone.  A superseded export (no rows left) is skipped:
    re-reading it would only resurrect what a newer export replaced.
    """
    from .importer import import_device_export

    with connect(settings) as db:
        imports = db.execute(
            """SELECT di.id, di.adapter_key, di.source_path, di.patient_id,
                      (SELECT COUNT(*) FROM device_metric_days d WHERE d.import_id=di.id) rows_owned
               FROM device_imports di
               WHERE di.owner_user_id=? AND di.adapter_key IN ('apple_health', 'oura', 'garmin', 'kardia')""",
            (user_id,),
        ).fetchall()
    results = []
    for item in imports:
        source = Path(str(item["source_path"]))
        entry = {"import_id": item["id"], "adapter": item["adapter_key"], "rows_owned": item["rows_owned"]}
        if not item["rows_owned"]:
            results.append({**entry, "status": "skipped_superseded"})
            continue
        if not source.exists():
            results.append({**entry, "status": "skipped_source_missing", "source_path": str(source)})
            continue
        result = import_device_export(
            settings, owner_user_id=user_id, patient_id=str(item["patient_id"]),
            vendor_key=str(item["adapter_key"]), source=source, preserve_other_imports=True,
        )
        results.append({**entry, "status": "reimported", "daily_metrics": result["daily_metrics"]})
    return results


def run(settings: Settings, user_id: str, *, chunk_days: int = 7, files: bool = True) -> dict[str, object]:
    with connect(settings) as db:
        aggregations = dict(db.execute(
            "SELECT metric_key, MAX(aggregation) FROM device_metric_days WHERE owner_user_id=? GROUP BY metric_key", (user_id,)))
    before = snapshot(settings, user_id)
    started = time.time()
    ow_counts = reaggregate_openwearables(settings, user_id, chunk_days=chunk_days)
    file_results = reimport_files(settings, user_id) if files else []
    # No cache to drop here: the app's device memo is keyed on the newest
    # `created_at` of the person's rows, which every write above advanced.
    after = snapshot(settings, user_id)
    return {
        "user_id": user_id, "seconds": round(time.time() - started, 1),
        "openwearables": ow_counts, "files": file_results,
        "changes": compare(before, after, aggregations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email")
    who.add_argument("--all", action="store_true")
    parser.add_argument("--chunk-days", type=int, default=7)
    parser.add_argument("--no-files", action="store_true", help="skip re-reading file exports")
    parser.add_argument("--report", help="write the full JSON report here")
    args = parser.parse_args(argv)
    settings = get_settings()
    migrate(settings)
    with connect(settings) as db:
        users = db.execute(
            "SELECT id, email FROM users" + ("" if args.all else " WHERE email=?"), () if args.all else (args.email,)
        ).fetchall()
    if not users:
        print("no such user", file=sys.stderr)
        return 1
    reports = []
    for user in users:
        report = run(settings, str(user["id"]), chunk_days=args.chunk_days, files=not args.no_files)
        report["email"] = user["email"]
        reports.append(report)
        moved = {}
        for change in report["changes"]:
            moved[change["metric_key"]] = moved.get(change["metric_key"], 0) + int(change["changed_days"])
        print(json.dumps({"email": user["email"], "seconds": report["seconds"], "openwearables": report["openwearables"],
                          "files": report["files"], "changed_days_by_metric": moved}, ensure_ascii=False))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
