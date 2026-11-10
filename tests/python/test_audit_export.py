from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile

from anamna import db
from anamna.config import Settings
from anamna.export import write_record_archive
from anamna.ingest.pipeline import ensure_vendor

PDF = b"%PDF-1.4 the original report bytes"


def _settings(tmp_path):
    return Settings(database_path=tmp_path / "db" / "t.sqlite3", source_dir=tmp_path / "sources", secret_key="x")


def _owner(connection, user_id, email, patient_id, document_id, filename, source_path, observation_value):
    connection.execute(
        "INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at) "
        "VALUES (?, ?, ?, x'00', x'11', '2026-01-01T00:00:00+00:00')",
        (user_id, email, email.split("@")[0].title()),
    )
    connection.execute(
        "INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at) "
        "VALUES (?, ?, 'Patient', '1990-01-02', 'female', '2026-01-01T00:00:00+00:00')",
        (patient_id, user_id),
    )
    connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type,
               byte_size, sha256, page_count, title, clinical_type, extraction_strategy, imported_at, report_date)
           VALUES (?, ?, ?, ?, ?, 'application/pdf', 10, 'abc', 1, ?, 'lab_report', 'native', '2026-01-01T00:00:00+00:00', '2026-02-03')""",
        (document_id, user_id, patient_id, filename, source_path, f"Report for {email}"),
    )
    connection.execute(
        """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
               value_type, value_numeric, unit_raw, observed_at, extraction_method, evidence_text, parser_version, created_at)
           VALUES (?, ?, ?, ?, 1, 'concept-hb', 'Hemoglobin', 'numeric', ?, 'g/L', '2026-02-03', 'native', 'Hb 1', 'test', '2026-01-01T00:00:00+00:00')""",
        (f"obs-{user_id}", user_id, patient_id, document_id, observation_value),
    )
    connection.execute(
        "INSERT INTO immunizations(id, owner_user_id, patient_id, vaccine_code, product_name, occurrence_date, "
        "created_at, updated_at) VALUES (?, ?, ?, 'hepB', 'Engerix', '2020-05-01', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (f"vac-{user_id}", user_id, patient_id),
    )


def _record(tmp_path):
    """Two accounts on one database; only the first is exported in these tests."""
    settings = _settings(tmp_path)
    db.migrate(settings)
    sources = settings.source_dir
    (sources / "uploads" / "2026-02").mkdir(parents=True)
    (sources / "uploads" / "2026-02" / "alice.pdf").write_bytes(PDF)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"not in sources")
    connection = sqlite3.connect(settings.database_path)
    connection.execute(
        "INSERT INTO concepts(id, canonical_name, category, value_type, created_at) "
        "VALUES ('concept-hb', 'Hemoglobin', 'hematology', 'numeric', '2026-01-01T00:00:00+00:00')"
    )
    _owner(
        connection, "user-alice", "alice@example.com", "patient-alice", "doc-alice", "alice.pdf",
        str(sources / "uploads" / "2026-02" / "alice.pdf"), 7.4,
    )
    _owner(
        connection, "user-bob", "bob@example.com", "patient-bob", "doc-bob", "bob-secret-report.pdf",
        str(sources / "uploads" / "2026-02" / "bob-secret-report.pdf"), 99.5,
    )
    connection.commit()
    connection.close()
    return settings


def _archive(settings, user_id):
    buffer = io.BytesIO()
    counts = write_record_archive(settings, user_id, buffer)
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue())), counts


def _csv_rows(archive, name):
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8"))))


def test_archive_holds_the_owners_record(tmp_path):
    settings = _record(tmp_path)

    archive, counts = _archive(settings, "user-alice")

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format"] == "anamna-record-export"
    assert manifest["version"] == 1
    assert manifest["schema_version"] == max(
        int(path.name.split("_", 1)[0]) for path in db.MIGRATIONS_DIR.glob("*.sql")
    )
    assert manifest["counts"] == counts
    assert counts["documents"] == 1
    assert counts["observations"] == 1
    assert counts["vaccinations"] == 1
    assert counts["files"] == 1
    assert counts["missing_files"] == 0

    profile = json.loads(archive.read("profile.json"))
    assert profile["email"] == "alice@example.com"
    assert profile["display_name"] == "Alice"
    assert [patient["date_of_birth"] for patient in profile["patients"]] == ["1990-01-02"]
    for patient in profile["patients"]:
        assert not any(word in key.lower() for key in patient for word in ("password", "hash", "token", "secret", "key"))

    observations = _csv_rows(archive, "observations.csv")
    assert len(observations) == 1
    assert observations[0]["value_numeric"] == "7.4"
    assert observations[0]["concept"] == "Hemoglobin"
    assert observations[0]["unit"] == "g/L"

    documents = _csv_rows(archive, "documents.csv")
    assert documents[0]["archive_path"] == "files/uploads/2026-02/alice.pdf"
    assert documents[0]["document_type"] == "lab_report"

    vaccinations = _csv_rows(archive, "vaccinations.csv")
    assert vaccinations[0]["product_name"] == "Engerix"
    assert "password" not in " ".join(vaccinations[0]).lower()

    assert archive.read("files/uploads/2026-02/alice.pdf") == PDF


def test_another_accounts_rows_and_files_are_not_included(tmp_path):
    settings = _record(tmp_path)

    archive, _ = _archive(settings, "user-alice")

    names = archive.namelist()
    assert not any("bob" in name for name in names)
    everything = b"".join(archive.read(name) for name in names if name.endswith((".csv", ".json")))
    assert b"bob@example.com" not in everything
    assert b"99.5" not in everything
    assert b"Report for bob" not in everything


def test_a_document_outside_the_sources_is_skipped_and_counted(tmp_path):
    settings = _record(tmp_path)
    connection = sqlite3.connect(settings.database_path)
    connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type,
               byte_size, sha256, page_count, title, clinical_type, extraction_strategy, imported_at)
           VALUES ('doc-escape', 'user-alice', 'patient-alice', 'x.pdf', '../../etc/x', 'application/pdf', 1,
               'def', 1, 'Escape', 'other', 'native', '2026-01-01T00:00:00+00:00')"""
    )
    connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type,
               byte_size, sha256, page_count, title, clinical_type, extraction_strategy, imported_at)
           VALUES ('doc-absolute', 'user-alice', 'patient-alice', 'outside.pdf', ?, 'application/pdf', 1,
               'ghi', 1, 'Absolute', 'other', 'native', '2026-01-01T00:00:00+00:00')""",
        (str(tmp_path / "outside.pdf"),),
    )
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert counts["missing_files"] == 2
    assert counts["files"] == 1
    assert not any(name.startswith("files/") and "outside" in name for name in archive.namelist())
    assert not any("etc" in name for name in archive.namelist())
    rows = {row["id"]: row for row in _csv_rows(archive, "documents.csv")}
    assert rows["doc-escape"]["archive_path"] == ""
    assert rows["doc-absolute"]["archive_path"] == ""


DEVICE = b"device export bytes"


def _device_import(connection, import_id, user_id, patient_id, source_path):
    vendor_id = ensure_vendor(connection, "Test device", None)
    connection.execute(
        """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
               source_fingerprint, source_bytes, raw_record_count, status, metadata_json, imported_at)
           VALUES (?, ?, ?, ?, 'test_export', ?, ?, 1, 0, 'complete', '{}', '2026-01-01T00:00:00+00:00')""",
        (import_id, user_id, patient_id, vendor_id, source_path, f"fingerprint-{import_id}"),
    )


def test_device_originals_are_in_the_archive_once(tmp_path):
    settings = _record(tmp_path)
    export = settings.source_dir / "devices" / "2026-03"
    export.mkdir(parents=True)
    (export / "alice-oura.zip").write_bytes(DEVICE)
    connection = sqlite3.connect(settings.database_path)
    _device_import(connection, "import-alice", "user-alice", "patient-alice", str(export / "alice-oura.zip"))
    # A second device row naming the document's own file must not add it twice.
    _device_import(
        connection, "import-alice-again", "user-alice", "patient-alice",
        str(settings.source_dir / "uploads" / "2026-02" / "alice.pdf"),
    )
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert archive.read("files/devices/2026-03/alice-oura.zip") == DEVICE
    assert archive.namelist().count("files/uploads/2026-02/alice.pdf") == 1
    assert counts["device_files"] == 1
    assert counts["files"] == 2
    assert counts["missing_files"] == 0
    imports = _csv_rows(archive, "device_imports.csv")
    assert {row["id"] for row in imports} == {"import-alice", "import-alice-again"}
    assert imports[0]["source_path"]
    assert not any(word in name.lower() for name in imports[0] for word in ("password", "secret", "token", "hash", "key"))


def test_a_device_export_directory_is_added_file_by_file(tmp_path):
    settings = _record(tmp_path)
    export = settings.source_dir / "devices" / "unpacked"
    (export / "sub").mkdir(parents=True)
    (export / "workout.gpx").write_bytes(b"<gpx>workout</gpx>")
    (export / "sub" / "route.gpx").write_bytes(b"<gpx>route</gpx>")
    connection = sqlite3.connect(settings.database_path)
    _device_import(connection, "import-alice-dir", "user-alice", "patient-alice", str(export))
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert archive.read("files/devices/unpacked/workout.gpx") == b"<gpx>workout</gpx>"
    assert archive.read("files/devices/unpacked/sub/route.gpx") == b"<gpx>route</gpx>"
    assert counts["device_files"] == 2
    assert counts["files"] == 3


def test_another_accounts_device_files_are_not_included(tmp_path):
    settings = _record(tmp_path)
    (settings.source_dir / "devices").mkdir(parents=True)
    (settings.source_dir / "devices" / "bob-watch.zip").write_bytes(b"bob device bytes")
    connection = sqlite3.connect(settings.database_path)
    _device_import(
        connection, "import-bob", "user-bob", "patient-bob", str(settings.source_dir / "devices" / "bob-watch.zip")
    )
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert not any("bob" in name for name in archive.namelist())
    everything = b"".join(archive.read(name) for name in archive.namelist())
    assert b"bob device bytes" not in everything
    assert counts["device_files"] == 0
    assert _csv_rows(archive, "device_imports.csv") == []


def test_a_device_file_outside_the_sources_is_skipped_and_counted(tmp_path):
    settings = _record(tmp_path)
    connection = sqlite3.connect(settings.database_path)
    _device_import(connection, "import-escape", "user-alice", "patient-alice", str(tmp_path / "outside.pdf"))
    _device_import(
        connection, "import-absent", "user-alice", "patient-alice", str(settings.source_dir / "devices" / "gone.zip")
    )
    # An API feed has no file to keep, so it is neither archived nor counted as missing.
    _device_import(connection, "import-api", "user-alice", "patient-alice", "openwearables://api")
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert counts["device_files"] == 0
    assert counts["missing_files"] == 2
    assert not any("outside" in name or "gone" in name for name in archive.namelist())


def test_a_workout_route_file_is_archived(tmp_path):
    settings = _record(tmp_path)
    route = settings.source_dir / "devices" / "routes" / "alice-run.gpx"
    route.parent.mkdir(parents=True)
    route.write_bytes(b"<gpx>run</gpx>")
    export = settings.source_dir / "devices" / "alice-export.zip"
    export.write_bytes(DEVICE)
    connection = sqlite3.connect(settings.database_path)
    _device_import(connection, "import-alice-run", "user-alice", "patient-alice", str(export))
    connection.execute(
        """INSERT INTO device_workouts(id, owner_user_id, patient_id, import_id, source_name, source_vendor,
               workout_type, started_at, route_file, created_at)
           VALUES ('workout-alice', 'user-alice', 'patient-alice', 'import-alice-run', 'Test device', 'Test device',
               'running', '2026-02-03T07:00:00+00:00', ?, '2026-01-01T00:00:00+00:00')""",
        (str(route),),
    )
    connection.commit()
    connection.close()

    archive, counts = _archive(settings, "user-alice")

    assert archive.read("files/devices/routes/alice-run.gpx") == b"<gpx>run</gpx>"
    assert counts["device_workouts"] == 1
    assert counts["device_files"] == 2  # the export file and the route, each once
    assert counts["missing_files"] == 0
