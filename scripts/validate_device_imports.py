"""Read-only validation for the direct Garmin and Kardia imports."""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anamna.config import ROOT, get_settings, resolve_source_path
from anamna.devices.importer import _fingerprint
from anamna.devices.registry import get_adapter

_FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


def _read_fit_definition(
    data: bytes, position: int, header: int
) -> tuple[tuple[int, list[tuple[int, int, int]], str], int]:
    """One FIT definition message; ``position`` is just past its header byte."""
    position += 1
    endian = ">" if data[position] else "<"
    position += 1
    global_number = struct.unpack_from(endian + "H", data, position)[0]
    position += 2
    field_count = data[position]
    position += 1
    fields = []
    for _ in range(field_count):
        number, size, base_type = data[position : position + 3]
        position += 3
        fields.append((number, size, base_type))
    if header & 0x20:
        developer_count = data[position]
        position += 1 + developer_count * 3
    return (global_number, fields, endian), position


def _read_fit_weight_fields(
    data: bytes, position: int, global_number: int, fields: list[tuple[int, int, int]], endian: str
) -> tuple[dict[int, int], int]:
    """The timestamp (253) and weight (0) of one data message, and where it ends."""
    record: dict[int, int] = {}
    for number, size, _ in fields:
        raw = data[position : position + size]
        position += size
        if global_number == 30 and number in (253, 0):
            fmt = {4: "I", 2: "H"}.get(size)
            if fmt:
                record[number] = struct.unpack(endian + fmt, raw)[0]
    return record, position


def _decode_fit_weights(data: bytes, out: list[tuple[str, float]]) -> None:
    """Append the weight-scale records of one FIT file; a malformed tail raises."""
    header_size = data[0]
    data_size = struct.unpack_from("<I", data, 4)[0]
    position = header_size
    end = header_size + data_size
    definitions: dict[int, tuple[int, list[tuple[int, int, int]], str]] = {}
    while position < end:
        header = data[position]
        position += 1
        if header & 0x80:
            _, fields, _ = definitions[(header >> 5) & 0x03]
            position += sum(size for _, size, _ in fields)
            continue
        local = header & 0x0F
        if header & 0x40:
            definitions[local], position = _read_fit_definition(data, position, header)
            continue
        global_number, fields, endian = definitions[local]
        record, position = _read_fit_weight_fields(data, position, global_number, fields, endian)
        if global_number == 30 and 253 in record and record.get(0) not in (None, 0xFFFF):
            timestamp = _FIT_EPOCH + timedelta(seconds=record[253])
            out.append((timestamp.strftime("%Y-%m-%d"), round(record[0] / 100.0, 2)))


def _fit_weight_records(archive_path: Path) -> list[tuple[str, float]] | None:
    """(day, weight_kg) decoded from every weight-scale FIT file (message 30).

    Returns None when the archive cannot be read at all — distinct from an
    archive that simply holds no weight records.
    """
    out: list[tuple[str, float]] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return None
    with zipfile.ZipFile(archive_path) as archive:
        for entry in entries:
            if not entry.filename.casefold().endswith(".fit"):
                continue
            try:
                _decode_fit_weights(archive.read(entry), out)
            except (IndexError, KeyError, struct.error):
                continue
    return out


