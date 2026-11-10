from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path
from typing import BinaryIO

from . import factors
from .config import Settings, resolve_source_path
from .db import transaction, utc_now


EXPORT_FORMAT = "anamna-record-export"
EXPORT_VERSION = 1
#: Columns that never leave the installation: credentials, sessions and keys.
_SECRET_WORDS = ("password", "secret", "token", "hash", "key")

_OBSERVATION_HEADER = [
    "observed_at", "concept", "printed_name", "value_numeric", "value_text", "comparator", "unit",
    "reference_text", "reference_low", "reference_high", "laboratory_flag", "verification_status",
    "document_id", "page_number",
]
_DOCUMENT_HEADER = ["id", "title", "document_type", "document_date", "original_filename", "archive_path"]
#: CSV file name in the archive -> the table it is a copy of.
_OWNED_TABLES = {
    "device_imports.csv": "device_imports",
    "vaccinations.csv": "immunizations",
    "device_metric_days.csv": "device_metric_days",
    "device_workouts.csv": "device_workouts",
    "medicines.csv": "factors",
    "medicine_effects.csv": "factor_effects",
}


def _kept_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    names = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]
    return [name for name in names if not any(word in name.lower() for word in _SECRET_WORDS)]


def _owned_rows(connection: sqlite3.Connection, table: str, user_id: str) -> tuple[list[str], list[tuple]]:
    columns = _kept_columns(connection, table)
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE owner_user_id = ? ORDER BY rowid", (user_id,)
    ).fetchall()
    return columns, [tuple(row) for row in rows]


#: Raw dose columns that medicines.csv moves beside ``schedule`` (see ``_medicine_csv``).
_DOSE_COLUMNS = ("dose_amount", "dose_unit")


def _medicine_csv(columns: list[str], rows: list[tuple]) -> tuple[list[str], list[tuple]]:
    """medicines.csv with the dose and how it is taken right after ``schedule``.

    ``dose_amount`` and ``dose_unit`` are already raw columns, further right; they move up
    so the dose sits with the schedule. ``how_taken`` is the line the Medicines page prints.
    """
    kept = [name for name in columns if name not in _DOSE_COLUMNS]
    after = kept.index("schedule") + 1
    header = kept[:after] + [*_DOSE_COLUMNS, "how_taken"] + kept[after:]
    out = []
    for row in rows:
        values = dict(zip(columns, row))
        plan = values.get("schedule_json") or ""
        amount = values["dose_amount"]
        shaped = {
            "kind": values["kind"],
            "dose_amount": amount,
            "dose_unit": values["dose_unit"],
            "dose": values["dose"],
            "schedule": values["schedule"],
            "regimen": json.loads(plan) if plan else None,
        }
        # A whole number is written without ".0".
        if amount is None:
            amount_text = ""
        elif float(amount).is_integer():
            amount_text = str(int(amount))
        else:
            amount_text = str(amount)
        values.update(
            dose_amount=amount_text,
            how_taken=factors.regimen_text(shaped, "en"),
        )
        out.append(tuple(values[name] for name in header))
    return header, out


