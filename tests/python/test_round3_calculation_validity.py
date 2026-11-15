"""Independent arithmetic/source-integrity counterexamples, with synthetic data."""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from anamna.db import connect, utc_now
from anamna.derived import ckd_epi_2021, refresh_derived_observations
from anamna.devices.calculations import refresh_device_calculations
from anamna.profile_calculations import profile_bmi
from anamna.lab_calculations import _sample_may_match

from test_concepts_repair import _egfr, _insert
from test_device_calculations import _derived, _history
from test_lab_calculations import add, connection as connection, results
from test_linked_metrics import _build, _device_day, _document, _observation
from test_web_panels import build


@pytest.mark.parametrize("raw,canonical,expected", [
    (None, "g/L", None), ("arbitrary", "g/L", None), ("g/dL", "g/L", 30),
])
def test_printed_units_are_required_and_override_stale_canonical_metadata(connection, raw, canonical, expected):
    add(connection, "Hemoglobin", 15, raw, unit_canonical=canonical)
    add(connection, "Red blood cell count", 5, "10^12/L")
    row = results(connection).get("mean-corpuscular-hemoglobin")
    assert (row["value_numeric"] if row else None) == expected


def test_malformed_numeric_payload_does_not_abort_other_laboratory_calculations(connection):
    add(connection, "Hemoglobin", "not-a-number", "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    add(connection, "Total cholesterol", 5, "mmol/L")
    add(connection, "HDL cholesterol", 1, "mmol/L")
    rows = results(connection)
    assert "mean-corpuscular-hemoglobin" not in rows
    assert rows["non-hdl-cholesterol"]["value_numeric"] == 4


@pytest.mark.parametrize("raw,canonical,expected", [
    (None, "µmol/L", False), ("arbitrary", "µmol/L", False), ("µmol/L", "mg/dL", True),
])
def test_egfr_does_not_treat_inferred_canonical_units_as_printed_evidence(tmp_path, raw, canonical, expected):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified',unit_raw=?,unit_canonical=? WHERE concept_id='creatinine'", (raw, canonical))
        refresh_derived_observations(db)
        rows = _egfr(db)
        assert bool(rows) is expected
        if expected:
            assert rows[0]["value_numeric"] == round(ckd_epi_2021(88 / 88.4, 34, "male"))


@pytest.mark.parametrize("kind", ["censored", "text", "malformed"])
def test_egfr_counts_incompatible_competing_source_results_before_filtering(tmp_path, kind):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        _insert(db, owner, "competing", "Creatinine", "creatinine", value=150 if kind != "text" else None, text="unreadable" if kind == "text" else None, unit="µmol/L")
        if kind == "censored":
            db.execute("UPDATE observations SET comparator='<' WHERE id='competing'")
        elif kind == "malformed":
            db.execute("UPDATE observations SET value_numeric='unreadable' WHERE id='competing'")
        refresh_derived_observations(db)
        assert _egfr(db) == []


@pytest.mark.parametrize("invalid", ["2025-01-01 garbled", "2025-01-01T25:00:00"])
def test_malformed_device_day_cannot_abort_valid_calculations(tmp_path, invalid):
    settings, owner = _history(tmp_path)
    _device_day(settings, owner, "body_weight", invalid, 80, "kg")
    with connect(settings) as db:
        refresh_device_calculations(db)
        assert [(row["day"], row["value"]) for row in _derived(db)] == [("2025-01-01", 20)]


@pytest.mark.parametrize("invalid", ["2024-01-01 garbled", "2024-01-01T25:00:00"])
def test_clinical_height_cannot_acquire_a_valid_day_by_truncation(tmp_path, invalid):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "height-report", "Synthetic clinic", "laboratory", "2024-01-01")
    _observation(settings, owner, "height", "height-report", "body-height", 200, "cm", invalid)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified'")
        refresh_device_calculations(db)
        assert _derived(db) == []


