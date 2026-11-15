"""Independent synthetic regressions for calculated-value presentation and reuse."""
from __future__ import annotations

from datetime import date

import pytest

from anamna.db import connect
from anamna.health import status_label
from anamna.i18n import activate_locale, reset_locale
from anamna.locales.messages import MESSAGES
from anamna.profile_calculations import profile_bmi
from anamna.web import app as web

from test_linked_metrics import _build, _document, _observation


PATIENT = {
    "id": "synthetic-patient", "owner_user_id": "synthetic-owner",
    "date_of_birth": "1990-01-01", "weight_kg": 80, "height_cm": 180,
}
HEIGHT = {
    "id": "synthetic-height", "patient_id": "synthetic-patient",
    "owner_user_id": "synthetic-owner", "value": 200, "unit": "cm", "day": "2025-01-01",
}
TODAY = date(2026, 11, 15)


@pytest.mark.parametrize("height_change,patient_change", [
    ({"patient_id": "another-patient"}, {}),
    ({"owner_user_id": "another-owner"}, {}),
    ({"day": "2026-11-16"}, {}),
    ({"day": "invalid"}, {}),
    ({"day": None}, {}),
    ({"ambiguous": True}, {}),
    ({}, {"date_of_birth": None}),
    ({}, {"date_of_birth": "2006-01-02"}),
    ({"day": "2009-12-31"}, {}),
])
def test_undated_weight_never_reuses_unqualified_or_foreign_dated_height(height_change, patient_change):
    assert profile_bmi({**PATIENT, **patient_change}, {"height_cm": {**HEIGHT, **height_change}}, today=TODAY) is None


def test_height_from_a_confirmed_clinical_record_keeps_its_own_provenance():
    reading = {
        **HEIGHT, "input_kind": "observation_height", "value": 2, "unit": "m",
        "verification_status": "verified", "extraction_method": "native_pdf_text_parser",
    }
    result = profile_bmi(PATIENT, {"height_cm": reading}, today=TODAY)
    assert result["value"] == 20
    assert result["observed_at"] is None
    height = result["calculation_inputs"][1]
    assert height["input_kind"] == "observation_height"
    assert height["input_id"] == reading["id"]
    assert height["input_value"] == 200 and height["input_unit"] == "cm"


@pytest.mark.parametrize("changes", [
    {"verification_status": "extracted"}, {"verification_status": "rejected"},
    {"comparator": "<"}, {"extraction_method": "derived_height"},
])
def test_clinical_height_must_be_independently_confirmed_and_uncensored(changes):
    reading = {
        **HEIGHT, "input_kind": "observation_height", "verification_status": "verified",
        "extraction_method": "native_pdf_text_parser", **changes,
    }
    assert profile_bmi(PATIENT, {"height_cm": reading}, today=TODAY) is None


def test_manual_profile_pair_remains_undated_without_an_inferred_measurement_age():
    result = profile_bmi({"weight_kg": 40, "height_cm": 150})
    assert result["value"] == pytest.approx(17.78)
    assert result["observed_at"] is None
    assert all(item["input_day"] is None for item in result["calculation_inputs"])


@pytest.mark.parametrize("status", ["verified", "corrected"])
def test_confirmed_calculation_is_not_described_as_provisional_in_cards_page_or_export(tmp_path, status):
    settings, owner, client = _build(tmp_path)
    _document(settings, owner, "synthetic-calculation", "Synthetic clinic", "laboratory", "2025-01-01")
    _observation(settings, owner, "synthetic-bmi", "synthetic-calculation", "body-mass-index", 25, "kg/m²", "2025-01-01")
    with connect(settings) as db:
        db.execute(
            "UPDATE observations SET raw_name='Body mass index', extraction_method='derived_bmi', verification_status=? WHERE id='synthetic-bmi'",
            (status,),
        )
    web.invalidate_catalog()
    for lang in ("en", "uk"):
        token = activate_locale(lang)
        try:
            with connect(settings) as db:
                card = next(item for item in web._metric_catalog(db, owner) if item["id"] == "body-mass-index")
                assert status_label(status).casefold() in card["verification_label"].casefold()
                assert card["verification_label"] != MESSAGES["calc.status"][lang]
                [row] = web._linked_observation_rows(db, owner, "body-mass-index")
                exported = web._export_observation_row(db, "body-mass-index", row, "1990-03-14", "male")
                assert status_label(status).casefold() in exported["status"].casefold()
        finally:
            reset_locale(token)
        client.cookies.set("anamna_lang", lang)
        response = client.get("/metrics/body-mass-index")
        assert response.status_code == 200
        assert MESSAGES["calc.provisional"][lang] not in response.text


