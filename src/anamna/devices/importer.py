from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..config import Settings
from ..db import connect, migrate, utc_now
from ..ingest.intake import discard_upload_tree
from ..ingest.pipeline import ensure_vendor, stable_id
from . import exclusions
from .registry import get_adapter
from .timezone import user_timezone_for
from .units import plausible_aggregates


def _source_files(source: Path, adapter_key: str) -> list[Path]:
    if source.is_file():
        return [source]
    patterns = {
        "apple_health": ("export.xml", "electrocardiograms/*.csv", "workout-routes/*.gpx"),
        "oura": ("**/*.json", "**/*.csv"),
        "garmin": ("**/*.json", "**/*.csv", "**/*.zip"),
        "kardia": ("**/*.pdf",),
    }[adapter_key]
    files: set[Path] = set()
    for pattern in patterns:
        files.update(path for path in source.glob(pattern) if path.is_file())
    return sorted(files, key=lambda path: str(path.relative_to(source)).casefold())


def _fingerprint(source: Path, adapter_key: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total_bytes = sum(path.stat().st_size for path in ([source] if source.is_file() else source.rglob("*") if source.is_dir() else []) if path.is_file())
    files = _source_files(source, adapter_key)
    if not files:
        raise FileNotFoundError(f"No supported {adapter_key} source files under {source}")
    root = source.parent if source.is_file() else source
    for path in files:
        relative = str(path.relative_to(root)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        with path.open("rb", buffering=16 * 1024 * 1024) as handle:
            for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), total_bytes


def _identity_reconciliation(connection, patient_id: str, metadata: dict[str, object]) -> dict[str, object]:
    identity = metadata.get("identity")
    if not isinstance(identity, dict):
        return {}
    patient = connection.execute("SELECT date_of_birth, sex_at_birth FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not patient:
        return {}
    updates: dict[str, str] = {}
    warnings: dict[str, dict[str, object]] = {}
    for column, incoming in (
        ("date_of_birth", identity.get("date_of_birth")),
        ("sex_at_birth", identity.get("biological_sex")),
    ):
        if not incoming or incoming == "notset":
            continue
        current = patient[column]
        if not current:
            updates[column] = str(incoming)
        elif str(current) != str(incoming):
            warnings[column] = {"patient": current, "device_export": incoming}
    if updates:
        assignments = ", ".join(f"{key}=?" for key in updates)
        connection.execute(f"UPDATE patients SET {assignments} WHERE id=?", (*updates.values(), patient_id))
    return {"patient_fields_filled": updates, "identity_warnings": warnings}


#: Re-parses allowed when "not my reading" rules keep changing mid-import.
_RULE_RETRIES = 3


def import_device_export(
    settings: Settings,
    *,
    owner_user_id: str,
    patient_id: str,
    vendor_key: str,
    source: Path,
    preserve_other_imports: bool = False,
) -> dict[str, object]:
    for attempt in range(_RULE_RETRIES):
        try:
            return _import_once(settings, owner_user_id=owner_user_id, patient_id=patient_id, vendor_key=vendor_key,
                                source=source, preserve_other_imports=preserve_other_imports)
        except exclusions.RulesChanged:
            if attempt == _RULE_RETRIES - 1:
                raise
    raise AssertionError("unreachable")


def _import_once(
    settings: Settings,
    *,
    owner_user_id: str,
    patient_id: str,
    vendor_key: str,
    source: Path,
    preserve_other_imports: bool,
) -> dict[str, object]:
    source = source.resolve()
    adapter = get_adapter(vendor_key)
    fingerprint, source_bytes = _fingerprint(source, vendor_key)
    migrate(settings)
    # Readings the person marked as not theirs are skipped as they are added,
    # so a re-import of the same export keeps them out.  A parse takes minutes,
    # so the rules are compared again inside the write; a change re-parses.
    with connect(settings) as connection:
        rules = exclusions.matcher(connection, owner_user_id, vendor_key)
        rules_version = exclusions.version(connection, owner_user_id)
    with exclusions.using(rules):
        parsed = adapter.parse(source, tz=user_timezone_for(settings, owner_user_id))
    if rules is not None:
        parsed.workouts = [item for item in parsed.workouts if not rules.excludes(
            item.source_name, exclusions.WORKOUTS, item.started_at, item.ended_at)]
        parsed.events = [item for item in parsed.events if not rules.excludes(
            item.source_name, exclusions.EVENTS, item.started_at, item.ended_at)]
    # Physically impossible body values never enter the record.
    parsed.aggregates = plausible_aggregates(parsed.aggregates)
    import_id = stable_id("device-import", f"{owner_user_id}:{vendor_key}:{fingerprint}")
    now = utc_now()

    migrate(settings)
    with connect(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if exclusions.version(connection, owner_user_id) != rules_version:
            raise exclusions.RulesChanged(owner_user_id)
        if connection.execute(
            "SELECT 1 FROM patients WHERE id=? AND owner_user_id=?", (patient_id, owner_user_id)
        ).fetchone() is None:
            raise ValueError("The device import patient must belong to its owner")
        # The same export uploaded again unpacks into a fresh directory, and the
        # row below moves to it.  Whatever it pointed at before is then named by
        # nothing at all -- for Apple Health, two or three gigabytes of unpacked
        # export sitting where only the previous copy of this very import used to
        # look.  Read it before the upsert overwrites it.
        superseded = connection.execute(
            "SELECT source_path FROM device_imports WHERE id=?", (import_id,)
        ).fetchone()
        vendor_id = ensure_vendor(connection, adapter.vendor_name, adapter.website)
        reconciliation = _identity_reconciliation(connection, patient_id, parsed.metadata)
        metadata = {**parsed.metadata, **reconciliation}
        connection.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, export_started_at, export_ended_at,
                   raw_record_count, status, metadata_json, imported_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'complete', ?, ?)
               ON CONFLICT(owner_user_id, adapter_key, source_fingerprint) DO UPDATE SET
                   source_path=excluded.source_path, source_bytes=excluded.source_bytes,
                   export_started_at=excluded.export_started_at, export_ended_at=excluded.export_ended_at,
                   raw_record_count=excluded.raw_record_count, status='complete',
                   metadata_json=excluded.metadata_json, imported_at=excluded.imported_at""",
            (
                import_id, owner_user_id, patient_id, vendor_id, vendor_key, str(source),
                fingerprint, source_bytes, parsed.export_started_at, parsed.export_ended_at,
                parsed.raw_record_count, json.dumps(metadata, ensure_ascii=False), now,
            ),
        )
        # Prune by natural key inside the import transaction. A timestamp
        # cannot identify this pass: utc_now has second precision. Retain
        # surviving rows so legacy IDs and links remain stable on a repair.
        fresh_keys = {
            "device_metric_days": {(item.source_name, item.definition.key, item.day) for item in parsed.aggregates},
            "device_workouts": {(item.source_name, item.workout_type, item.started_at) for item in parsed.workouts},
            "device_events": {(item.source_name, item.event_type, item.started_at) for item in parsed.events},
        }
        key_columns = {
            "device_metric_days": "source_name, metric_key, day",
            "device_workouts": "source_name, workout_type, started_at",
            "device_events": "source_name, event_type, started_at",
        }
        previous_rows: set[tuple[str, str]] = set()
        for table in ("device_metric_days", "device_workouts", "device_events"):
            previous = connection.execute(
                f"SELECT id, {key_columns[table]} FROM {table} WHERE import_id=?", (import_id,)
            ).fetchall()
            previous_rows.update((table, row["id"]) for row in previous)
            connection.executemany(
                f"DELETE FROM {table} WHERE id=? AND import_id=?",
                [(row["id"], import_id) for row in previous if tuple(row)[1:] not in fresh_keys[table]],
            )
        # A vendor export is cumulative: next month's Apple Health archive
        # repeats every day this one holds.  So a row is matched on what it
        # measures -- person, source, metric, day -- and the newer export wins,
        # rather than landing beside the old copy as a second answer.  See
        # migrations/012_device_rows_are_owner_scoped.sql.
        connection.executemany(
            f"""INSERT INTO device_metric_days(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   metric_key, metric_name, category, day, aggregation, unit, value,
                   value_min, value_max, value_sum, sample_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, source_name, metric_key, day) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, metric_name=excluded.metric_name,
                   category=excluded.category, aggregation=excluded.aggregation,
                   unit=excluded.unit, value=excluded.value, value_min=excluded.value_min,
                   value_max=excluded.value_max, value_sum=excluded.value_sum,
                   sample_count=excluded.sample_count, created_at=excluded.created_at
                   {"WHERE device_metric_days.import_id=excluded.import_id" if preserve_other_imports else ""}""",
            [
                (
                    stable_id("device-metric-day", f"{owner_user_id}:{item.source_name}:{item.definition.key}:{item.day}"),
                    owner_user_id, patient_id, import_id, item.source_name, item.source_vendor,
                    item.definition.key, item.definition.name, item.definition.category, item.day,
                    item.definition.aggregation, item.definition.unit, item.value,
                    item.value_min, item.value_max, item.value_sum, item.sample_count, now,
                )
                for item in parsed.aggregates
            ],
        )
        connection.executemany(
            f"""INSERT INTO device_workouts(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   workout_type, started_at, ended_at, duration_minutes, energy_kcal,
                   distance_km, route_file, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, source_name, workout_type, started_at) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
                   duration_minutes=excluded.duration_minutes, energy_kcal=excluded.energy_kcal,
                   distance_km=excluded.distance_km, route_file=excluded.route_file,
                   created_at=excluded.created_at
                   {"WHERE device_workouts.import_id=excluded.import_id" if preserve_other_imports else ""}""",
            [
                (
                    stable_id("device-workout", f"{owner_user_id}:{item.source_name}:{item.workout_type}:{item.started_at}"),
                    owner_user_id, patient_id, import_id, item.source_name, item.source_vendor,
                    item.workout_type, item.started_at, item.ended_at, item.duration_minutes,
                    item.energy_kcal, item.distance_km, item.route_file, now,
                )
                for item in parsed.workouts
            ],
        )
        connection.executemany(
            f"""INSERT INTO device_events(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   event_type, started_at, ended_at, value_text, value_numeric, unit,
                   source_file, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, event_type, started_at, source_name) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
                   value_text=excluded.value_text, value_numeric=excluded.value_numeric,
                   unit=excluded.unit, source_file=excluded.source_file,
                   created_at=excluded.created_at
                   {"WHERE device_events.import_id=excluded.import_id" if preserve_other_imports else ""}""",
            [
                (
                    stable_id("device-event", f"{owner_user_id}:{item.event_type}:{item.started_at}:{item.source_name}"),
                    owner_user_id, patient_id, import_id, item.source_name, item.source_vendor,
                    item.event_type, item.started_at, item.ended_at, item.value_text,
                    item.value_numeric, item.unit, item.source_file, now,
                )
                for item in parsed.events
            ],
        )
        current_rows = {
            (table, row["id"])
            for table in ("device_metric_days", "device_workouts", "device_events")
            for row in connection.execute(f"SELECT id FROM {table} WHERE import_id=?", (import_id,))
        }
        removed = len(previous_rows - current_rows)
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
               VALUES (?, ?, 'device_export_imported', 'device_import', ?, ?, ?)""",
            (
                owner_user_id, owner_user_id, import_id,
                json.dumps({
                    "adapter": vendor_key, "source_fingerprint": fingerprint,
                    "preserve_other_imports": preserve_other_imports,
                    "raw_records": parsed.raw_record_count,
                    "daily_metrics": len(parsed.aggregates), "workouts": len(parsed.workouts),
                    "events": len(parsed.events), "superseded_rows": removed,
                }),
                now,
            ),
        )

    # After the commit, and only for a directory this import itself has stopped
    # pointing at: the database is the thing that must be right first, and bytes
    # deleted before it commits are bytes deleted for a rollback.
    previous = Path(str(superseded["source_path"])) if superseded else None
    if previous is not None and previous != source:
        discard_upload_tree(settings, previous)

    return {
        "import_id": import_id,
        "adapter": vendor_key,
        "fingerprint": fingerprint,
        "raw_records": parsed.raw_record_count,
        "daily_metrics": len(parsed.aggregates),
        "workouts": len(parsed.workouts),
        "events": len(parsed.events),
        "export_started_at": parsed.export_started_at,
        "export_ended_at": parsed.export_ended_at,
        "source_vendors": parsed.metadata.get("source_vendor_counts", {}),
        **reconciliation,
    }
