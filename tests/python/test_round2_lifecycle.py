"""Adversarial regressions for calculation identity, review and hand-offs."""
from __future__ import annotations

import pytest
import json

from anamna.calculation_info import calculation_source
from anamna import derived
from anamna.db import connect
from anamna.derived import refresh_derived_observations
from anamna.i18n import activate_locale, reset_locale, t
from anamna.ingest.pipeline import DuplicateRefused, _copy_rows_held_by_primary, _result_fingerprints
from anamna.web import ai_export, chat_routes

from test_audit_export import _archive, _csv_rows, _record
from test_concepts_repair import _egfr, _insert
from test_web_panels import build


def test_changed_birth_date_reopens_review_even_when_integer_age_and_egfr_match(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [before] = _egfr(connection)
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (before["id"],))
        connection.execute("UPDATE patients SET date_of_birth='1990-03-15' WHERE owner_user_id=?", (owner,))
        refresh_derived_observations(connection)
        [after] = _egfr(connection)
        assert after["value_numeric"] == before["value_numeric"]
        assert after["verification_status"] == "extracted"
        assert "date_of_birth=1990-03-15" in after["evidence_text"]
        assert "input_id=obs-2" in after["evidence_text"]
        assert refresh_derived_observations(connection) == {"added": 0, "updated": 0, "removed": 0}


def test_egfr_keeps_sample_context_and_reopens_review_after_context_change(tmp_path):
    settings, _, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified', specimen='serum', sample_condition='fasting' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [row] = _egfr(connection)
        assert (row["specimen"], row["sample_condition"]) == ("serum", "fasting")
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (row["id"],))
        connection.execute("UPDATE observations SET sample_condition='not_fasting' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [row] = _egfr(connection)
        assert row["sample_condition"] == "not_fasting"
        assert row["verification_status"] == "extracted"


def test_unrelated_parser_release_does_not_revoke_an_unchanged_calculation_review(tmp_path, monkeypatch):
    settings, _, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [before] = _egfr(connection)
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (before["id"],))
        monkeypatch.setattr(derived, "PARSER_VERSION", "unrelated-parser-release")
        assert refresh_derived_observations(connection) == {"added": 0, "updated": 0, "removed": 0}
        assert _egfr(connection)[0]["verification_status"] == "verified"
        assert _egfr(connection)[0]["parser_version"] == before["parser_version"]


