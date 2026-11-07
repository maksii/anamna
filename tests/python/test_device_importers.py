from __future__ import annotations

import csv
import json

from anamna.devices.apple_health import AppleHealthAdapter
from anamna.devices.kardia import KardiaAdapter
from anamna.devices.structured import GarminAdapter, OuraAdapter
from anamna.oura import DEFS as OURA_API_DEFS


def write_semicolon_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def test_apple_health_streams_deduplicates_and_keeps_origin_vendor(tmp_path):
    export = tmp_path / "export.xml"
    export.write_text(
        """<?xml version="1.0"?>
<HealthData>
 <Me HKCharacteristicTypeIdentifierDateOfBirth="1990-03-14" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>
 <Record type="HKQuantityTypeIdentifierOxygenSaturation" sourceName="Oura" unit="%" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:00:00 +0200" value="0.98"/>
 <Record type="HKQuantityTypeIdentifierOxygenSaturation" sourceName="Oura" unit="%" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:00:00 +0200" value="0.98"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Oura" startDate="2026-01-01 23:00:00 +0200" endDate="2026-01-02 01:00:00 +0200" value="HKCategoryValueSleepAnalysisAsleepDeep"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Oura" startDate="2026-01-02 12:00:00 +0200" endDate="2026-01-02 12:30:00 +0200" duration="30" durationUnit="min"/>
 <Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="Connect" startDate="2026-01-02 12:00:00 +0200" endDate="2026-01-02 12:00:00 +0200"/>
</HealthData>""",
        encoding="utf-8",
    )

    parsed = AppleHealthAdapter().parse(tmp_path)
    by_key = {item.definition.key: item for item in parsed.aggregates}

    assert by_key["blood_oxygen"].value == 98
    assert by_key["blood_oxygen"].sample_count == 1
    assert by_key["blood_oxygen"].source_vendor == "Oura"
    assert by_key["sleep_deep"].value == 2
    assert by_key["sleep_duration"].value == 2
    assert parsed.metadata["deduplicated_samples"] == 1
    assert parsed.metadata["identity"]["date_of_birth"] == "1990-03-14"
    assert parsed.metadata["source_vendor_counts"]["Oura"] == 4
    assert parsed.metadata["source_vendor_counts"]["Garmin"] == 1


def test_apple_health_maps_exported_pressure_swimming_stairs_and_events(tmp_path):
    (tmp_path / "export.xml").write_text(
        """<?xml version="1.0"?>
<HealthData>
 <Record type="HKQuantityTypeIdentifierHeight" sourceName="Health" unit="cm" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:00:00 +0200" value="190"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Connect" unit="mmHg" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:00:00 +0200" value="121"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" sourceName="Connect" unit="mmHg" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:00:00 +0200" value="79"/>
 <Record type="HKQuantityTypeIdentifierDistanceSwimming" sourceName="Apple Watch" unit="m" startDate="2026-01-02 11:00:00 +0200" endDate="2026-01-02 11:20:00 +0200" value="600"/>
 <Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" sourceName="Apple Watch" unit="count" startDate="2026-01-02 11:00:00 +0200" endDate="2026-01-02 11:20:00 +0200" value="300"/>
 <Record type="HKQuantityTypeIdentifierStairAscentSpeed" sourceName="Apple Watch" unit="m/s" startDate="2026-01-02 12:00:00 +0200" endDate="2026-01-02 12:01:00 +0200" value="0.5"/>
 <Record type="HKQuantityTypeIdentifierEnvironmentalSoundReduction" sourceName="AirPods" unit="dBASPL" startDate="2026-01-02 13:00:00 +0200" endDate="2026-01-02 13:01:00 +0200" value="12"/>
 <Record type="HKCategoryTypeIdentifierAppleStandHour" sourceName="Apple Watch" startDate="2026-01-02 14:00:00 +0200" endDate="2026-01-02 15:00:00 +0200" value="HKCategoryValueAppleStandHourStood"/>
 <Record type="HKCategoryTypeIdentifierMindfulSession" sourceName="Health" startDate="2026-01-02 16:00:00 +0200" endDate="2026-01-02 16:10:00 +0200" value="HKCategoryValueNotApplicable"/>
 <Record type="HKCategoryTypeIdentifierAudioExposureEvent" sourceName="Health" startDate="2026-01-02 17:00:00 +0200" endDate="2026-01-02 17:01:00 +0200" value="HKCategoryValueEnvironmentalAudioExposureEventMomentaryLimit"/>
 <Record type="HKDataTypeSleepDurationGoal" sourceName="Clock" startDate="2026-01-02 18:00:00 +0200" endDate="2026-01-02 18:00:00 +0200" value="8"/>
</HealthData>""",
        encoding="utf-8",
    )
    parsed = AppleHealthAdapter().parse(tmp_path)
    values = {item.definition.key: item.value for item in parsed.aggregates}
    assert values == {
        "body_height": 190,
        "systolic_blood_pressure": 121,
        "diastolic_blood_pressure": 79,
        "swimming_distance": 600,
        "swimming_strokes": 300,
        "stair_ascent_speed": 0.5,
        "environmental_sound_reduction": 12,
        "stand_hours": 1,
    }
    assert parsed.events[0].event_type == "Mindful session"
    assert parsed.events[1].event_type == "Audio exposure event"
    assert parsed.metadata["retained_setting_type_counts"] == {"HKDataTypeSleepDurationGoal": 1}
    assert parsed.metadata["unknown_type_counts"] == {}