@pytest.mark.parametrize("change", ["foreign-patient-document", "foreign-patient-import"])
def test_device_bmi_requires_input_source_identity_to_match_patient(tmp_path, change):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "height-report", "Synthetic clinic", "laboratory", "2024-01-01")
    _observation(settings, owner, "height", "height-report", "body-height", 200, "cm", "2024-01-01")
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES ('other-patient',?,'Synthetic other patient',?)", (owner, utc_now()))
        db.execute("UPDATE observations SET verification_status='verified'")
        if change == "foreign-patient-document":
            db.execute("UPDATE documents SET patient_id='other-patient' WHERE id='height-report'")
        else:
            db.execute("UPDATE device_imports SET patient_id='other-patient' WHERE id='imp-1'")
        refresh_device_calculations(db)
        assert _derived(db) == []


@pytest.mark.parametrize("day", ["2024-01-01 garbled", "2024-01-01T25:00:00"])
def test_profile_height_does_not_accept_invalid_timestamp_suffix(day):
    assert profile_bmi({"weight_kg": 80, "date_of_birth": "1990-01-01"}, {
        "height_cm": {"value": 200, "unit": "cm", "day": day},
    }) is None


@pytest.mark.parametrize("days_until_due,expected", [(None, True), (-1, True), (0, False), (280, False), (281, True)])
def test_known_pregnancy_uses_the_existing_inclusive_sample_window(tmp_path, days_until_due, expected):
    settings, _, _ = build(tmp_path)
    due = (date(2025, 2, 13) + timedelta(days=days_until_due)).isoformat() if days_until_due is not None else None
    with connect(settings) as db:
        db.execute("UPDATE patients SET sex_at_birth='female',pregnancy_due_date=?", (due,))
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(db)
        assert bool(_egfr(db)) is expected