def test_confirmed_clinic_height_connects_to_manual_profile_weight(tmp_path):
    settings, owner, client = _build(tmp_path)
    _document(settings, owner, "synthetic-height-doc", "Synthetic clinic", "consultation", "2025-01-01")
    _observation(settings, owner, "synthetic-height-obs", "synthetic-height-doc", "body-height", 2, "m", "2025-01-01")
    with connect(settings) as db:
        db.execute("UPDATE patients SET weight_kg=80 WHERE owner_user_id=?", (owner,))
        db.execute("UPDATE observations SET raw_name='Body height', verification_status='verified' WHERE id='synthetic-height-obs'")
        measured = web._measured_body(db, owner)
        assert measured["height_cm"]["value"] == 200
        assert measured["height_cm"]["unit"] == "cm"
        estimate = web._profile_bmi_reading(db, owner)
        assert estimate["value_numeric"] == 20
        assert estimate["calculation_inputs"][1]["input_kind"] == "observation_height"
    web.invalidate_catalog()
    for lang in ("en", "uk"):
        client.cookies.set("anamna_lang", lang)
        response = client.get("/profile")
        assert response.status_code == 200
        assert MESSAGES["calc.input_observation_height"][lang] in response.text
        assert 'href="/devices/metrics/body_height"' not in response.text


def test_conflicting_same_day_confirmed_heights_do_not_choose_a_profile_bmi_by_id(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "synthetic-conflicting-heights", "Synthetic clinic", "consultation", "2025-01-01")
    for suffix, value in (("a", 180), ("b", 200)):
        _observation(settings, owner, "synthetic-height-" + suffix, "synthetic-conflicting-heights", "body-height", value, "cm", "2025-01-01")
    with connect(settings) as db:
        db.execute("UPDATE patients SET weight_kg=80, height_cm=190 WHERE owner_user_id=?", (owner,))
        db.execute("UPDATE observations SET raw_name='Body height', verification_status='verified' WHERE concept_id='body-height'")
        measured = web._measured_body(db, owner)
        assert measured["height_cm"]["ambiguous"] is True
        assert web._profile_bmi_reading(db, owner) is None
        web._profile_store(
            db, owner, "Test Patient", None, "1990-03-14", "male", None,
            {"height_cm": None, "weight_kg": 80}, {}, "",
        )
        assert db.execute("SELECT height_cm FROM patients WHERE owner_user_id=?", (owner,)).fetchone()[0] == 190


def test_same_owner_distinct_patients_keep_evidence_without_merging_the_primary_series(tmp_path):
    settings, owner, _ = _build(tmp_path)
    with connect(settings) as db:
        db.execute(
            """INSERT INTO patients(id,owner_user_id,display_name,date_of_birth,sex_at_birth,created_at)
               VALUES ('synthetic-secondary',?,'Another Synthetic Patient','2015-01-01','female','2999-01-01')""",
            (owner,),
        )
    for suffix in ("primary", "secondary"):
        _document(settings, owner, "synthetic-" + suffix, "Synthetic clinic", "laboratory", "2025-01-01")
        _observation(settings, owner, "synthetic-bmi-" + suffix, "synthetic-" + suffix, "body-mass-index", 25, "kg/m²", "2025-01-01")
    with connect(settings) as db:
        db.execute("UPDATE documents SET patient_id='synthetic-secondary' WHERE id='synthetic-secondary'")
        db.execute("UPDATE observations SET patient_id='synthetic-secondary' WHERE id='synthetic-bmi-secondary'")
        db.execute("UPDATE observations SET raw_name='Body mass index'")
        evidence = web._deduped_observation_rows(db, owner, "body-mass-index")
        assert {row["id"] for row in evidence} == {"synthetic-bmi-primary", "synthetic-bmi-secondary"}
        linked = web._linked_observation_rows(db, owner, "body-mass-index")
        assert [row["id"] for row in linked] == ["synthetic-bmi-primary"]
        card = next(item for item in web._metric_catalog(db, owner) if item["id"] == "body-mass-index")
        assert card["count"] == 1 and card["evidence_count"] == 1
        assert db.execute("SELECT COUNT(*) FROM documents WHERE owner_user_id=?", (owner,)).fetchone()[0] == 2
