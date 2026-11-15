"""Review findings on the device importers: synthetic regressions only."""
from __future__ import annotations

import json

import pytest

from anamna import garmin
from anamna import openwearables as ow
from anamna.db import connect
from anamna.devices import exclusions
from anamna.devices.apple_health import AppleHealthAdapter, _sleep_hours
from anamna.devices.calculations import BMI_ID_PREFIX, refresh_device_calculations
from anamna.devices.catalog import metric
from anamna.devices.importer import import_device_export
from anamna.devices.models import Aggregate
from anamna.devices.oura_export import OuraAdapter, quarantine_sleep
from anamna.devices.timezone import zone
from anamna.devices.units import plausible_aggregates, plausible_value

from test_linked_metrics import _build, _device_day, _document, _observation
from test_openwearables_webhooks import linked_record  # noqa: F401 - fixture
from test_oura_sleep_day import PERIODS, period, sleep_hours, write_takeout

SENTINEL = "2000-01-01T00:00:00+00:00"


def _derived(connection):
    return connection.execute(
        "SELECT * FROM device_metric_days WHERE substr(id, 1, ?)=?", (len(BMI_ID_PREFIX), BMI_ID_PREFIX)
    ).fetchall()


# --- sleep: a day holds 24 hours ----------------------------------------------

def _apple_sleep(tmp_path, start, end, value="InBed"):
    xml = tmp_path / "export.xml"
    xml.write_text(
        '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Synthetic phone" '
        f'startDate="{start}" endDate="{end}" value="HKCategoryValueSleepAnalysis{value}"/></HealthData>',
        encoding="utf-8",
    )
    return AppleHealthAdapter().parse(xml, zone("UTC"))


def test_apple_interval_longer_than_a_day_is_not_sleep_and_a_long_night_still_is(tmp_path):
    week = _apple_sleep(tmp_path, "2026-01-01 22:00:00 +0000", "2026-01-08 22:00:00 +0000")
    assert week.aggregates == []
    night = _apple_sleep(tmp_path, "2026-01-01 20:00:00 +0000", "2026-01-02 16:00:00 +0000")
    assert [(item.definition.key, item.value) for item in night.aggregates] == [("time_in_bed", 20)]
    assert _sleep_hours("2026-01-01 00:00:00 +0000", "2026-01-02 00:00:00 +0000") == 24
    assert _sleep_hours("2026-01-01 00:00:00 +0000", "2026-01-02 00:00:01 +0000") is None


@pytest.mark.parametrize("key", ["sleep_duration", "time_in_bed", "sleep_core", "sleep_deep", "sleep_rem", "sleep_awake"])
def test_daily_sleep_value_over_24_hours_is_never_stored(key):
    assert plausible_value(key, 24) == 24 and plausible_value(key, 20) == 20
    assert plausible_value(key, 24.5) is None and plausible_value(key, 168) is None
    item = Aggregate(metric(key, key, "device_sleep", "hours", "sum"), "2026-01-01", "Synthetic", "Synthetic")
    item.add(168, "2026-01-01T08:00:00Z")
    assert plausible_aggregates([item]) == []
    kept, withheld = quarantine_sleep([item])
    assert kept == [] and withheld[0]["reason"] == "longer than 24 hours" and withheld[0]["day"] == "2026-01-01"


# --- Apple Health: a damaged export.xml ---------------------------------------

