"""Synthetic raw-to-metric coverage and source-unit regression evidence."""
from __future__ import annotations

import json
import importlib.util
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anamna import openwearables as ow
from anamna.db import connect, utc_now
from anamna.devices.apple_health import AppleHealthAdapter
from anamna.devices.oura_export import OuraAdapter, distinct_sleep_periods
from anamna.devices.structured import GarminAdapter
from anamna.devices.timezone import zone
from anamna.devices.units import plausible_aggregates
from test_openwearables_webhooks import linked_record  # noqa: F401 - fixture


def _values(bucket):
    return {item.definition.key: item.value for item in bucket.values()}


@pytest.mark.parametrize("spacing", ["", "\n", "\r\n"])
def test_apple_xml_structure_not_line_layout_controls_record_import(tmp_path, spacing):
    xml = tmp_path / "export.xml"
    xml.write_text(spacing.join([
        '<HealthData><Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexFemale"/>',
        '<Record\n type="HKQuantityTypeIdentifierStepCount" sourceName="Synthetic &amp; watch" '
        'unit="count" startDate="2026-01-01 12:00:00 +0000" endDate="2026-01-01 12:01:00 +0000" value="0"/>',
        '<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Synthetic &amp; watch" unit="count" '
        'startDate="2026-01-01 12:01:00 +0000" endDate="2026-01-01 12:02:00 +0000" value="12"/>',
        '<Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Synthetic watch" '
        'startDate="2026-01-01 12:00:00 +0000" endDate="2026-01-01 12:10:00 +0000" '
        'duration="10" durationUnit="min"/>',
        '</HealthData>',
    ]), encoding="utf-8")
    result = AppleHealthAdapter().parse(xml, zone("UTC"))
    assert result.raw_record_count == 3
    assert len(result.workouts) == 1
    assert result.metadata["identity"]["biological_sex"] == "female"
    steps = next(item for item in result.aggregates if item.definition.key == "steps")
    assert steps.value == 12 and steps.sample_count == 2
    assert steps.source_name == "Synthetic & watch"


@pytest.mark.parametrize("series,key,unit,value,expected", [
    ("body_temperature", "body_temperature", "fahrenheit", 98.6, 37),
    ("heart_rate_variability_sdnn", "heart_rate_variability", "ms", 30, 30),
    ("heart_rate_variability_rmssd", "heart_rate_variability_rmssd", "ms", 40, 40),
    ("sleeping_breathing_disturbances", "breathing_disturbances", "count", 0, 0),
    ("respiratory_rate", "respiratory_rate", "brpm", 12, 12),
    ("oxygen_saturation", "blood_oxygen", "percent", 96, 96),
    ("average_met", "physical_effort", "met", 2, 2),
    ("physical_effort", "physical_effort", "met", 2, 2),
    ("weather_temperature", "weather_temperature", "celsius", 0, 0),
    ("weather_humidity", "weather_humidity", "percent", 50, 50),
])
def test_supported_raw_channel_reaches_its_distinct_quantity(series, key, unit, value, expected):
    bucket = {}
    assert ow.map_raw_metrics([{
        "type": series, "timestamp": "2026-01-01T12:00:00Z", "value": value, "unit": unit,
        "source": {"provider": "apple"},
    }], bucket, zone("UTC")) == set()
    assert _values(bucket) == {key: pytest.approx(expected)}


def test_explicit_metre_waist_converts_but_bad_centimetre_label_is_not_repaired():
    bucket = {}
    ow._map_body_series([
        {"type": "waist_circumference", "timestamp": "2026-01-01T12:00:00Z", "value": 0.9, "unit": "m"},
        {"type": "waist_circumference", "timestamp": "2026-01-02T12:00:00Z", "value": 0.9, "unit": "cm"},
    ], bucket, zone("UTC"))
    kept = plausible_aggregates(bucket.values())
    assert [(item.day, item.value) for item in kept] == [("2026-01-01", 90)]


