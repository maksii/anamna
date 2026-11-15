"""Portable calculation provenance remains provisional and scoped to its owner."""
from __future__ import annotations

from anamna import db
from anamna.calculation_info import calculation_source

from test_audit_export import _archive, _csv_rows, _device_import, _record


def _calculated_record(tmp_path):
    settings = _record(tmp_path)
    with db.connect(settings) as connection:
        for person, weight in (("alice", 80), ("bob", 120)):
            _device_import(connection, f"import-{person}", f"user-{person}", f"patient-{person}", "device://api")
            for row_id, key, name, value, source, vendor, unit in (
                (f"weight-{person}", "body_weight", "Body weight", weight, "Test scale", "Test device", "kg"),
                (f"derived-bmi-{person}", "body_mass_index", "Body mass index", weight / 4, "Calculated BMI", "Anamna", "kg/m²"),
            ):
                connection.execute(
                    """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id,
                           source_name, source_vendor, metric_key, metric_name, category, day,
                           aggregation, unit, value, sample_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'device_body', '2026-02-03', 'latest', ?, ?, 1, ?)""",
                    (row_id, f"user-{person}", f"patient-{person}", f"import-{person}", source, vendor,
                     key, name, unit, value, db.utc_now()),
                )
            connection.executemany(
                """INSERT INTO device_calculation_inputs(row_id, input_kind, input_id, input_day, input_value, input_unit)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (f"derived-bmi-{person}", "device_weight", f"weight-{person}", "2026-02-03", weight, "kg"),
                    (f"derived-bmi-{person}", "profile_height", f"patient-{person}", None, 200, "cm"),
                ],
            )
        connection.execute(
            """UPDATE observations SET extraction_method='derived_mch',
                   evidence_text='MCH (pg) = Hb (g/L) / RBC (10^12/L)\nHb 150; RBC 5',
                   verification_status='extracted' WHERE owner_user_id='user-alice'"""
        )
    return settings


def test_archive_retains_formula_method_and_official_source(tmp_path):
    settings = _calculated_record(tmp_path)
    archive, _ = _archive(settings, "user-alice")
    [row] = _csv_rows(archive, "observations.csv")
    assert row["extraction_method"] == "derived_mch"
    assert row["evidence_text"] == "MCH (pg) = Hb (g/L) / RBC (10^12/L)\nHb 150; RBC 5"
    assert row["verification_status"] == "extracted"
    assert row["calculation_source"] == calculation_source("derived_mch")


def test_archive_retains_owner_scoped_device_dependencies_and_provisional_status(tmp_path):
    settings = _calculated_record(tmp_path)
    archive, counts = _archive(settings, "user-alice")
    inputs = _csv_rows(archive, "device_calculation_inputs.csv")
    assert counts["device_calculation_inputs"] == 2
    assert {row["row_id"] for row in inputs} == {"derived-bmi-alice"}
    dependencies = {row["input_kind"]: row for row in inputs}
    assert dependencies["device_weight"]["input_id"] == "weight-alice"
    assert dependencies["device_weight"]["input_value"] == "80.0"
    assert dependencies["device_weight"]["input_day"] == "2026-02-03"
    assert dependencies["profile_height"]["input_id"] == "patient-alice"
    assert dependencies["profile_height"]["input_day"] == ""
    days = {row["id"]: row for row in _csv_rows(archive, "device_metric_days.csv")}
    assert days["derived-bmi-alice"]["extraction_method"] == "derived_bmi"
    assert days["derived-bmi-alice"]["verification_status"] == "extracted"
    assert days["derived-bmi-alice"]["calculation_source"] == calculation_source("derived_bmi")
    assert days["weight-alice"]["extraction_method"] == ""
    assert days["weight-alice"]["verification_status"] == "device_measurement"
    assert days["weight-alice"]["calculation_source"] == ""
    everything = b"".join(archive.read(name) for name in archive.namelist() if name.endswith((".csv", ".json")))
    assert b"bob" not in everything


def test_public_metric_and_adapter_identifiers_are_preserved_without_credentials(tmp_path):
    settings = _calculated_record(tmp_path)
    archive, _ = _archive(settings, "user-alice")
    rows = _csv_rows(archive, "device_metric_days.csv")
    assert {row["metric_key"] for row in rows} == {"body_weight", "body_mass_index"}
    [source] = _csv_rows(archive, "device_imports.csv")
    assert source["adapter_key"] == "test_export"
    assert not any(word in key.lower() for row in rows for key in row for word in ("password", "secret", "token", "hash"))


def test_empty_calculation_inputs_export_keeps_a_parseable_header(tmp_path):
    settings = _record(tmp_path)
    archive, counts = _archive(settings, "user-alice")
    assert _csv_rows(archive, "device_calculation_inputs.csv") == []
    assert archive.read("device_calculation_inputs.csv").decode("utf-8").startswith("row_id,input_kind,input_id,")
    assert counts["device_calculation_inputs"] == 0