def test_oura_json_adapter_accepts_common_export_fields(tmp_path):
    # The bare "score" field must map to nothing: each export section carries
    # one, so mapping it would publish sleep scores as a recovery metric.
    (tmp_path / "sleep.json").write_text(
        json.dumps({"data": [{"day": "2026-01-02", "score": 80, "sleep_score": 87,
                              "total_sleep_duration": 27000, "average_hrv": 44}]}),
        encoding="utf-8",
    )
    parsed = OuraAdapter().parse(tmp_path)
    values = {item.definition.key: item.value for item in parsed.aggregates}
    assert values == {"sleep_score": 87, "sleep_duration": 7.5, "heart_rate_variability_rmssd": 44}


def test_oura_file_export_and_api_use_the_same_metric_contract():
    assert {definition[0] for definition in OuraAdapter.fields.values()} == set(OURA_API_DEFS)


def test_official_oura_takeout_maps_scores_sleep_vitals_activity_and_workouts(tmp_path):
    app = tmp_path / "App Data"
    write_semicolon_csv(
        app / "dailyactivity.csv",
        ["id", "day", "score", "steps", "active_calories", "total_calories",
         "medium_activity_time", "high_activity_time"],
        [{"id": "a", "day": "2026-08-01", "score": 82, "steps": 8123,
          "active_calories": 450, "total_calories": 2450,
          "medium_activity_time": 3600, "high_activity_time": 600}],
    )
    write_semicolon_csv(
        app / "dailyreadiness.csv", ["id", "day", "score", "temperature_deviation"],
        [{"id": "r", "day": "2026-08-01", "score": 79, "temperature_deviation": -0.2}],
    )
    write_semicolon_csv(
        app / "dailysleep.csv", ["id", "day", "score"],
        [{"id": "d", "day": "2026-08-01", "score": 88}],
    )
    write_semicolon_csv(
        app / "sleepmodel.csv",
        ["id", "day", "type", "bedtime_start", "bedtime_end", "total_sleep_duration",
         "deep_sleep_duration", "rem_sleep_duration", "light_sleep_duration", "awake_time",
         "time_in_bed", "lowest_heart_rate", "average_hrv", "average_breath", "efficiency"],
        [{"id": "s", "day": "2026-08-01", "type": "long_sleep",
          "bedtime_start": "2026-07-31T23:00:00+00:00", "bedtime_end": "2026-08-01T07:00:00+00:00",
          "total_sleep_duration": 25200, "deep_sleep_duration": 3600,
          "rem_sleep_duration": 5400, "light_sleep_duration": 16200, "awake_time": 1800,
          "time_in_bed": 27000, "lowest_heart_rate": 51, "average_hrv": 46,
          "average_breath": 13.5, "efficiency": 93}],
    )
    write_semicolon_csv(
        app / "dailyspo2.csv", ["id", "day", "breathing_disturbance_index", "spo2_percentage"],
        [{"id": "o", "day": "2026-08-01", "breathing_disturbance_index": 2,
          "spo2_percentage": json.dumps({"average": 96.5})}],
    )
    write_semicolon_csv(
        app / "workout.csv",
        ["id", "activity", "calories", "day", "distance", "end_datetime", "start_datetime"],
        [{"id": "w", "activity": "walking", "calories": 120, "day": "2026-08-01",
          "distance": 2500, "start_datetime": "2026-08-01T10:00:00+00:00",
          "end_datetime": "2026-08-01T10:30:00+00:00"}],
    )

    parsed = OuraAdapter().parse(tmp_path)
    values = {item.definition.key: item.value for item in parsed.aggregates}

    assert values["sleep_score"] == 88
    assert values["readiness_score"] == 79
    assert values["activity_score"] == 82
    assert values["sleep_duration"] == 7
    assert values["sleep_core"] == 4.5
    # Oura's `day` is the wake date. Preserve bedtime as the observation
    # timestamp without moving duration/stage rows to the preceding date.
    sleep = [item for item in parsed.aggregates if item.definition.key in {
        "sleep_duration", "sleep_deep", "sleep_rem", "sleep_core", "sleep_awake", "time_in_bed"}]
    assert {item.day for item in sleep} == {"2026-08-01"}
    assert {item.latest_at for item in sleep} == {"2026-07-31T23:00:00+00:00"}
    from anamna import oura
    api_bucket = {}
    oura._map_sleep([{"day": "2026-08-01", "type": "long_sleep", "bedtime_start": "2026-07-31T23:00:00+00:00",
                     "total_sleep_duration": 25200, "deep_sleep_duration": 3600, "average_hrv": 46}], api_bucket)
    assert {item.day for item in api_bucket.values()} == {"2026-08-01"}
    assert values["heart_rate_variability_rmssd"] == 46
    assert values["blood_oxygen"] == 96.5
    assert values["active_energy"] == 450
    assert values["resting_energy"] == 2000
    assert values["moderate_activity"] == 60
    assert values["vigorous_activity"] == 10
    assert parsed.workouts[0].duration_minutes == 30
    assert parsed.workouts[0].distance_km == 2.5
    assert parsed.metadata["export_format"] == "oura_takeout_csv"
    assert parsed.metadata["unsupported_populated_files"] == []