@pytest.mark.parametrize("row,expected", [
    ({"nap_count": 1, "nap_duration_minutes": 25}, {"sleep_naps": 1, "sleep_nap_duration": 25}),
    ({"nap_count": 0, "nap_duration_minutes": 0}, {}),
    ({"nap_count": 0, "nap_duration_minutes": 0, "sessions": [{"is_nap": False}]},
     {"sleep_naps": 0, "sleep_nap_duration": 0}),
    ({"nap_count": 0, "nap_duration_minutes": 0, "sessions": [{}]}, {}),
    ({"nap_count": -1, "nap_duration_minutes": -1, "sessions": [{"is_nap": False}]}, {}),
    ({"nap_count": 1.5, "nap_duration_minutes": None}, {}),
])
def test_nap_metrics_distinguish_positive_evidence_classified_zero_and_unknown(row, expected):
    bucket = {}
    ow._map_sleep([{"date": "2026-01-01", **row}], bucket, zone("UTC"))
    assert _values(bucket) == expected


def test_raw_hrv_rebuild_preserves_other_source_summary_and_archive_holes(linked_record):
    settings, owner = linked_record
    remote, server, _generation = ow.account_identity(settings, owner)
    source = {"provider": "oura", "device": "Synthetic ring"}
    envelope = ow.ensure_envelope(settings, owner)
    with connect(settings) as db:
        for day in ("2026-01-01", "2026-01-02"):
            row = {"date": day, "avg_hrv_rmssd_ms": 40, "source": source}
            db.execute("INSERT INTO openwearables_raw_records VALUES (?,?,?,?,?,?,?,?)",
                       (owner, server, remote, "sleep", day, day, json.dumps(row), utc_now()))
        raw = {"type": "heart_rate_variability_rmssd", "timestamp": "2026-01-01T12:00:00Z", "value": 50,
               "unit": "ms", "source": source}
        db.execute("INSERT INTO openwearables_raw_samples VALUES (?,?,?,?,?,?,?,?)",
                   (owner, server, remote, "synthetic-rmssd", raw["timestamp"], raw["type"], json.dumps(raw), utc_now()))
        ow.recompute_raw_days(settings, db, owner, envelope, ow.account_identity(settings, owner),
                              "2026-01-01", "2026-01-02", zone("UTC"))
    with connect(settings) as db:
        values = dict(db.execute("SELECT day,value FROM device_metric_days WHERE metric_key='heart_rate_variability_rmssd'"))
    assert values == {"2026-01-01": 50, "2026-01-02": 40}


def test_oura_identical_acquisitions_deduplicate_and_conflicting_overlaps_are_withheld():
    period = {"id": "a", "day": "2026-01-02", "type": "long_sleep",
              "bedtime_start": "2026-01-01T22:00:00+00:00",
              "bedtime_end": "2026-01-02T06:00:00+00:00", "total_sleep_duration": 25200}
    assert distinct_sleep_periods([period, {**period, "id": "b"}]) == [period]
    following = {**period, "id": "c", "bedtime_start": period["bedtime_end"],
                 "bedtime_end": "2026-01-02T07:00:00+00:00"}
    assert len(distinct_sleep_periods([period, following])) == 2
    rescored = {**period, "id": "b", "total_sleep_duration": 25000}
    withheld = []
    assert distinct_sleep_periods([period, rescored, following], withheld) == [following]
    assert withheld == [period, rescored]
    # An interval that cannot be read, or cannot be placed, is withheld too.
    backwards = {**following, "id": "d", "bedtime_end": following["bedtime_start"]}
    unplaced = {**following, "id": "e", "bedtime_start": "2026-01-05T22:00:00", "bedtime_end": "2026-01-06T06:00:00"}
    withheld = []
    assert distinct_sleep_periods([period, backwards, unplaced, {"id": "f", "day": "2026-01-09"}], withheld) == [
        period, {"id": "f", "day": "2026-01-09"}]
    assert withheld == [backwards, unplaced]


def test_oura_export_long_duration_retains_independent_hrv(tmp_path):
    source = tmp_path / "sleep.json"
    source.write_text(json.dumps([{"day": "2026-01-02", "total_sleep_duration": 72000,
                                  "time_in_bed": 75600, "average_hrv": 40}]), encoding="utf-8")
    parsed = OuraAdapter().parse(source, tz=zone("UTC"))
    values = {item.definition.key: item.value for item in parsed.aggregates}
    assert values["sleep_duration"] == 20
    assert values["time_in_bed"] == 21
    assert values["heart_rate_variability_rmssd"] == 40
    assert parsed.metadata["quarantined_sleep_days"] == []


