"""Synthetic BMI histories: provenance, source choice, chronology and invalidation."""
from __future__ import annotations

import pytest

from anamna.db import connect, utc_now
from anamna.garmin import purge_envelope
from anamna.devices.calculations import BMI_ID_PREFIX, refresh_device_calculations
from anamna.devices.queries import device_history_summary, device_metric_comparison, device_metric_values
from anamna.devices.reconcile import source_key, source_kind
from anamna.security import create_user
from anamna.web import app as web

from test_linked_metrics import _build, _device_day, _document, _observation


def _derived(connection):
    return connection.execute(
        "SELECT * FROM device_metric_days WHERE substr(id, 1, ?)=?", (len(BMI_ID_PREFIX), BMI_ID_PREFIX)
    ).fetchall()


def _history(tmp_path, *, height_day="2024-01-01", weight_day="2025-01-01", height=200, unit="cm"):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_height", height_day, height, unit)
    _device_day(settings, owner, "body_weight", weight_day, 80, "kg")
    return settings, owner


def test_bmi_recalculates_and_retains_both_inputs(tmp_path):
    settings, _ = _history(tmp_path)
    with connect(settings) as connection:
        assert refresh_device_calculations(connection) == {"added": 1, "updated": 0, "removed": 0}
        [bmi] = _derived(connection)
        assert bmi["value"] == 20
        assert bmi["source_name"] == "Calculated BMI"
        assert bmi["source_vendor"] == "Anamna"
        assert source_kind(dict(bmi)) == "calculated"
        comparison = device_metric_comparison(connection, bmi["owner_user_id"], "body_mass_index")
        assert comparison["sources"][0]["kind"] == "calculated"
        assert comparison["days"][0]["rows"][0]["source_kind"] == "calculated"
        assert bmi["day"] == "2025-01-01"
        inputs = connection.execute(
            "SELECT input_kind, input_day, input_value, input_unit FROM device_calculation_inputs ORDER BY input_kind"
        ).fetchall()
        assert [tuple(row) for row in inputs] == [
            ("device_height", "2024-01-01", 200, "cm"),
            ("device_weight", "2025-01-01", 80, "kg"),
        ]
        assert refresh_device_calculations(connection) == {"added": 0, "updated": 0, "removed": 0}
        created = bmi["created_at"]
        connection.execute("UPDATE device_metric_days SET value=100 WHERE metric_key='body_weight'")
        assert refresh_device_calculations(connection)["updated"] == 1
        [bmi] = _derived(connection)
        assert bmi["value"] == 25
        assert bmi["created_at"] == created
        connection.execute("DELETE FROM device_metric_days WHERE metric_key='body_height'")
        assert refresh_device_calculations(connection)["removed"] == 1
        assert _derived(connection) == []
        assert connection.execute("SELECT COUNT(*) FROM device_calculation_inputs").fetchone()[0] == 0