def test_official_oura_takeout_reports_new_populated_tables_and_columns(tmp_path):
    app = tmp_path / "App Data"
    write_semicolon_csv(
        app / "dailysleep.csv", ["id", "day", "score", "future_signal"],
        [{"id": "d", "day": "2026-08-01", "score": 80, "future_signal": 7}],
    )
    write_semicolon_csv(
        app / "brandnewhealthtable.csv", ["day", "value"],
        [{"day": "2026-08-01", "value": 1}],
    )

    parsed = OuraAdapter().parse(tmp_path)

    assert parsed.metadata["unsupported_populated_files"] == ["brandnewhealthtable.csv"]
    assert parsed.metadata["unexpected_normalized_columns"] == {
        "dailysleep.csv": ["future_signal"]
    }


def test_garmin_json_adapter_accepts_common_export_fields(tmp_path):
    (tmp_path / "daily.json").write_text(
        json.dumps([{"calendarDate": "2026-01-02", "totalSteps": 8123, "restingHeartRate": 58, "sleepTimeSeconds": 25200}]),
        encoding="utf-8",
    )
    parsed = GarminAdapter().parse(tmp_path)
    values = {item.definition.key: item.value for item in parsed.aggregates}
    assert values == {"steps": 8123, "resting_heart_rate": 58, "sleep_duration": 7}


def test_garmin_account_export_parses_nested_pressure_and_scale_data(tmp_path):
    wellness = tmp_path / "DI_CONNECT" / "DI-Connect-Wellness"
    wellness.mkdir(parents=True)
    (wellness / "BloodPressureFile_2026-01-01_2026-08-03.json").write_text(
        json.dumps([{
            "metaData": {"calendarDate": [2026, 4, 27, 14, 8, 57]},
            "bloodPressure": {"systolic": 120, "diastolic": 80, "pulse": 76},
        }]),
        encoding="utf-8",
    )
    (wellness / "100200300_userBioMetrics.json").write_text(
        json.dumps([
            {
                "metaData": {"calendarDate": "2026-05-03T11:24:54"},
                "weight": {"weight": 110800, "sourceType": "USER_SETTING"},
            },
            {
                "metaData": {"calendarDate": "2026-05-28T20:24:31"},
                "weight": {"weight": 9350, "bmi": 2.7, "bodyFat": 5, "sourceType": "INDEX_SCALE"},
            },
        ]),
        encoding="utf-8",
    )

    parsed = GarminAdapter().parse(tmp_path)
    values = {item.definition.key: item.value for item in parsed.aggregates}
    assert values["systolic_blood_pressure"] == 120
    assert values["diastolic_blood_pressure"] == 80
    assert values["blood_pressure_pulse"] == 76
    assert values["body_weight"] == 110.8
    assert "body_fat_percentage" not in values
    assert parsed.raw_record_count == 3
    assert parsed.metadata["excluded_implausible_values"][0]["metric"] == "body_weight"


def test_kardia_pdf_adapter_keeps_ecg_classification_and_source(monkeypatch, tmp_path):
    source = tmp_path / "recording.pdf"
    source.write_bytes(b"placeholder")
    text = """EKG Recording Overview
6L Recording
Date Of Birth
03/14/1990
Sex
Male
Recorded on:
Monday, Aug 03, 2026, 1:44 PM
Heart Rate:
77 BPM
Duration:
30s
Kardia Advanced Determination:
Normal Sinus Rhythm
"""

    class FakePage:
        def extract_text(self):
            return text

    class FakeReader:
        pages = [FakePage()] * 7

    monkeypatch.setattr("anamna.devices.kardia.PdfReader", lambda _: FakeReader())
    parsed = KardiaAdapter().parse(source)

    assert parsed.raw_record_count == 1
    assert parsed.aggregates[0].value == 77
    assert parsed.events[0].value_text == "Normal Sinus Rhythm"
    assert parsed.events[0].ended_at == "2026-08-03T13:44:30"
    assert parsed.metadata["pdf_pages"] == 7
    assert parsed.metadata["identity"] == {"date_of_birth": "1990-03-14", "biological_sex": "male"}