def test_pregnancy_context_retracts_reconstruction_but_keeps_reported_results(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET sex_at_birth='female'")
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(db)
        assert len(_egfr(db)) == 1
        db.execute("UPDATE patients SET pregnancy_due_date='2025-08-01'")
        assert refresh_derived_observations(db)["removed"] == 1
        assert _egfr(db) == []
        _insert(db, owner, "reported-egfr", "Reported eGFR", "estimated-glomerular-filtration-rate-ckd-epi-2021", value=100, unit="mL/min/1.73m²")
        refresh_derived_observations(db)
        assert db.execute("SELECT value_numeric FROM observations WHERE id='reported-egfr'").fetchone()[0] == 100


def test_foreign_source_reported_bmi_cannot_hide_valid_patient_fallback(tmp_path):
    settings, owner = _history(tmp_path)
    _document(settings, owner, "bmi-report", "Synthetic clinic", "laboratory", "2025-01-01")
    _observation(settings, owner, "reported-bmi", "bmi-report", "body-mass-index", 20, "kg/m²", "2025-01-01")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES ('other-patient',?,'Synthetic other patient',?)", (owner, utc_now()))
        db.execute("UPDATE documents SET patient_id='other-patient' WHERE id='bmi-report'")
        refresh_device_calculations(db)
        assert len(_derived(db)) == 1


@pytest.mark.parametrize("born", ["1990-03-14 garbled", "1990-03-14T25:00:00"])
def test_calculations_do_not_infer_age_from_a_malformed_birth_date(tmp_path, born):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET date_of_birth=?", (born,))
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(db)
        assert _egfr(db) == []
    assert profile_bmi({"weight_kg": 80, "date_of_birth": born}, {
        "height_cm": {"value": 200, "unit": "cm", "day": "2024-01-01"},
    }) is None


def test_device_height_carry_forward_cannot_infer_adulthood_from_invalid_birth_date(tmp_path):
    settings, _ = _history(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET date_of_birth='1990-03-14 garbled'")
        refresh_device_calculations(db)
        assert _derived(db) == []


@pytest.mark.parametrize("creatinine,age,sex", [(1, 34, "unknown"), (1, 17, "male"),
                                             (0, 34, "male"), (float("inf"), 34, "male"),
                                             (1, float("nan"), "female")])
def test_equation_api_itself_never_silently_substitutes_male_or_invalid_inputs(creatinine, age, sex):
    with pytest.raises(ValueError):
        ckd_epi_2021(creatinine, age, sex)


@pytest.mark.parametrize("number,unit", [(10, "mg/L"), (0.01, "g/L"), (1, "mg/dL"), (88.4, "µmol/L")])
def test_egfr_converts_explicit_mass_volume_units_without_magnitude_guessing(tmp_path, number, unit):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified',value_numeric=?,unit_raw=? WHERE concept_id='creatinine'", (number, unit))
        refresh_derived_observations(db)
        assert _egfr(db)[0]["value_numeric"] == round(ckd_epi_2021(1, 34, "male"))


@pytest.mark.parametrize("height,unit,expected", [(78, "in", 20.38), (2000, "mm", 20), (2, "m", 20)])
def test_explicit_clinic_height_units_feed_device_bmi(tmp_path, height, unit, expected):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "height-report", "Synthetic clinic", "laboratory", "2024-01-01")
    _observation(settings, owner, "height", "height-report", "body-height", height, unit, "2024-01-01")
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified'")
        refresh_device_calculations(db)
        assert _derived(db)[0]["value"] == expected


@pytest.mark.parametrize("target_time,target_specimen,expected", [
    ("2024-01-10T09:00:00", "blood", True),
    ("2024-01-10T08:00:00", "plasma", True),
    ("2024-01-10", None, False),
    (None, None, False),
    ("2024-01-10T08:00:00", "blood", False),
])
def test_reported_target_from_distinct_draw_does_not_hide_a_missing_sample_result(connection, target_time, target_specimen, expected):
    add(connection, "Hemoglobin", 150, "g/L", observed_at="2024-01-10T08:00:00", specimen="blood")
    add(connection, "Red blood cell count", 5, "10^12/L", observed_at="2024-01-10T08:00:00", specimen="blood")
    add(connection, "Mean corpuscular hemoglobin", 29, "pg", observed_at=target_time, specimen=target_specimen)
    assert ("mean-corpuscular-hemoglobin" in results(connection)) is expected


@pytest.mark.parametrize("reported_time,expected", [("2025-02-13T09:00:00", True), ("2025-02-13", False), (None, False)])
def test_egfr_reported_for_one_draw_does_not_hide_an_explicitly_distinct_draw(tmp_path, reported_time, expected):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified',observed_at='2025-02-13T08:00:00' WHERE concept_id='creatinine'")
        _insert(db, owner, "reported-egfr", "Reported eGFR", "estimated-glomerular-filtration-rate-ckd-epi-2021", value=100, unit="mL/min/1.73m²", observed=reported_time)
        refresh_derived_observations(db)
        assert bool(_egfr(db)) is expected


def test_target_timestamp_offsets_do_not_turn_one_instant_into_two_samples():
    identity = ("owner", "patient", ("report", "report"))
    assert _sample_may_match((*identity, "2025-01-02T00:30:00+02:00", "blood", "fasting"),
                             (*identity, "2025-01-01T22:30:00Z", "blood", "fasting"))


@pytest.mark.parametrize("sources,target,expected", [
    ([("White blood cell count", 8000, "cells/µL"), ("Neutrophils", 50, "%")], "neutrophils-absolute", 4),
    ([("White blood cell count", 8000, "cells/µL"), ("Neutrophils, absolute", 4000, "cells/µL")], "neutrophils", 50),
    ([("Hemoglobin", 150, "g/L"), ("Red blood cell count", 5000000, "cells/µL")], "mean-corpuscular-hemoglobin", 30),
    ([("Hematocrit", 0.45, "L/L"), ("Red blood cell count", 5000000, "cells/µL")], "mean-corpuscular-volume", 90),
    ([("Platelet count", 250000, "cells/µL"), ("Mean platelet volume", 10, "fL")], "plateletcrit", 0.25),
    ([("Reticulocytes, absolute", 100000, "cells/µL"), ("Red blood cell count", 5000000, "cells/µL")], "reticulocytes", 2),
    ([("White blood cell count", 8000, "cells/µL"), ("Basophils, absolute", 0, "cells/µL")], "basophils", 0),
])
def test_explicit_cell_volume_units_are_scaled_before_arithmetic(connection, sources, target, expected):
    for name, number, unit in sources:
        add(connection, name, number, unit, specimen="blood")
    assert results(connection)[target]["value_numeric"] == expected


def test_cell_volume_conversion_does_not_make_urine_counts_into_blood_counts(connection):
    add(connection, "White blood cell count", 8000, "cells/µL", specimen="urine")
    add(connection, "Neutrophils", 50, "%", specimen="urine")
    assert results(connection) == {}