def test_reported_bmi_wins_and_removal_allows_fallback_again(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        refresh_device_calculations(connection)
    _device_day(settings, owner, "body_mass_index", "2025-01-01", 19.7, "kg/m²")
    with connect(settings) as connection:
        assert refresh_device_calculations(connection)["removed"] == 1
        assert _derived(connection) == []
        connection.execute("DELETE FROM device_metric_days WHERE metric_key='body_mass_index'")
        assert refresh_device_calculations(connection)["added"] == 1


@pytest.mark.parametrize("height,unit,expected", [(2, "m", 20), (200, "cm", 20), (200, "", None),
                                               (2, "ft", 215.28), (2000, "mm", 20)])
def test_height_requires_explicit_supported_units(tmp_path, height, unit, expected):
    settings, _ = _history(tmp_path, height=height, unit=unit)
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        rows = _derived(connection)
        assert (rows[0]["value"] if rows else None) == expected


@pytest.mark.parametrize("born,height_day,weight_day,expected", [
    ("2010-01-01", "2024-01-01", "2025-01-01", False),
    ("2010-01-01", "2025-01-01", "2025-01-01", True),
    (None, "2024-01-01", "2025-01-01", False),
    ("1990-01-01", "2025-01-02", "2025-01-01", False),
    ("2005-01-01", "2024-01-01", "2025-01-01", False),
])
def test_height_carry_forward_needs_adulthood_and_never_uses_future_height(tmp_path, born, height_day, weight_day, expected):
    settings, _ = _history(tmp_path, height_day=height_day, weight_day=weight_day)
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET date_of_birth=?", (born,))
        refresh_device_calculations(connection)
        assert bool(_derived(connection)) is expected


def test_profile_height_is_explicitly_undated_and_only_used_for_adults(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET height_cm=200")
        refresh_device_calculations(connection)
        assert _derived(connection)[0]["value"] == 20
        height = connection.execute("SELECT * FROM device_calculation_inputs WHERE input_kind='profile_height'").fetchone()
        assert height["input_day"] is None
        connection.execute("UPDATE patients SET date_of_birth='2010-01-01'")
        refresh_device_calculations(connection)
        assert _derived(connection) == []


def test_source_preference_changes_bmi_dependency_and_value(tmp_path):
    settings, owner = _history(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 100, "kg", vendor="Apple Health", name="Health")
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        first = _derived(connection)[0]["id"]
        apple = dict(connection.execute("SELECT * FROM device_metric_days WHERE source_vendor='Apple Health'").fetchone())
        connection.execute(
            "INSERT INTO device_source_preferences(owner_user_id, preference_group, source_key, updated_at) VALUES (?, 'body_weight', ?, '2025-01-01')",
            (owner, source_key(apple)),
        )
        counts = refresh_device_calculations(connection)
        [bmi] = _derived(connection)
        assert bmi["value"] == 25
        assert bmi["id"] != first
        assert counts == {"added": 1, "updated": 0, "removed": 1}


def test_verified_clinical_height_is_an_input_and_rejection_removes_bmi(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    _document(settings, owner, "height-doc", "Test Clinic", "consultation", "2024-01-01")
    _observation(settings, owner, "height-observation", "height-doc", "body-height", 200, "cm", "2024-01-01")
    with connect(settings) as connection:
        assert refresh_device_calculations(connection)["added"] == 0
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id='height-observation'")
        refresh_device_calculations(connection)
        assert _derived(connection)[0]["value"] == 20
        assert connection.execute("SELECT input_kind FROM device_calculation_inputs WHERE input_id='height-observation'").fetchone()[0] == "observation_height"
        connection.execute("UPDATE observations SET verification_status='rejected' WHERE id='height-observation'")
        assert refresh_device_calculations(connection)["removed"] == 1


@pytest.mark.parametrize("other_owner", [False, True])
def test_height_of_another_patient_or_owner_never_joins_weight(tmp_path, other_owner):
    settings, owner = _history(tmp_path)
    second_owner = create_user(settings, "second@example.test", "Second", "a-long-test-password") if other_owner else owner
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, created_at) VALUES ('other-patient', ?, 'Second Patient', '1990-01-01', ?)",
            (second_owner, utc_now()),
        )
        connection.execute(
            "UPDATE device_metric_days SET patient_id='other-patient', owner_user_id=? WHERE metric_key='body_height'",
            (second_owner,),
        )
        refresh_device_calculations(connection)
        assert _derived(connection) == []


def test_conflicting_same_day_dated_heights_do_not_choose_a_number(tmp_path):
    settings, owner = _history(tmp_path)
    _document(settings, owner, "height-doc", "Test Clinic", "consultation", "2024-01-01")
    _observation(settings, owner, "height-observation", "height-doc", "body-height", 190, "cm", "2024-01-01")
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id='height-observation'")
        refresh_device_calculations(connection)
        assert _derived(connection) == []


@pytest.mark.parametrize("scope,from_utc,until_utc", [
    ("origin", None, None),
    ("reading", "2025-01-01T10:00:00+00:00", None),
    ("window", "2024-12-31T23:00:00+00:00", "2025-01-01T12:00:00+00:00"),
])
def test_explicit_bmi_exclusion_cannot_be_recreated_from_retained_weight(tmp_path, scope, from_utc, until_utc):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, from_utc, until_utc, series, created_at)
               VALUES ('bmi-rule', ?, 'garmin', 'Garmin Index Scale', ?, ?, ?, '["body_mass_index"]', ?)""",
            (owner, scope, from_utc, until_utc, utc_now()),
        )
        assert refresh_device_calculations(connection)["removed"] == 1
        assert _derived(connection) == []
        assert connection.execute("SELECT value FROM device_metric_days WHERE metric_key='body_weight'").fetchone()[0] == 80
        connection.execute("UPDATE device_exclusions SET revoked_at=? WHERE id='bmi-rule'", (utc_now(),))
        assert refresh_device_calculations(connection)["added"] == 1


def test_exclusion_uses_writer_context_and_does_not_reach_other_origins_or_series(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, series, created_at)
               VALUES ('other-series', ?, 'garmin', 'Garmin Index Scale', 'origin', '["body_fat_percentage"]', ?)""",
            (owner, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, series, created_at)
               VALUES ('other-context', ?, 'apple_health', 'Garmin Index Scale', 'origin', '["body_mass_index"]', ?)""",
            (owner, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, series, created_at)
               VALUES ('other-source', ?, 'garmin', 'Other Scale', 'origin', '["body_mass_index"]', ?)""",
            (owner, utc_now()),
        )
        assert refresh_device_calculations(connection)["added"] == 1