def test_unchecked_competing_creatinine_prevents_ambiguous_reconstruction(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        _insert(connection, owner, "unchecked-creatinine", "Creatinine", "creatinine", value=150, unit="µmol/L", status="extracted")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


@pytest.mark.parametrize("change", ["extraction_method='derived_reconstructed_creatinine'", "document_id=NULL,report_id=NULL"])
def test_egfr_requires_independent_source_with_document_or_report_identity(tmp_path, change):
    settings, _, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        connection.execute(f"UPDATE observations SET {change} WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


@pytest.mark.parametrize("observed_at", ["2025-02-13 garbled", "2025-02-13T25:00:00", "2025-02-13T12:99:00"])
def test_egfr_does_not_silently_truncate_an_invalid_timestamp(tmp_path, observed_at):
    settings, _, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified',observed_at=? WHERE concept_id='creatinine'", (observed_at,))
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


def test_egfr_rejects_source_document_assigned_to_another_patient(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES ('another-patient',?,'Another synthetic patient','2025-01-01')", (owner,))
        connection.execute("UPDATE documents SET patient_id='another-patient' WHERE id='doc-1'")
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


def test_archive_observation_ids_make_dependencies_resolvable_and_keep_patient_context(tmp_path):
    settings = _record(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET specimen='serum',sample_condition='fasting',unit_canonical='g/L' WHERE owner_user_id='user-alice'")
    archive, _ = _archive(settings, "user-alice")
    [row] = _csv_rows(archive, "observations.csv")
    assert row["id"] == "obs-user-alice"
    assert row["patient_id"] == "patient-alice"
    assert row["concept_id"] == "concept-hb"
    assert row["report_id"] == ""
    assert row["unit_canonical"] == "g/L"
    assert row["specimen"] == "serum"
    assert row["sample_condition"] == "fasting"


def test_egfr_structured_dependencies_export_actual_source_identity_value_and_unit(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [result] = _egfr(connection)
        [dependency] = json.loads(result["calculation_inputs_json"])
        source = connection.execute("SELECT * FROM observations WHERE id=?", (dependency["input_id"],)).fetchone()
        assert dependency == {
            "input_kind": "observation", "input_id": "obs-2", "input_concept_id": "creatinine",
            "input_name": "Creatinine", "input_value": 88.0, "input_unit": "µmol/L",
            "input_day": "2025-02-13", "document_id": "doc-1", "report_id": source["report_id"],
        }
        result_id = result["id"]
    archive, _ = _archive(settings, owner)
    rows = {row["id"]: row for row in _csv_rows(archive, "observations.csv")}
    [exported] = json.loads(rows[result_id]["calculation_inputs_json"])
    assert exported == dependency
    assert float(rows[exported["input_id"]]["value_numeric"]) == exported["input_value"]
    assert rows[exported["input_id"]]["unit"] == exported["input_unit"]
    token = activate_locale("uk")
    try:
        card = ai_export._observation_card(dict(result))
        text = ai_export._calculation_text(card)
        assert "Креатинін 88 µmol/L @2025-02-13" in text
        assert "calc.input_observation" not in text
    finally:
        reset_locale(token)


def test_calculated_values_are_not_printed_evidence_for_document_deduplication(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [calculated] = _egfr(connection)
        assert calculated["concept_id"] not in {key[0] for key in _result_fingerprints(connection, "doc-1")}
        document = dict(connection.execute("SELECT * FROM documents WHERE id='doc-1'").fetchone())
        document.update(id="second-report", sha256="second-report-sha", title="Independent reported eGFR")
        connection.execute(
            f"INSERT INTO documents ({','.join(document)}) VALUES ({','.join('?' for _ in document)})",
            tuple(document.values()),
        )
        _insert(connection, owner, "printed-egfr", "eGFR (CKD-EPI 2021)", calculated["concept_id"],
                value=calculated["value_numeric"], unit=calculated["unit_raw"], status="extracted")
        connection.execute("UPDATE observations SET document_id='second-report' WHERE id='printed-egfr'")
        with pytest.raises(DuplicateRefused):
            _copy_rows_held_by_primary(connection, "second-report", "doc-1")


def _summary():
    inputs = [
        {"input_kind": "device_weight", "input_value": 80, "input_unit": "kg", "input_day": "2026-02-01"},
        {"input_kind": "profile_height", "input_value": 200, "input_unit": "cm", "input_day": None},
    ]
    return {
        "metric_key": "body_mass_index", "name": "Body mass index", "unit": "kg/m²",
        "aggregation": "latest", "day_count": 2, "first_day": "2024-01-01", "row_count": 2,
        "vendors": ["Anamna"], "latest_day": "2026-02-01", "latest_value": 20,
        "extraction_method": "derived_bmi", "verification_status": "extracted",
        "calculation_inputs": inputs, "calculated_day_count": 1,
        "recent_days": [
            {"day": "2026-02-01", "value": 20, "extraction_method": "derived_bmi", "calculation_inputs": inputs},
            {"day": "2024-01-01", "value": 21},
        ],
        "months": [{"period": "2026-02", "mean": 20, "min": 20, "max": 20, "days": 1, "calculated_day_count": 1}],
        "years": [{"period": "2024", "mean": 21, "min": 21, "max": 21, "days": 1, "calculated_day_count": 0}],
    }


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_model_hand_off_keeps_calculation_status_inputs_and_full_dates(locale):
    token = activate_locale(locale)
    try:
        summary = _summary()
        for text in ("\n".join(ai_export._device_block(summary)), ai_export._device_one_liner(summary),
                     chat_routes._device_detail(summary), chat_routes._device_line(summary)):
            assert calculation_source("derived_bmi") in text
            assert t("ai.calculated_days", count=1) in text
            assert "80 kg @2026-02-01" in text
            assert t("calc.undated_input") in text
        for text in ("\n".join(ai_export._device_block(summary)), chat_routes._device_detail(summary)):
            assert "2024-01-01 21" in text
            assert t("calc.status") in text
    finally:
        reset_locale(token)


def test_reported_latest_bmi_does_not_hide_formula_of_older_calculated_days():
    summary = _summary()
    summary.update(extraction_method=None, calculation_inputs=[], verification_status="device_measurement")
    assert calculation_source("derived_bmi") in ai_export._device_one_liner(summary)
    assert calculation_source("derived_bmi") in chat_routes._device_line(summary)