def test_invalid_sleep_duration_does_not_cancel_a_valid_period_or_its_hrv():
    from anamna import oura

    bucket = {}
    oura._map_sleep([
        {"day": "2026-01-02", "type": "long_sleep", "total_sleep_duration": 27000, "average_hrv": 40},
        {"day": "2026-01-02", "type": "late_nap", "total_sleep_duration": -1800},
    ], bucket)
    assert _values(bucket)["sleep_duration"] == 7.5
    assert _values(bucket)["heart_rate_variability_rmssd"] == 40


def test_garmin_unknown_impedance_unit_is_accounted_for_without_inventing_ohms(tmp_path):
    source = tmp_path / "synthetic_userBioMetrics.json"
    source.write_text(json.dumps([
        {"metaData": {"calendarDate": f"2026-01-0{index + 1}T12:00:00"},
         "weight": {"sourceType": "INDEX_SCALE", "weight": 70000, "rawImpedance": impedance}}
        for index, impedance in enumerate([0, 500])
    ]), encoding="utf-8")
    parsed = GarminAdapter().parse(source)
    coverage = parsed.metadata["uninterpreted_fields"]["weight.rawImpedance"]
    assert coverage["records"] == 2 and coverage["positive_records"] == 1
    assert "undocumented" in coverage["reason"]
    assert {item.definition.key for item in parsed.aggregates} == {"body_weight"}


_FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
_FIT_SCALE_FIELDS = {"weight": (0, 100), "percent_fat": (1, 100), "percent_hydration": (2, 100),
                     "bone_mass": (4, 100), "muscle_mass": (5, 100), "bmi": (13, 10)}


def _fit_file(global_number, fields):
    """A minimal FIT file: one definition and one data message. `fields` is (number, struct code, value)."""
    from anamna.devices.structured import _fit_crc

    sizes = {"I": (4, 0x86), "H": (2, 0x84), "B": (1, 0x00)}
    body = struct.pack("<BBBHB", 0x40, 0, 0, global_number, len(fields))
    body += b"".join(bytes([number, *sizes[code]]) for number, code, _ in fields)
    body += bytes(1) + b"".join(struct.pack("<" + code, value) for _, code, value in fields)
    data = struct.pack("<BBHI4sH", 14, 0x20, 2100, len(body), b".FIT", 0) + body
    return data + struct.pack("<H", _fit_crc(data))


def _fit_weight_archive(root, rows):
    with zipfile.ZipFile(root / "synthetic-scale.zip", "w") as archive:
        for index, row in enumerate(rows):
            fields = [(253, "I", int((row["timestamp"] - _FIT_EPOCH).total_seconds()))]
            fields += [(number, "H", round(row[name] * scale)) for name, (number, scale) in _FIT_SCALE_FIELDS.items() if name in row]
            archive.writestr(f"synthetic-{index}.fit", _fit_file(30, fields))


def test_garmin_fit_capture_absent_from_json_is_withheld_and_exact_utc_json_is_kept(tmp_path):
    matched = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    independent = datetime(2026, 1, 2, 22, 30, tzinfo=UTC)
    _fit_weight_archive(tmp_path, [
        {"timestamp": matched, "weight": 71, "percent_fat": 24},
        {"timestamp": independent, "weight": 72, "percent_fat": 25, "percent_hydration": 50,
         "bone_mass": 3, "muscle_mass": 40, "bmi": 23},
        {"timestamp": independent, "weight": 72, "percent_fat": 25, "percent_hydration": 50,
         "bone_mass": 3, "muscle_mass": 40, "bmi": 23},
    ])
    (tmp_path / "synthetic_userBioMetrics.json").write_text(json.dumps([
        {"metaData": {"calendarDate": "2026-01-02T00:30:00+02:00"}, "weight": {
            "sourceType": "INDEX_SCALE", "timestampGMT": "2026-01-01T22:30:00", "weight": 70000, "bodyFat": 23}},
    ]), encoding="utf-8")
    parsed = GarminAdapter().parse(tmp_path, tz=zone("Europe/Kyiv"))
    weights = [item for item in parsed.aggregates if item.definition.key == "body_weight"]
    assert [(item.day, item.value, item.sample_count) for item in weights] == [("2026-01-02", 70, 1)]
    # The account's JSON does not hold the second capture, so nothing says it
    # is this person's: no aggregate, under any source name.
    assert {item.source_name for item in parsed.aggregates} == {"Garmin Index Scale"}
    assert {item.definition.key for item in parsed.aggregates} == {"body_weight", "body_fat_percentage"}
    assert parsed.raw_record_count == 1
    coverage = parsed.metadata["fit_scale_coverage"]
    assert coverage["matched_json_records"] == 1
    assert coverage["unmatched_json_records"] == coverage["withheld_unmatched_records"] == 1
    assert coverage["repeated_fit_timestamps"] == 1
    assert "accepted_unmatched_records" not in coverage