def test_pending_weight_exclusion_withholds_dependent_bmi_before_reaggregation(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, series, created_at)
               VALUES ('weight-rule', ?, 'garmin', 'Garmin Index Scale', 'origin', '["body_weight"]', ?)""",
            (owner, utc_now()),
        )
        assert refresh_device_calculations(connection)["added"] == 0
        assert _derived(connection) == []


def test_openwearables_exclusion_matches_original_bridge_source(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE device_imports SET adapter_key='openwearables_api'")
        connection.execute(
            "UPDATE device_metric_days SET source_name='OpenWearables · apple · Connect · iPhone16,2', source_vendor='OpenWearables' WHERE metric_key='body_weight'"
        )
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   origin_device, scope, series, created_at)
               VALUES ('bridge-rule', ?, 'apple', 'Connect', 'iPhone16,2', 'origin', '["body_mass_index"]', ?)""",
            (owner, utc_now()),
        )
        assert refresh_device_calculations(connection)["added"] == 0


def test_openwearables_reading_exclusion_uses_local_body_day(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE users SET timezone='Europe/Kyiv'")
        connection.execute("UPDATE device_imports SET adapter_key='openwearables_api'")
        connection.execute(
            "UPDATE device_metric_days SET source_name='OpenWearables · apple · Connect · iPhone16,2', source_vendor='OpenWearables' WHERE metric_key='body_weight'"
        )
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   origin_device, scope, from_utc, series, created_at)
               VALUES ('bridge-rule', ?, 'apple', 'Connect', 'iPhone16,2', 'reading',
                   '2024-12-31T23:00:00+00:00', '["body_mass_index"]', ?)""",
            (owner, utc_now()),
        )
        assert refresh_device_calculations(connection)["added"] == 0


def test_invalid_reported_bmi_still_withholds_fallback_until_source_is_resolved(tmp_path):
    settings, owner = _history(tmp_path)
    _device_day(settings, owner, "body_mass_index", "2025-01-01", float("inf"), "unknown")
    with connect(settings) as connection:
        assert refresh_device_calculations(connection)["added"] == 0
        assert _derived(connection) == []


def test_rule_named_for_calculated_source_is_also_honoured(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        connection.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, origin_provider, origin_source,
                   scope, series, created_at)
               VALUES ('calculation-rule', ?, 'garmin', 'Calculated BMI', 'origin', '["body_mass_index"]', ?)""",
            (owner, utc_now()),
        )
        assert refresh_device_calculations(connection)["removed"] == 1
        assert _derived(connection) == []


def test_clinical_calculated_bmi_outranks_device_fallback(tmp_path):
    settings, owner = _history(tmp_path)
    _document(settings, owner, "bmi-doc", "Test Clinic", "consultation", "2025-01-01")
    _observation(settings, owner, "bmi-observation", "bmi-doc", "body-mass-index", 20, "kg/m²", "2025-01-01")
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET extraction_method='derived_bmi' WHERE id='bmi-observation'")
        assert refresh_device_calculations(connection)["added"] == 0
        assert _derived(connection) == []


