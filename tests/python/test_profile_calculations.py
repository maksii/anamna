"""Synthetic current-profile estimates never manufacture dated measurements."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from anamna.profile_calculations import BMI_SOURCE_URL, PROFILE_BMI_METHOD, profile_bmi


def test_manual_weight_and_height_make_an_undated_provisional_estimate():
    result = profile_bmi({"id": "synthetic-patient", "weight_kg": 81, "height_cm": 180})
    assert result["value"] == 25
    assert result["unit"] == "kg/m²"
    assert result["method"] == result["extraction_method"] == PROFILE_BMI_METHOD
    assert result["source_url"] == BMI_SOURCE_URL
    assert result["observed_at"] is None and result["day"] is None
    assert result["verification_status"] == "extracted"
    assert [row["input_kind"] for row in result["calculation_inputs"]] == ["profile_weight", "profile_height"]
    assert all(row["input_day"] is None for row in result["calculation_inputs"])


def test_dated_device_height_keeps_provenance_without_dating_the_estimate():
    result = profile_bmi({"weight_kg": 100, "height_cm": 180, "date_of_birth": "1990-01-01"}, {
        "height_cm": {"id": "synthetic-height", "value": 200, "day": "2025-01-02", "source": "Synthetic scale"},
    })
    assert result["value"] == 25
    height = result["calculation_inputs"][1]
    assert height == {
        "input_kind": "device_height", "input_id": "synthetic-height", "input_day": "2025-01-02",
        "input_value": 200, "input_unit": "cm", "input_source": "Synthetic scale",
    }
    assert result["observed_at"] is None
    assert result["calculation_inputs"][0]["input_day"] is None


@pytest.mark.parametrize("measured_weight", [{"value": 81, "day": "2025-01-02"}, None, {}])
def test_any_measured_weight_is_owned_by_the_dated_device_path(measured_weight):
    assert profile_bmi({"weight_kg": 81, "height_cm": 180}, {"weight_kg": measured_weight}) is None


@pytest.mark.parametrize("field,value", [
    ("weight_kg", None), ("weight_kg", False), ("weight_kg", 0), ("weight_kg", -1),
    ("weight_kg", 1), ("weight_kg", 700), ("weight_kg", float("nan")), ("weight_kg", float("inf")),
    ("height_cm", None), ("height_cm", True), ("height_cm", 0), ("height_cm", -1),
    ("height_cm", 30), ("height_cm", 280), ("height_cm", float("nan")), ("height_cm", float("inf")),
])
def test_invalid_profile_values_follow_existing_body_measurement_bounds(field, value):
    patient = {"weight_kg": 81, "height_cm": 180, field: value}
    assert profile_bmi(patient) is None


@pytest.mark.parametrize("value,unit,expected", [(2, "m", 20), (200, "cm", 20),
                                               (2, "", None), (2, "arbitrary", None)])
def test_device_height_requires_explicit_supported_units(value, unit, expected):
    result = profile_bmi({"weight_kg": 80, "date_of_birth": "1990-01-01"}, {
        "height_cm": {"value": value, "unit": unit, "day": "2025-01-02"},
    })
    assert (result["value"] if result else None) == expected


def test_profile_unit_names_never_trigger_magnitude_recovery():
    assert profile_bmi({"weight_kg": 80, "height_cm": 1.8}) is None
    assert profile_bmi({"weight_kg": 80, "height_cm": 180}, {"height_cm": {"value": 1.8}}) is None


def test_an_invalid_measured_height_never_silently_falls_back_to_manual_height():
    assert profile_bmi({"weight_kg": 80, "height_cm": 180}, {"height_cm": {"value": 0}}) is None


def test_profile_metadata_never_becomes_a_measurement_date_and_inputs_are_unchanged():
    patient = {"weight_kg": 81, "height_cm": 180, "updated_at": "2025-02-03", "date_of_birth": "1990-01-01"}
    measured = {"height_cm": {"value": 180, "day": "2024-01-01", "source": "Synthetic device"}}
    original = copy.deepcopy((patient, measured))
    result = profile_bmi(patient, measured)
    assert (patient, measured) == original
    assert result["observed_at"] is None
    assert result["calculation_inputs"][0]["input_day"] is None


def test_sqlite_profile_row_is_supported_without_a_persisted_estimate():
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE patients(id TEXT, weight_kg REAL, height_cm REAL)")
        connection.execute("INSERT INTO patients VALUES ('synthetic-patient',81,180)")
        row = connection.execute("SELECT * FROM patients").fetchone()
        assert profile_bmi(row)["value"] == 25
        assert connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1


def test_missing_profile_or_measurement_is_insufficient():
    assert profile_bmi(None) is None
    assert profile_bmi({}) is None
    assert profile_bmi({"weight_kg": 81}) is None