def test_only_weight_scale_fit_members_are_decoded_and_each_is_read_once(tmp_path, monkeypatch):
    from anamna.devices import structured

    _fit_weight_archive(tmp_path, [{"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "weight": 70}])
    with zipfile.ZipFile(tmp_path / "synthetic-scale.zip", "a") as archive:
        for index in range(3):
            archive.writestr(f"synthetic-activity-{index}.fit", _fit_file(0, [(0, "B", 4)]))
    decoded, reads = [], []
    real_rows, real_read = structured._fit_weight_scale_rows, zipfile.ZipFile.read
    monkeypatch.setattr(structured, "_fit_weight_scale_rows", lambda data: decoded.append(1) or real_rows(data))
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda self, name, *a, **k: reads.append(1) or real_read(self, name, *a, **k))
    parsed = GarminAdapter().parse(tmp_path, tz=zone("UTC"))
    assert len(decoded) == 1 and len(reads) == 4
    assert parsed.metadata["fit_archive_counts"] == {"entries": 4, "weight_scale": 1, "other": 3}
    assert parsed.metadata["fit_scale_coverage"]["weight_scale_messages"] == 1


def test_garmin_fit_rejects_existing_product_bounds_and_conflicting_captures(tmp_path):
    _fit_weight_archive(tmp_path, [
        {"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "weight": 10, "percent_fat": 25},
        {"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "weight": 70},
        {"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "weight": 71},
    ])
    parsed = GarminAdapter().parse(tmp_path, tz=zone("UTC"))
    assert parsed.aggregates == []
    assert parsed.metadata["fit_scale_coverage"]["product_weight_bounds_rejected"] == 1
    assert parsed.metadata["fit_scale_coverage"]["conflicting_fit_records"] == 2


@pytest.mark.parametrize("remove_capture_accounting", [False, True])
def test_fit_validator_accounts_different_utc_captures_on_the_same_day(tmp_path, remove_capture_accounting):
    _fit_weight_archive(tmp_path, [
        {"timestamp": datetime(2026, 1, 2, 12, tzinfo=UTC), "weight": 71},
        {"timestamp": datetime(2026, 1, 2, 13, tzinfo=UTC), "weight": 72},
    ])
    (tmp_path / "synthetic_userBioMetrics.json").write_text(json.dumps([
        {"metaData": {"calendarDate": "2026-01-02T12:00:00Z"}, "weight": {
            "sourceType": "INDEX_SCALE", "timestampGMT": "2026-01-02T12:00:00", "weight": 70000}},
    ]), encoding="utf-8")
    parsed = GarminAdapter().parse(tmp_path, tz=zone("UTC"))
    coverage = parsed.metadata["fit_scale_coverage"]
    assert coverage["matched_json_records"] == coverage["withheld_unmatched_records"] == 1
    if remove_capture_accounting:
        coverage["withheld_unmatched_records"] = 0
    path = Path(__file__).resolve().parents[2] / "scripts/validate_device_imports.py"
    spec = importlib.util.spec_from_file_location("device_validator", path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    errors = []
    validator._check_garmin_scale({"metadata": parsed.metadata}, {}, [], errors)
    assert bool(errors) == remove_capture_accounting


def test_garmin_fit_crc_failure_is_diagnosed_and_never_normalized(tmp_path):
    _fit_weight_archive(tmp_path, [{"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "weight": 70}])
    source = tmp_path / "synthetic-scale.zip"
    with zipfile.ZipFile(source) as archive:
        raw = bytearray(archive.read("synthetic-0.fit"))
    raw[-1] ^= 0xFF
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("synthetic-0.fit", raw)
    parsed = GarminAdapter().parse(tmp_path, tz=zone("UTC"))
    assert parsed.aggregates == []
    assert parsed.metadata["fit_scale_coverage"]["decode_errors"] == 1