def _csv_text(header: list[str], rows: list[tuple]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _inside(settings: Settings, stored: str, root: Path) -> Path | None:
    """The resolved path a stored name points at, or ``None`` when it resolves outside the sources directory."""
    try:
        path = resolve_source_path(settings, stored).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if path.is_relative_to(root) else None


def _original_file(settings: Settings, stored: str, root: Path) -> Path | None:
    """The file a document row names, or ``None`` when it is missing or resolves outside the sources directory."""
    path = _inside(settings, stored, root)
    return path if path is not None and path.is_file() else None


def _device_originals(settings: Settings, stored: str, root: Path) -> tuple[list[Path], int]:
    """The files a device import's stored original names, and how many entries were refused.

    A file is itself; a directory (an unpacked export) contributes every file beneath
    it. Each candidate is checked for containment on its own, so a symlink out of the
    sources directory is refused. Symlinked directories are not descended.
    """
    path = _inside(settings, stored, root)
    if path is None:
        return [], 1
    if path.is_file():
        return [path], 0
    if not path.is_dir():
        return [], 1
    found: list[Path] = []
    refused = 0
    for directory, _subdirectories, filenames in os.walk(path):
        for name in sorted(filenames):
            candidate = Path(directory, name).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                found.append(candidate)
            else:
                refused += 1
    return found, refused


def write_record_archive(settings: Settings, user_id: str, target: BinaryIO) -> dict[str, int]:
    """Write one account's whole record as a ZIP to ``target``; returns counts."""
    root = settings.source_dir.resolve()
    with transaction(settings, immediate=False) as connection:
        account = connection.execute(
            "SELECT email, display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if account is None:
            raise ValueError("No such account")
        schema_version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        patient_columns, patient_rows = _owned_rows(connection, "patients", user_id)
        observation_rows = connection.execute(
            """SELECT o.observed_at, c.canonical_name, o.raw_name, o.value_numeric, o.value_text,
                      o.comparator, o.unit_raw, o.vendor_reference_text, o.vendor_reference_low,
                      o.vendor_reference_high, o.vendor_interpretation, o.verification_status,
                      o.document_id, o.page_number
                 FROM observations o LEFT JOIN concepts c ON c.id = o.concept_id
                WHERE o.owner_user_id = ? ORDER BY o.observed_at, o.id""",
            (user_id,),
        ).fetchall()
        document_rows = connection.execute(
            """SELECT id, title, clinical_type, report_date, original_filename, source_path
                 FROM documents WHERE owner_user_id = ? ORDER BY imported_at, id""",
            (user_id,),
        ).fetchall()
        owned = {name: _owned_rows(connection, table, user_id) for name, table in _OWNED_TABLES.items()}
    owned["medicines.csv"] = _medicine_csv(*owned["medicines.csv"])

    files: dict[str, Path] = {}
    archive_paths: dict[str, str] = {}
    missing = 0
    for document in document_rows:
        path = _original_file(settings, document["source_path"], root)
        if path is None:
            missing += 1
            archive_paths[document["id"]] = ""
            continue
        arcname = "files/" + path.relative_to(root).as_posix()
        files[arcname] = path
        archive_paths[document["id"]] = arcname

    # An API feed (``openwearables://api``) and a workout without a route have no
    # file to keep, so they are not counted as missing.
    device_header, device_rows = owned["device_imports.csv"]
    workout_header, workout_rows = owned["device_workouts.csv"]
    stored_originals = [row[device_header.index("source_path")] for row in device_rows]
    stored_originals += [row[workout_header.index("route_file")] for row in workout_rows]
    files_before_devices = len(files)
    for stored in stored_originals:
        if not stored or "://" in stored:
            continue
        found, refused = _device_originals(settings, stored, root)
        missing += refused
        for path in found:
            # setdefault: a file a document already put in the archive is written once.
            files.setdefault("files/" + path.relative_to(root).as_posix(), path)
    device_files = len(files) - files_before_devices

    counts = {
        "patients": len(patient_rows),
        "documents": len(document_rows),
        "observations": len(observation_rows),
        "vaccinations": len(owned["vaccinations.csv"][1]),
        "device_imports": len(device_rows),
        "device_metric_days": len(owned["device_metric_days.csv"][1]),
        "device_workouts": len(workout_rows),
        "medicines": len(owned["medicines.csv"][1]),
        "medicine_effects": len(owned["medicine_effects.csv"][1]),
        "device_files": device_files,
        "files": len(files),
        "missing_files": missing,
    }
    manifest = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "schema_version": schema_version,
        "exported_at": utc_now(),
        "counts": counts,
    }
    profile = {
        "email": account["email"],
        "display_name": account["display_name"],
        "patients": [dict(zip(patient_columns, row)) for row in patient_rows],
    }
    documents_csv = _csv_text(
        _DOCUMENT_HEADER,
        [
            (
                document["id"], document["title"], document["clinical_type"], document["report_date"],
                document["original_filename"], archive_paths[document["id"]],
            )
            for document in document_rows
        ],
    )

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("profile.json", json.dumps(profile, ensure_ascii=False, indent=2, default=str))
        archive.writestr("observations.csv", _csv_text(_OBSERVATION_HEADER, observation_rows))
        archive.writestr("documents.csv", documents_csv)
        for name, (columns, rows) in owned.items():
            archive.writestr(name, _csv_text(columns, rows))
        for arcname, path in files.items():
            archive.write(path, arcname)
    return counts