def test_changed_profile_height_invalidates_device_memo_without_restamping_measurement(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET height_cm=200")
        refresh_device_calculations(connection)
    with connect(settings) as connection:
        before = web._fingerprint(connection, owner, "device")
        created = _derived(connection)[0]["created_at"]
        cards = web._device_rows(connection, owner)
        assert next(card["latest_numeric"] for card in cards if card["id"] == "device:body_mass_index") == 20
        connection.execute("UPDATE patients SET height_cm=160")
        assert refresh_device_calculations(connection)["updated"] == 1
    # Owner invalidation deliberately retains _DEVICE_ONLY; its own persisted
    # calculation revision must detect a recalculation by another process.
    web.invalidate_catalog(owner)
    with connect(settings) as connection:
        assert web._fingerprint(connection, owner, "device") != before
        assert _derived(connection)[0]["created_at"] == created
        cards = web._device_rows(connection, owner)
        assert next(card["latest_numeric"] for card in cards if card["id"] == "device:body_mass_index") == 31.25
        revision = connection.execute(
            "SELECT revision FROM device_calculation_revisions WHERE owner_user_id=?", (owner,)
        ).fetchone()[0]
        assert refresh_device_calculations(connection) == {"added": 0, "updated": 0, "removed": 0}
        assert connection.execute(
            "SELECT revision FROM device_calculation_revisions WHERE owner_user_id=?", (owner,)
        ).fetchone()[0] == revision


@pytest.mark.parametrize("metric,unit,primary_value,other_value,group", [
    ("body_weight", "kg", 80, 100, "body_weight"),
    ("sleep_duration", "hours", 8, 10, "sleep"),
])
def test_patient_filter_precedes_daily_source_selection(tmp_path, metric, unit, primary_value, other_value, group):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, metric, "2025-01-01", primary_value, unit)
    _device_day(settings, owner, metric, "2025-01-01", other_value, unit, vendor="Apple Health", name="Other device")
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES ('other-patient', ?, 'Second Patient', ?)",
            (owner, utc_now()),
        )
        connection.execute("UPDATE device_metric_days SET patient_id='other-patient' WHERE source_vendor='Apple Health'")
        other = dict(connection.execute("SELECT * FROM device_metric_days WHERE patient_id='other-patient'").fetchone())
        connection.execute(
            "INSERT INTO device_source_preferences(owner_user_id, preference_group, source_key, updated_at) VALUES (?, ?, ?, ?)",
            (owner, group, source_key(other), utc_now()),
        )
        assert device_metric_values(connection, owner, metric)[0]["value"] == other_value
        primary = device_metric_values(connection, owner, metric, patient_id=f"patient-{owner}")
        assert len(primary) == 1
        assert primary[0]["value"] == primary_value
        assert device_metric_values(connection, owner, metric, patient_id="absent-patient") == []


def test_history_keeps_calculated_provenance_when_latest_bmi_was_reported(tmp_path):
    settings, owner = _history(tmp_path, height_day="2023-01-01", weight_day="2023-02-01")
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    _device_day(settings, owner, "body_mass_index", "2025-01-02", 20, "kg/m²")
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        summary = next(item for item in device_history_summary(connection, owner) if item["metric_key"] == "body_mass_index")
        assert summary["verification_status"] == "device_measurement"
        assert summary["calculated_day_count"] == 2
        assert summary["recent_days"][0]["extraction_method"] is None
        for reading in summary["recent_days"][1:]:
            assert reading["extraction_method"] == "derived_bmi"
            assert reading["verification_status"] == "extracted"
            assert len(reading["calculation_inputs"]) == 2
        assert summary["months"][0]["calculated_day_count"] == 1
        assert summary["years"][0]["calculated_day_count"] == 1


@pytest.mark.parametrize("key", ["body_weight", "body_height"])
def test_partial_envelope_purge_removes_dependent_bmi(tmp_path, key):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        assert len(_derived(connection)) == 1
        purge_envelope(connection, owner, "garmin", keys=[key])
        assert _derived(connection) == []
        assert connection.execute("SELECT COUNT(*) FROM device_calculation_inputs").fetchone()[0] == 0


def test_purging_height_envelope_removes_bmi_owned_by_another_import(tmp_path):
    settings, owner = _history(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, imported_at)
               SELECT 'height-import', owner_user_id, patient_id, vendor_id, 'garmin_api',
                   source_path, 'height-fingerprint', source_bytes, imported_at
               FROM device_imports WHERE id='imp-1'"""
        )
        connection.execute("UPDATE device_metric_days SET import_id='height-import' WHERE metric_key='body_height'")
        refresh_device_calculations(connection)
        assert _derived(connection)[0]["import_id"] == "imp-1"
        purge_envelope(connection, owner, "garmin_api", drop_envelope=True)
        assert _derived(connection) == []
        assert connection.execute("SELECT COUNT(*) FROM device_metric_days WHERE metric_key='body_weight'").fetchone()[0] == 1