def _collect_json_weight_days(payload: object, days: set[str]) -> None:
    """Add the day of every node of ``payload`` that carries a non-zero weight."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            weight = node.get("weight")
            day = node.get("calendarDate") or node.get("date") or node.get("timestampGMT")
            if isinstance(weight, (int, float)) and weight and day:
                days.add(str(day)[:10])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _fit_weights_missing_from_json(source: Path) -> list[tuple[str, float]] | None:
    """FIT weight records whose day has no weight on the canonical JSON side."""
    fit_records: list[tuple[str, float]] = []
    for archive in sorted(source.rglob("*.zip")):
        decoded = _fit_weight_records(archive)
        if decoded is None:
            return None
        fit_records.extend(decoded)
    json_days: set[str] = set()
    for path in sorted(source.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _collect_json_weight_days(payload, json_days)
    return sorted(item for item in fit_records if item[0] not in json_days)


def _latest_source(connection: sqlite3.Connection, key: str) -> Path | None:
    row = connection.execute(
        "SELECT source_path FROM device_imports WHERE adapter_key=? ORDER BY imported_at DESC LIMIT 1",
        (key,),
    ).fetchone()
    # The app's own resolver: a database copied from the container records
    # /data/sources/... paths that live here under the configured sources dir.
    return resolve_source_path(get_settings(), str(row["source_path"])) if row else None


def _count_for_import(connection: sqlite3.Connection, table: str, import_id: object) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE import_id=?", (import_id,)).fetchone()[0])


def _check_import(
    connection: sqlite3.Connection, key: str, source: Path, errors: list[str], results: dict[str, object]
) -> None:
    fingerprint, source_bytes = _fingerprint(source, key)
    parsed = get_adapter(key).parse(source)
    row = connection.execute(
        "SELECT * FROM device_imports WHERE adapter_key=? AND source_fingerprint=?",
        (key, fingerprint),
    ).fetchone()
    if row is None:
        errors.append(f"{key}: matching imported fingerprint not found")
        return
    # Counted by natural key, not by import_id: a day the Garmin API also
    # delivers is upserted onto the same (owner, source, metric, day) row
    # and changes envelope, by design. What must hold is that every day the
    # file parses is present — whichever import now owns it.
    present = {
        (r[0], r[1], r[2]) for r in connection.execute(
            "SELECT source_name, metric_key, day FROM device_metric_days WHERE owner_user_id=?",
            (row["owner_user_id"],),
        )
    }
    stored = {
        "raw_records": int(row["raw_record_count"]),
        "daily_metrics": sum(
            (a.source_name, a.definition.key, a.day) in present for a in parsed.aggregates
        ),
        "workouts": _count_for_import(connection, "device_workouts", row["id"]),
        "events": _count_for_import(connection, "device_events", row["id"]),
    }
    expected = {
        "raw_records": parsed.raw_record_count,
        "daily_metrics": len(parsed.aggregates),
        "workouts": len(parsed.workouts),
        "events": len(parsed.events),
    }
    if stored != expected:
        errors.append(f"{key}: stored counts {stored} do not match parsed counts {expected}")
    if int(row["source_bytes"]) != source_bytes:
        errors.append(f"{key}: source byte count changed")
    if row["export_started_at"] != parsed.export_started_at or row["export_ended_at"] != parsed.export_ended_at:
        errors.append(f"{key}: stored export range does not match source")
    results[key] = {
        "fingerprint": fingerprint,
        "source_bytes": source_bytes,
        "range": [parsed.export_started_at, parsed.export_ended_at],
        **stored,
        "metadata": parsed.metadata,
    }


def _check_garmin_scale(
    garmin: dict, reconciliation: dict, pairs: list[tuple[str, Path]], errors: list[str]
) -> None:
    """Every plausible FIT-only weight must also be in the JSON import."""
    if reconciliation.get("scale_matches"):
        return
    garmin_source = dict(pairs).get("garmin")
    fit_only = _fit_weights_missing_from_json(garmin_source) if garmin_source else None
    if fit_only is None:
        errors.append("garmin: scale reconciliation failed and the FIT records could not be decoded")
        return
    plausible_missing = [item for item in fit_only if 30 <= item[1] <= 300]
    garmin["fit_only_weight_records"] = [list(item) for item in fit_only]
    if plausible_missing:
        errors.append(
            f"garmin: {len(plausible_missing)} plausible weight record(s) exist only in the FIT "
            f"upload history: {plausible_missing} — the JSON import lost them"
        )
    # Implausible FIT-only records are records the person deleted
    # from the account (or the importer would exclude anyway).


def _check_garmin(
    connection: sqlite3.Connection, results: dict[str, object], pairs: list[tuple[str, Path]], errors: list[str]
) -> None:
    garmin = results.get("garmin")
    if not isinstance(garmin, dict):
        return
    metadata = garmin.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    reconciliation = metadata.get("fit_json_reconciliation", {})
    fit_counts = metadata.get("fit_archive_counts", {})
    excluded = metadata.get("excluded_implausible_values", [])
    # Counts pinned to one export go stale on the next upload; what must
    # hold for ANY export is that nothing plausible in the FIT upload
    # history is missing from the canonical JSON side.
    if not reconciliation.get("blood_pressure_matches"):
        errors.append("garmin: FIT blood-pressure records do not reconcile with the JSON side")
    _check_garmin_scale(garmin, reconciliation, pairs, errors)
    if fit_counts.get("invalid"):
        errors.append(f"garmin: {fit_counts['invalid']} FIT file(s) failed to decode")
    bad_excluded = [
        item for item in excluded
        if item.get("metric") == "body_weight" and 30 <= float(item.get("value", 0)) <= 300
    ]
    if bad_excluded:
        errors.append(f"garmin: plausible weights were excluded as implausible: {bad_excluded}")
    bad_weights = int(connection.execute(
        """SELECT COUNT(*) FROM device_metric_days
           WHERE source_vendor='Garmin' AND metric_key='body_weight'
             AND (value < 30 OR value > 300)"""
    ).fetchone()[0])
    if bad_weights:
        errors.append(f"garmin: {bad_weights} implausible weights reached the usable trend")


def _check_kardia(connection: sqlite3.Connection, errors: list[str]) -> list[sqlite3.Row]:
    kardia_event = connection.execute(
        """SELECT de.*, d.id document_id FROM device_events de
           LEFT JOIN documents d ON d.source_path=de.source_file AND d.owner_user_id=de.owner_user_id
           WHERE de.source_vendor='Kardia'"""
    ).fetchall()
    kardia_metric = {
        (row["owner_user_id"], row["day"]): row
        for row in connection.execute(
            """SELECT * FROM device_metric_days
               WHERE source_vendor='Kardia' AND metric_key='ecg_heart_rate'"""
        )
    }
    for event in kardia_event:
        # Every recording keeps its determination, its source report and a
        # heart-rate day whose range holds the recording's own rate.
        day = kardia_metric.get((event["owner_user_id"], str(event["started_at"])[:10]))
        rate = event["value_numeric"]
        if not (
            event["value_text"]
            and event["document_id"]
            and day is not None
            and rate is not None
            and float(day["value_min"]) <= float(rate) <= float(day["value_max"])
        ):
            errors.append(f"kardia: event {event['id']} lacks its determination, heart-rate day or source document")
    return kardia_event


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "anamna.sqlite3")
    # No path defaults: each adapter's newest import records its own source, and
    # a hardcoded directory goes stale the day a fresh export is uploaded.
    parser.add_argument("--garmin", type=Path, default=None)
    parser.add_argument("--kardia", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=ROOT / "work" / "device-import-validation.json")
    args = parser.parse_args()

    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    errors: list[str] = []
    results: dict[str, object] = {}

    pairs = []
    for key, override in (("garmin", args.garmin), ("kardia", args.kardia)):
        source = override or _latest_source(connection, key)
        if source is None:
            errors.append(f"{key}: no import recorded and no --{key} path given")
            continue
        pairs.append((key, source.resolve()))

    for key, source in pairs:
        _check_import(connection, key, source, errors, results)

    _check_garmin(connection, results, pairs, errors)
    kardia_event = _check_kardia(connection, errors)

    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    if integrity != "ok":
        errors.append(f"database integrity: {integrity}")
    if foreign_keys:
        errors.append(f"foreign key violations: {foreign_keys}")

    payload = {
        "imports": results,
        "kardia_document_linked": bool(kardia_event and kardia_event[0]["document_id"]),
        "database_integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "errors": errors,
        "automated_pass_grants_clinical_verification": False,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "garmin": {key: results.get("garmin", {}).get(key) for key in ("raw_records", "daily_metrics", "events")},
        "kardia": {key: results.get("kardia", {}).get(key) for key in ("raw_records", "daily_metrics", "events")},
        "kardia_document_linked": payload["kardia_document_linked"],
        "errors": len(errors),
        "database_integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "automated_pass_grants_clinical_verification": False,
    }, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