def test_truncated_apple_export_fails_with_a_message_that_names_nothing(tmp_path):
    folder = tmp_path / "Surname export"
    folder.mkdir()
    xml = folder / "export.xml"
    xml.write_text(
        '<HealthData><Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Private scale" unit="kg" '
        'value="80" startDate="2026-01-01 08:00:00 +0000" endDate="2026-01-01 08:00:00 +0000"/><Record type="HKQuan',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as caught:
        AppleHealthAdapter().parse(xml, zone("UTC"))
    message = str(caught.value)
    assert message == "Apple Health export.xml is truncated or is not well-formed XML"
    assert "Surname" not in message and "Private" not in message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- Oura: overlapping periods that differ ------------------------------------

def test_oura_takeout_with_a_rescored_night_and_a_nap_inside_a_night_still_imports(tmp_path, monkeypatch):
    extra = [
        # The 20th again, scored differently.
        period("b2", "2026-02-20", "long_sleep", "2026-02-19T22:00:00.000+02:00", "2026-02-20T07:00:00.000+02:00", 27000, 32400),
        # A nap recorded inside the night of the 25th.
        period("n", "2026-02-25", "sleep", "2026-02-25T02:00:00.000+02:00", "2026-02-25T02:30:00.000+02:00", 1200, 1800),
    ]
    monkeypatch.setattr("test_oura_sleep_day.PERIODS", [*PERIODS, *extra])
    parsed = OuraAdapter().parse(write_takeout(tmp_path))
    # Neither answer for a contested night is published, and nothing is summed.
    assert sleep_hours(parsed) == {"2026-02-19": 6.667, "2026-02-21": 6.333, "2026-02-22": 6.167}
    assert set(sleep_hours(parsed, "time_in_bed")) == {"2026-02-19", "2026-02-21", "2026-02-22"}
    assert parsed.metadata["quarantined_sleep_days"] == [
        {"day": day, "source": "Oura", "metric": "sleep_duration", "reason": "overlapping sleep periods that differ"}
        for day in ("2026-02-20", "2026-02-25")
    ]


def test_oura_legacy_export_withholds_only_the_sleep_of_the_contested_day(tmp_path):
    night = {"day": "2026-01-02", "bedtime_start": "2026-01-01T22:00:00+00:00",
             "bedtime_end": "2026-01-02T06:00:00+00:00", "total_sleep_duration": 25200}
    source = tmp_path / "export.json"
    source.write_text(json.dumps([
        night, {**night, "total_sleep_duration": 25000},
        {"day": "2026-01-02", "steps": 5000},
        {"day": "2026-01-03", "bedtime_start": "2026-01-02T22:00:00+00:00",
         "bedtime_end": "2026-01-03T06:00:00+00:00", "total_sleep_duration": 28800},
    ]), encoding="utf-8")
    parsed = OuraAdapter().parse(source, tz=zone("UTC"))
    values = {(item.definition.key, item.day): item.value for item in parsed.aggregates}
    assert values == {("steps", "2026-01-02"): 5000, ("sleep_duration", "2026-01-03"): 8}
    assert [item["day"] for item in parsed.metadata["quarantined_sleep_days"]] == ["2026-01-02"]


# --- calculated BMI: which height ----------------------------------------------

def test_profile_height_still_covers_adult_weights_older_than_the_first_measured_height(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2023-01-01", 80, "kg")
    _device_day(settings, owner, "body_weight", "2025-01-01", 81, "kg")
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET height_cm=200")
        refresh_device_calculations(connection)
        assert {row["day"]: row["value"] for row in _derived(connection)} == {"2023-01-01": 20, "2025-01-01": 20.25}
    # One later measured height must not take the earlier BMI away.
    _device_day(settings, owner, "body_height", "2024-06-01", 180, "cm")
    with connect(settings) as connection:
        refresh_device_calculations(connection)
        assert {row["day"]: row["value"] for row in _derived(connection)} == {"2023-01-01": 20, "2025-01-01": 25}
        kinds = {row["input_day"]: row["input_kind"] for row in connection.execute(
            "SELECT input_kind, input_day FROM device_calculation_inputs WHERE input_kind LIKE '%height'")}
        assert kinds == {None: "profile_height", "2024-06-01": "device_height"}
        # A child's weight still needs a height of its own day.
        connection.execute("UPDATE patients SET date_of_birth='2010-01-01'")
        refresh_device_calculations(connection)
        assert _derived(connection) == []


def test_same_day_heights_within_half_a_centimetre_agree_and_real_disagreement_uses_the_previous_day(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    _device_day(settings, owner, "body_height", "2023-01-01", 160, "cm")
    _device_day(settings, owner, "body_height", "2024-01-01", 200.3, "cm")
    _document(settings, owner, "height-doc", "Test Clinic", "consultation", "2024-01-01")
    _observation(settings, owner, "height-observation", "height-doc", "body-height", 200, "cm", "2024-01-01")
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id='height-observation'")
        refresh_device_calculations(connection)
        # 200 and 200.3 are one height; the verified observation is the one used.
        assert [row["value"] for row in _derived(connection)] == [20]
        assert connection.execute(
            "SELECT input_id FROM device_calculation_inputs WHERE input_kind LIKE '%height'").fetchone()[0] == "height-observation"
        # 200 against 190.3 is a disagreement: the previous eligible day speaks.
        connection.execute("UPDATE device_metric_days SET value=190.3 WHERE metric_key='body_height' AND day='2024-01-01'")
        refresh_device_calculations(connection)
        assert [row["value"] for row in _derived(connection)] == [31.25]
        assert connection.execute(
            "SELECT input_day FROM device_calculation_inputs WHERE input_kind LIKE '%height'").fetchone()[0] == "2023-01-01"
        # With no earlier day and no profile height there is still no number.
        connection.execute("DELETE FROM device_metric_days WHERE metric_key='body_height' AND day='2023-01-01'")
        refresh_device_calculations(connection)
        assert _derived(connection) == []


# --- calculated BMI: a re-read is not a change -----------------------------------

def _stamp(settings):
    """Mark the calculated row, and return what a needless rewrite would change."""
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET created_at=? WHERE id LIKE 'derived-bmi-%'", (SENTINEL,))
        return _state(db)


def _state(db):
    rows = [(row["id"], row["value"], row["created_at"]) for row in _derived(db)]
    return rows, db.execute("SELECT revision FROM device_calculation_revisions").fetchall()[0][0]


def test_reimport_keeps_the_calculated_bmi_row_and_removes_it_with_its_weight(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = settings.source_dir / "apple" / "export.xml"
    source.parent.mkdir()
    source.write_text(
        '<HealthData><Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Synthetic scale" unit="kg" '
        'value="80" startDate="2025-01-01 08:00:00 +0000" endDate="2025-01-01 08:00:00 +0000"/></HealthData>',
        encoding="utf-8",
    )
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200")

    def read():
        return import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner,
                                    vendor_key="apple_health", source=source)

    read()
    before = _stamp(settings)
    assert [row[1] for row in before[0]] == [20]
    read()
    with connect(settings) as db:
        assert _state(db) == before
    # The re-read that removes the weight removes what was calculated from it.
    exclusions.create(settings, owner, owner, provider="apple_health", source="Synthetic scale", scope="origin")
    assert exclusions.run_pending(settings, owner) == 1
    with connect(settings) as db:
        assert _derived(db) == []
        assert not db.execute("SELECT 1 FROM device_metric_days WHERE metric_key='body_weight'").fetchone()
        assert not db.execute("SELECT 1 FROM device_calculation_inputs").fetchone()


def test_provider_window_replacement_keeps_the_calculated_bmi_row_and_removes_it_with_its_weight(tmp_path):
    settings, owner, _ = _build(tmp_path)
    keys = ["body_weight", "body_mass_index"]
    weight = Aggregate(metric("body_weight", "Body weight", "device_body", "kg", "latest"), "2025-01-01", "Synthetic scale", "Garmin")
    weight.add(80, "2025-01-01T08:00:00Z")
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200")
        garmin.replace_metric_days(db, owner, "imp-1", keys, [weight.day], [weight])
    before = _stamp(settings)
    assert [row[1] for row in before[0]] == [20]
    with connect(settings) as db:
        garmin.replace_metric_days(db, owner, "imp-1", keys, [weight.day], [weight])
        assert _state(db) == before
        garmin.replace_metric_days(db, owner, "imp-1", keys, [weight.day], [])
        assert _derived(db) == []


def test_openwearables_body_sync_keeps_the_calculated_bmi_row_and_removes_it_with_its_weight(linked_record):  # noqa: F811
    settings, owner = linked_record
    keys, window = ("body_weight", "body_mass_index"), ("2025-01-01", "2025-01-01")
    weight = Aggregate(metric("body_weight", "Body weight", "device_body", "kg", "latest"), "2025-01-01",
                       "OpenWearables · synthetic scale", "OpenWearables")
    weight.add(80, "2025-01-01T08:00:00Z")
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200, date_of_birth='1990-01-01'")
    envelope, identity = ow.ensure_envelope(settings, owner), ow.account_identity(settings, owner)
    ow._write_days(settings, owner, envelope, [weight], keys, *window, identity)
    before = _stamp(settings)
    assert [row[1] for row in before[0]] == [20]
    ow._write_days(settings, owner, envelope, [weight], keys, *window, identity)
    with connect(settings) as db:
        assert _state(db) == before
    ow._write_days(settings, owner, envelope, [], keys, *window, identity)
    with connect(settings) as db:
        assert _derived(db) == []
