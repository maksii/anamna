"""Garmin — both tiers, against recorded-shape fake payloads.

Business tier (garmin.py): pushes and pings land in a local mirror and every
touched (type, day) is rebuilt from it, so revisions replace rather than sum,
edits move activities, units convert through the shared converter, and the
lifecycle notices (deregistration, withdrawn permission) delete what Garmin
delivered — never what the person imported from a file. Backfill records
Garmin's answers per type and resumes after a rate limit.

Personal tier (garmin_personal.py): the person's own key is validated by
using it, exchanged for a JWT that is re-minted before it lapses, and a
refused key asks for a new one. The windowed recompute writes each dataset in
the catalog's units — weight arrives in grams despite Garmin's spec saying kg,
measured on a live account — under the same source names as the Garmin file
importer, so the two routes merge day for day.

All HTTP goes through ``integrations._request``, stubbed with a path router.
Payload shapes follow Garmin Health API 1.2.2 / Personal API OpenAPI 1.0.0.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anamna import garmin, garmin_personal, integrations, security
from anamna.db import connect, utc_now
from anamna.devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS
from anamna.reference import canonical_unit

from test_web_issue_reports import csrf_for
from test_web_panels import build

GARMIN_USER = "garmin-user-1"
KEY = "GCDC_" + "a" * 36 + "." + "b" * 36 + "." + "c" * 43 + ".123456789"


def configure(settings, *, personal: bool = False) -> None:
    integrations.save_integration_settings(settings, {
        "garmin_client_id": "garmin-client-id",
        "garmin_client_secret": "garmin-client-secret",
        "garmin_personal_enabled": "1" if personal else "0",
    })
    integrations._refresh_locks.clear()
    security._attempts.clear()


def connect_business(settings, user_id: str, *, expires_in: int = 3600, scopes: str = "HEALTH_EXPORT ACTIVITY_EXPORT MCT_EXPORT") -> None:
    integrations.save_connection(
        settings, user_id, "garmin",
        access_token="access-live", refresh_token="refresh-live",
        expires_at=(datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat(),
        external_user_id=GARMIN_USER, scopes=scopes,
    )


def router(monkeypatch, routes: dict[str, object], calls: list | None = None):
    """Longest path-prefix match on the URL after its host; a reply may be a
    value, an Exception, or callable(url, kwargs)."""
    def request(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        for prefix in sorted(routes, key=len, reverse=True):
            if path.startswith(prefix):
                reply = routes[prefix]
                if isinstance(reply, Exception):
                    raise reply
                return reply(url, kwargs) if callable(reply) else reply
        raise AssertionError(f"unexpected request {url}")
    monkeypatch.setattr(integrations, "_request", request)


def deliver(settings, payload: dict, received_at: str | None = None) -> None:
    with connect(settings) as db:
        db.execute("INSERT INTO provider_events(provider, payload, received_at) VALUES ('garmin', ?, ?)",
                   (json.dumps(payload), received_at or utc_now()))


def rows(settings, key: str) -> list:
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM device_metric_days WHERE metric_key=? ORDER BY day, source_name", (key,)
        ).fetchall()


def value(settings, key: str, day: str, source: str = "Garmin") -> float | None:
    found = [r["value"] for r in rows(settings, key) if r["day"] == day and r["source_name"] == source]
    return found[0] if found else None


def epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


def daily(day: str, summary_id: str, **fields) -> dict:
    return {
        "userId": GARMIN_USER, "summaryId": summary_id, "calendarDate": day,
        "startTimeInSeconds": epoch(f"{day}T00:00:00+03:00"), "startTimeOffsetInSeconds": 10800,
        "steps": 8000, "distanceInMeters": 6200.0, "floorsClimbed": 7,
        "activeKilocalories": 450, "bmrKilocalories": 1900,
        "moderateIntensityDurationInSeconds": 1200, "vigorousIntensityDurationInSeconds": 600,
        "restingHeartRateInBeatsPerMinute": 54, "averageHeartRateInBeatsPerMinute": 68,
        "minHeartRateInBeatsPerMinute": 48, "maxHeartRateInBeatsPerMinute": 151,
        "averageStressLevel": 31, **fields,
    }


# --- catalog consistency ---------------------------------------------------------


def test_every_garmin_key_uses_the_catalog_unit_spelling():
    """A key whose unit folds differently from the catalog would split its trend."""
    catalog = {d.key: d for d in {**HEALTHKIT_METRICS, **SLEEP_METRICS}.values()}
    for key, definition in garmin.DEFS.items():
        if key in catalog:
            assert canonical_unit(definition.unit) == canonical_unit(catalog[key].unit), key
            assert definition.aggregation == catalog[key].aggregation, key
    for keys in (*garmin.TYPE_KEYS.values(), *garmin_personal.DATASET_KEYS.values()):
        assert set(keys) <= set(garmin.DEFS)
    owned = [key for keys in garmin.TYPE_KEYS.values() for key in keys]
    assert len(owned) == len(set(owned)), "a key owned by two types would delete the other's days"


# --- business tier: pushes, revisions, units --------------------------------------


def test_dailies_map_with_converted_units_and_revisions_replace(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    deliver(settings, {"dailies": [daily("2026-11-01", "x-1", averageStressLevel=-1)]})
    assert garmin.process_pending(settings) == 1
    assert value(settings, "steps", "2026-11-01") == 8000
    assert value(settings, "walking_running_distance", "2026-11-01") == pytest.approx(6.2)
    assert value(settings, "moderate_activity", "2026-11-01") == 20
    assert value(settings, "resting_energy", "2026-11-01") == 1900
    heart = rows(settings, "daily_heart_rate")[0]
    assert (heart["value"], heart["value_min"], heart["value_max"]) == (68, 48, 151)
    assert value(settings, "stress_level", "2026-11-01") is None  # -1 = not enough data

    # Garmin revises the day later, under a new summaryId: replaced, not summed.
    deliver(settings, {"dailies": [daily("2026-11-01", "x-2", steps=11000)]})
    garmin.process_pending(settings)
    assert value(settings, "steps", "2026-11-01") == 11000
    assert value(settings, "stress_level", "2026-11-01") == 31

    # Redelivery of the same content changes nothing.
    deliver(settings, {"dailies": [daily("2026-11-01", "x-2", steps=11000)]})
    garmin.process_pending(settings)
    assert len(rows(settings, "steps")) == 1


def test_sleep_body_pressure_and_series_mapping(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    start = epoch("2026-11-02T23:00:00+02:00")
    deliver(settings, {
        "sleeps": [{
            "userId": GARMIN_USER, "summaryId": "s-1", "calendarDate": "2026-11-03",
            "startTimeInSeconds": start, "startTimeOffsetInSeconds": 7200, "durationInSeconds": 28800,
            "deepSleepDurationInSeconds": 5400, "lightSleepDurationInSeconds": 14400,
            "remSleepInSeconds": 6300, "awakeDurationInSeconds": 2700,
            "overallSleepScore": {"value": 83, "qualifierKey": "GOOD"},
        }],
        "bodyComps": [{
            "userId": GARMIN_USER, "summaryId": "b-1", "measurementTimeInSeconds": epoch("2026-11-03T07:10:00+02:00"),
            "measurementTimeOffsetInSeconds": 7200, "weightInGrams": 81250, "bodyFatInPercent": 21.5,
            "muscleMassInGrams": 36000, "boneMassInGrams": 0, "bodyMassIndex": 24.8,
        }],
        "bloodPressures": [{
            "userId": GARMIN_USER, "summaryId": "p-1", "measurementTimeInSeconds": epoch("2026-11-03T08:00:00+02:00"),
            "measurementTimeOffsetInSeconds": 7200, "systolic": 128, "diastolic": 82, "pulse": 64,
        }],
        "pulseox": [{
            "userId": GARMIN_USER, "summaryId": "o-1", "calendarDate": "2026-11-03",
            "startTimeInSeconds": start, "startTimeOffsetInSeconds": 7200,
            "timeOffsetSpo2Values": {"0": 96, "3600": 94, "7200": 0},
        }],
        "allDayRespiration": [{
            "userId": GARMIN_USER, "summaryId": "r-1", "startTimeInSeconds": start,
            "startTimeOffsetInSeconds": 7200, "timeOffsetEpochToBreaths": {"0": 14.0, "60": 16.0, "120": -1},
        }],
        "hrv": [{"userId": GARMIN_USER, "summaryId": "h-1", "calendarDate": "2026-11-03", "lastNightAvg": 47}],
        "stressDetails": [{
            "userId": GARMIN_USER, "summaryId": "d-1", "calendarDate": "2026-11-03",
            "timeOffsetBodyBatteryValues": {"0": 35, "3600": 88, "7200": -1, "9000": 22},
        }],
        "userMetrics": [{"userId": GARMIN_USER, "summaryId": "u-1", "calendarDate": "2026-11-03", "vo2Max": 44.0, "fitnessAge": 31}],
        "skinTemp": [{"userId": GARMIN_USER, "summaryId": "t-1", "calendarDate": "2026-11-03", "avgDeviationCelsius": -0.4}],
        "epochs": [{"userId": GARMIN_USER, "summaryId": "e-1"}],  # archive only
    })
    garmin.process_pending(settings)
    day = "2026-11-03"
    assert value(settings, "sleep_duration", day) == pytest.approx(7.25)  # staged sum, awake excluded
    assert value(settings, "time_in_bed", day) == pytest.approx(8.0)
    assert value(settings, "sleep_awake", day) == pytest.approx(0.75)
    assert value(settings, "sleep_score", day) == 83
    assert value(settings, "body_weight", day) == pytest.approx(81.25)
    assert value(settings, "muscle_mass", day) == pytest.approx(36.0)
    assert value(settings, "bone_mass", day) is None  # 0 = the scale cannot measure it
    assert value(settings, "systolic_blood_pressure", day, garmin.BP_SOURCE_NAME) == 128
    assert value(settings, "blood_oxygen", day) == pytest.approx(95.0)  # the 0 dropout is not a reading
    assert value(settings, "respiratory_rate", "2026-11-02") == pytest.approx(15.0)
    assert value(settings, "heart_rate_variability_rmssd", day) == 47
    assert (value(settings, "body_battery_high", day), value(settings, "body_battery_low", day)) == (88, 22)
    assert (value(settings, "vo2_max", day), value(settings, "fitness_age", day)) == (44.0, 31)
    assert value(settings, "temperature_deviation", day) == pytest.approx(-0.4)
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM garmin_summaries WHERE summary_type='epochs'").fetchone()[0] == 0


def test_activity_edits_replace_and_events_map(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    start = epoch("2026-11-04T07:00:00+02:00")
    run = {"userId": GARMIN_USER, "summaryId": "a-1", "activityId": 991, "activityType": "RUNNING",
           "startTimeInSeconds": start, "startTimeOffsetInSeconds": 7200, "durationInSeconds": 1800,
           "distanceInMeters": 5000.0, "activeKilocalories": 380}
    deliver(settings, {"activities": [run], "moveIQActivities": [{
        "userId": GARMIN_USER, "summaryId": "m-1", "startTimeInSeconds": start + 7200,
        "offsetInSeconds": 7200, "durationInSeconds": 900, "activityType": "Walking"}],
        "mct": [
            {"userId": GARMIN_USER, "summaryId": "c-1", "periodStartDate": "2026-10-20", "cycleLength": 29,
             "currentPhaseType": "LUTEAL"},
            {"userId": GARMIN_USER, "summaryId": "c-2", "periodStartDate": "2026-11-18", "isPredictedCycle": True},
        ]})
    garmin.process_pending(settings)
    # The person corrects the type in Garmin Connect: the edit replaces it.
    deliver(settings, {"manuallyUpdatedActivities": [{**run, "summaryId": "a-1-edit", "activityType": "TRAIL_RUNNING"}]})
    garmin.process_pending(settings)
    with connect(settings) as db:
        workouts = db.execute("SELECT workout_type, started_at, duration_minutes, distance_km FROM device_workouts").fetchall()
        events = db.execute("SELECT event_type, started_at, value_numeric FROM device_events ORDER BY started_at").fetchall()
    assert [tuple(w) for w in workouts] == [("trail_running", "2026-11-04T07:00:00+02:00", 30.0, 5.0)]
    assert [tuple(e) for e in events] == [
        ("Menstrual cycle", "2026-10-20", 29.0),
        ("Garmin Move IQ", "2026-11-04T09:00:00+02:00", 15.0),
    ]


# --- business tier: pings, strangers, lifecycle ------------------------------------


def test_ping_is_pulled_from_garmin_only_and_retried_on_failure(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    callback = "https://apis.garmin.com/wellness-api/rest/dailies?uploadStartTimeInSeconds=1&uploadEndTimeInSeconds=2&token=t"
    calls: list = []
    router(monkeypatch, {"/wellness-api/rest/dailies": IntegrationErrorReply(503)}, calls)
    deliver(settings, {"dailies": [
        {"userId": GARMIN_USER, "callbackURL": callback},
        {"userId": GARMIN_USER, "callbackURL": "https://evil.example/steal"},
        {"userId": "someone-else", "summaryId": "z", "calendarDate": "2026-11-01", "steps": 5},
    ]})
    assert garmin.process_pending(settings) == 0  # Garmin will not redeliver a 200: keep it pending
    assert all("evil" not in call["url"] for call in calls)
    assert calls[0]["headers"]["Authorization"] == "Bearer access-live"
    router(monkeypatch, {"/wellness-api/rest/dailies": [daily("2026-11-01", "x-1")]}, calls)
    assert garmin.process_pending(settings) == 1
    assert value(settings, "steps", "2026-11-01") == 8000
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM garmin_summaries").fetchone()[0] == 1  # the stranger was never stored


class IntegrationErrorReply(integrations.IntegrationError):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}", status=status)


def _file_import_row(settings, user_id: str) -> None:
    """A Garmin *file export* reading in its own envelope."""
    with connect(settings) as db:
        patient = db.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
        vendor = db.execute("SELECT id FROM vendors LIMIT 1").fetchone()[0]
        db.execute("""INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                       source_fingerprint, source_bytes, raw_record_count, status, metadata_json, imported_at)
                      VALUES ('file-env', ?, ?, ?, 'garmin', 'x.zip', 'fp', 1, 1, 'complete', '{}', ?)""",
                   (user_id, patient, vendor, utc_now()))
        db.execute("""INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit, value, value_min, value_max,
                       value_sum, sample_count, created_at)
                      VALUES ('file-row', ?, ?, 'file-env', 'Garmin Connect blood pressure', 'Garmin',
                       'systolic_blood_pressure', 'Systolic blood pressure', 'device_recovery', '2025-01-01',
                       'latest', 'mmHg', 121, 121, 121, 121, 1, ?)""", (user_id, patient, utc_now()))


def test_deregistration_deletes_what_garmin_delivered_but_not_file_imports(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    deliver(settings, {"dailies": [daily("2026-11-01", "x-1")]})
    garmin.process_pending(settings)
    _file_import_row(settings, user_id)
    # A deregistration Garmin queued before this connection existed is stale.
    deliver(settings, {"deregistrations": [{"userId": GARMIN_USER}]}, received_at="2000-01-01T00:00:00+00:00")
    garmin.process_pending(settings)
    assert integrations.connection_row(settings, user_id, "garmin") is not None
    deliver(settings, {"deregistrations": [{"userId": GARMIN_USER}]})
    garmin.process_pending(settings)
    assert integrations.connection_row(settings, user_id, "garmin") is None
    assert rows(settings, "steps") == []
    assert [r["id"] for r in rows(settings, "systolic_blood_pressure")] == ["file-row"]
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM garmin_summaries").fetchone()[0] == 0


def test_withdrawn_permission_deletes_only_that_scope(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    start = epoch("2026-11-04T07:00:00+02:00")
    deliver(settings, {"dailies": [daily("2026-11-01", "x-1")], "activities": [{
        "userId": GARMIN_USER, "summaryId": "a", "activityId": 1, "activityType": "CYCLING",
        "startTimeInSeconds": start, "startTimeOffsetInSeconds": 7200, "durationInSeconds": 600}]})
    garmin.process_pending(settings)
    deliver(settings, {"userPermissionsChange": [{"userId": GARMIN_USER, "summaryId": "pc",
                                                  "permissions": ["ACTIVITY_EXPORT"], "changeTimeInSeconds": 1}]})
    garmin.process_pending(settings)
    assert rows(settings, "steps") == []
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 1
    assert integrations.connection_row(settings, user_id, "garmin")["scopes"] == "ACTIVITY_EXPORT"


def test_backfill_records_each_answer_and_resumes_after_a_rate_limit(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    answers = {"dailies": None, "sleeps": IntegrationErrorReply(409), "hrv": IntegrationErrorReply(403),
               "stressDetails": IntegrationErrorReply(429)}

    def reply(url, kwargs):
        endpoint = url.split("/backfill/")[1].split("?")[0]
        answer = answers.get(endpoint)
        if isinstance(answer, Exception):
            raise answer
        return answer
    calls: list = []
    router(monkeypatch, {"/wellness-api/rest/backfill/": reply}, calls)
    state = garmin.request_backfill(settings, user_id)
    assert {k: v["status"] for k, v in state.items()} == {
        "dailies": "done", "sleeps": "done", "hrv": "unavailable", "stressDetails": "paused"}
    assert "summaryStartTimeInSeconds" in calls[0]["url"]
    answers["stressDetails"] = None
    state = garmin.request_backfill(settings, user_id)
    assert state["stressDetails"]["status"] == "done" and state["hrv"]["status"] == "unavailable"
    assert set(state) == set(garmin.BACKFILL_ENDPOINTS)
    assert garmin.sync_state(settings, user_id)["last_backfill_at"]


def test_garmin_refresh_rotates_the_pair_through_the_shared_helper(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id, expires_in=10)
    calls: list = []
    router(monkeypatch, {
        "/di-oauth2-service/oauth/token": {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 86400},
        "/wellness-api/rest/user/permissions": {"permissions": ["HEALTH_EXPORT"]},
    }, calls)
    assert garmin.fetch_permissions(settings, user_id) == ["HEALTH_EXPORT"]
    assert calls[0]["data"]["grant_type"] == "refresh_token" and calls[0]["data"]["refresh_token"] == "refresh-live"
    row = integrations.connection_row(settings, user_id, "garmin")
    assert (row["access_token"], row["refresh_token"], row["scopes"]) == ("access-2", "refresh-2", "HEALTH_EXPORT")
    assert calls[1]["headers"]["Authorization"] == "Bearer access-2"


# --- personal tier --------------------------------------------------------------------


def jwt(exp_in: int = 86400) -> str:
    claims = {"exp": int(time.time()) + exp_in, "garmin_guid": "guid-1", "scope": ["CONNECT_READ"]}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def personal_api(monkeypatch, calls: list | None = None, **overrides):
    """A small Garmin account: one scale reading and one manual weight, a watch
    worn from 2026-10-30, one run, a fitness age."""
    routes: dict[str, object] = {
        garmin_personal.TOKEN_PATH: lambda url, kw: jwt(),
        "/weight-service/weight/range/": {"dailyWeightSummaries": [{
            "summaryDate": "2026-08-08",
            "allWeightMetrics": [
                {"calendarDate": "2026-08-08", "weight": 110000.0, "bmi": 32.1, "bodyFat": 31.0, "bodyWater": 51.0,
                 "boneMass": 6699, "muscleMass": 41240, "sourceType": "INDEX_SCALE",
                 "date": 1786210611000, "timestampGMT": 1786199811000},
                {"calendarDate": "2026-08-08", "weight": 110500.0, "sourceType": "MANUAL",
                 "date": 1786214211000, "timestampGMT": 1786203411000},
            ]}]},
        "/usersummary-service/v2/dailysummaries": lambda url, kw: {"data": [
            {"calendarDate": "2026-10-29", "includesWellnessData": False, "movement": {"steps": 0}},
            {"calendarDate": "2026-10-30", "includesWellnessData": True,
             "movement": {"steps": 9100, "floorsAscended": 4}, "calories": {"burnedActive": 510, "burnedResting": 1950},
             "heartRate": {"restingValue": 55}, "intensityMinutes": {"moderate": 25, "vigorous": 10},
             "stress": {"avgLevel": -1}, "bodyBattery": {"maxValue": 91, "minValue": 18}},
        ] if "2026" in url else []},
        "/sleep-service/sleep/dailySleepSummariesByDate": [
            {"calendarDate": "2026-10-31", "sleepTimeSeconds": 25200, "deepSleepSeconds": 5400,
             "lightSleepSeconds": 14400, "remSleepSeconds": 5400, "awakeSleepSeconds": 1800,
             "sleepScores": {"overall": {"value": 79}}, "averageRespirationValue": 14.5,
             "averageSpO2Value": 95.0, "avgHeartRate": 52.0, "sleepStartTimestampLocal": "2026-10-30T23:40:00"},
            {"calendarDate": "2026-11-01", "sleepTimeSeconds": None},
        ],
        "/hrv-service/hrv/daily/": {"hrvSummaries": [{"calendarDate": "2026-10-31", "lastNightAvg": 44}]},
        "/activitylist-service/activities/search/activities": [{
            "activityId": 7, "activityType": {"typeKey": "running"}, "startTimeLocal": "2026-11-02 07:05:00",
            "startTimeGMT": "2026-11-02 05:05:00", "duration": 2400.0, "distance": 7000.0, "calories": 520.0}],
        "/fitnessage-service/fitnessage/v2/": [{"fitnessAge": 33.5, "lastUpdated": "2026-11-01T10:00:00.0"}],
    }
    routes.update(overrides)
    router(monkeypatch, routes, calls)


def test_key_shape_and_refusal_store_nothing(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, personal=True)
    assert garmin_personal.looks_like_key(KEY)
    for bad in ("", "abc", "GCDC_ with space", "gcdc_" + "a" * 40, "GCDC_" + "é" * 30):
        assert not garmin_personal.looks_like_key(bad)
    router(monkeypatch, {garmin_personal.TOKEN_PATH: IntegrationErrorReply(401)})
    with pytest.raises(garmin_personal.InvalidKeyError):
        garmin_personal.link_key(settings, user_id, KEY)
    assert integrations.connection_row(settings, user_id, garmin_personal.PROVIDER_KEY) is None


def test_personal_backfill_maps_every_dataset_in_catalog_units(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, personal=True)
    calls: list = []
    personal_api(monkeypatch, calls)
    garmin_personal.link_key(settings, user_id, KEY)
    mint = calls[0]
    assert mint["headers"]["Authorization"] == f"ApiKey {KEY}" and mint["method"] == "POST" and mint["raw"]
    row = integrations.connection_row(settings, user_id, garmin_personal.PROVIDER_KEY)
    assert (row["refresh_token"], row["external_user_id"]) == (KEY, "guid-1")

    garmin_personal.backfill(settings, user_id)
    scale = garmin.SCALE_SOURCE_NAME
    assert value(settings, "body_weight", "2026-08-08", scale) == pytest.approx(110.0)  # grams, not kg
    assert value(settings, "bone_mass", "2026-08-08", scale) == pytest.approx(6.699)
    assert value(settings, "body_weight", "2026-08-08", garmin.MANUAL_WEIGHT_SOURCE_NAME) == pytest.approx(110.5)
    weight = [r for r in rows(settings, "body_weight") if r["source_name"] == scale][0]
    assert weight["unit"] == "kg"
    assert value(settings, "steps", "2026-10-30") == 9100
    assert value(settings, "steps", "2026-10-29") is None  # no wellness data: zeros are not measurements
    assert value(settings, "stress_level", "2026-10-30") is None
    assert value(settings, "body_battery_low", "2026-10-30") == 18
    assert value(settings, "sleep_duration", "2026-10-31") == pytest.approx(7.0)
    assert value(settings, "time_in_bed", "2026-10-31") == pytest.approx(7.5)
    assert value(settings, "sleep_score", "2026-10-31") == 79
    assert value(settings, "sleeping_heart_rate", "2026-10-31") == 52
    assert value(settings, "heart_rate_variability_rmssd", "2026-10-31") == 44
    assert value(settings, "fitness_age", "2026-11-01") == pytest.approx(33.5)
    with connect(settings) as db:
        workout = db.execute("SELECT workout_type, started_at, distance_km FROM device_workouts").fetchone()
    assert tuple(workout) == ("running", "2026-11-02T07:05:00+02:00", 7.0)
    # Sleep was only asked for from the first day a watch was worn, not 2008.
    sleep_calls = [c["url"] for c in calls if "dailySleepSummariesByDate" in c["url"]]
    assert sleep_calls and "startDate=2026-10-30" in sleep_calls[0]
    state = garmin_personal.sync_state(settings, user_id)
    assert state["first_wellness_day"] == "2026-10-30" and state["failed_datatypes"] == {}


def test_personal_window_removes_absent_days_but_not_file_imports(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, personal=True)
    personal_api(monkeypatch)
    garmin_personal.link_key(settings, user_id, KEY)
    garmin_personal.sync_dataset(settings, user_id, "weight", "2026-08-01", "2026-08-31")
    _file_import_row(settings, user_id)
    # The reading was deleted in Garmin Connect: the window no longer has it.
    personal_api(monkeypatch, **{"/weight-service/weight/range/": {"dailyWeightSummaries": []}})
    garmin_personal.sync_dataset(settings, user_id, "weight", "2026-08-01", "2026-08-31")
    assert rows(settings, "body_weight") == []
    assert len(rows(settings, "systolic_blood_pressure")) == 1


def test_api_and_file_import_merge_on_one_natural_key(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, personal=True)
    personal_api(monkeypatch)
    garmin_personal.link_key(settings, user_id, KEY)
    garmin.ensure_envelope(settings, user_id, garmin_personal.ADAPTER_KEY)  # the vendor row
    _file_import_row(settings, user_id)
    with connect(settings) as db:
        patient = db.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
        db.execute("""INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit, value, value_min, value_max,
                       value_sum, sample_count, created_at)
                      VALUES ('file-weight', ?, ?, 'file-env', 'Garmin Index Scale', 'Garmin', 'body_weight', 'Body weight',
                       'device_body', '2026-08-08', 'latest', 'kg', 110.0, 110.0, 110.0, 110.0, 1, ?)""",
                   (user_id, patient, utc_now()))
    garmin_personal.sync_dataset(settings, user_id, "weight", "2026-08-01", "2026-08-31")
    scale_rows = [r for r in rows(settings, "body_weight") if r["source_name"] == garmin.SCALE_SOURCE_NAME]
    assert len(scale_rows) == 1 and scale_rows[0]["value"] == pytest.approx(110.0)


def test_jwt_is_reminted_before_it_lapses_and_a_refused_key_asks_for_a_new_one(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, personal=True)
    calls: list = []
    personal_api(monkeypatch, calls)
    garmin_personal.link_key(settings, user_id, KEY)
    with connect(settings) as db:  # inside the one-hour slack
        db.execute("UPDATE provider_connections SET token_expires_at=? WHERE provider=?",
                   ((datetime.now(UTC) + timedelta(minutes=30)).isoformat(), garmin_personal.PROVIDER_KEY))
    garmin_personal.api_get(settings, user_id, "/hrv-service/hrv/daily/2026-10-01/2026-10-31")
    assert sum(garmin_personal.TOKEN_PATH in c["url"] for c in calls) == 2
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET token_expires_at=? WHERE provider=?",
                   (datetime.now(UTC).isoformat(), garmin_personal.PROVIDER_KEY))
    personal_api(monkeypatch, **{garmin_personal.TOKEN_PATH: IntegrationErrorReply(401)})
    with pytest.raises(integrations.ReauthorizeError):
        garmin_personal.api_get(settings, user_id, "/hrv-service/hrv/daily/2026-10-01/2026-10-31")
    assert integrations.connection_row(settings, user_id, garmin_personal.PROVIDER_KEY)["status"] == "reauthorize"
    assert garmin_personal.panel(settings, user_id)["needs_new_key"] is True


# --- the profile card and routes -------------------------------------------------------


def test_personal_card_is_operator_gated_and_bilingual(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANAMNA_GARMIN_PERSONAL", raising=False)
    settings, user_id, client = build(tmp_path)
    started: list = []
    monkeypatch.setattr(garmin_personal, "start_sync", lambda s, u: started.append(u))
    assert "/integrations/garmin/personal" not in client.get("/profile?tab=connections").text
    configure(settings, personal=True)
    page = client.get("/profile?tab=connections").text
    assert 'action="/integrations/garmin/personal"' in page and 'type="password"' in page
    client.cookies.set("anamna_lang", "uk")
    uk = client.get("/profile?tab=connections").text
    assert "особистий ключ" in uk and "Ключ Personal API" in uk
    assert "Paste it here" not in uk
    client.cookies.set("anamna_lang", "en")

    csrf = csrf_for(settings, user_id)
    bad = client.post("/integrations/garmin/personal", data={"api_key": "nope", "csrf_token": csrf}, follow_redirects=False)
    assert bad.headers["location"] == "/profile?error=integrations.error_garmin_key"
    router(monkeypatch, {garmin_personal.TOKEN_PATH: IntegrationErrorReply(403)})
    refused = client.post("/integrations/garmin/personal", data={"api_key": KEY, "csrf_token": csrf}, follow_redirects=False)
    assert refused.headers["location"] == "/profile?error=integrations.error_garmin_key_refused"
    personal_api(monkeypatch)
    saved = client.post("/integrations/garmin/personal", data={"api_key": KEY, "csrf_token": csrf}, follow_redirects=False)
    assert saved.headers["location"] == "/profile?saved=garmin_key_saved" and started == [user_id]
    page = client.get("/profile?saved=garmin_key_saved").text
    assert KEY not in page  # the key is never echoed back
    assert "/integrations/garmin/personal/remove" in page
    removed = client.post("/integrations/garmin/personal/remove", data={"csrf_token": csrf}, follow_redirects=False)
    assert removed.headers["location"] == "/profile?saved=garmin_key_removed"
    assert integrations.connection_row(settings, user_id, garmin_personal.PROVIDER_KEY) is None


def test_business_disconnect_deletes_garmin_delivered_data(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    connect_business(settings, user_id)
    deliver(settings, {"dailies": [daily("2026-11-01", "x-1")]})
    garmin.process_pending(settings)
    calls: list = []
    router(monkeypatch, {"/wellness-api/rest/user/registration": None}, calls)
    page = client.get("/profile?tab=connections").text
    assert "/integrations/garmin/sync" in page and "Last delivery from Garmin" in page
    response = client.post("/integrations/garmin/disconnect", data={"csrf_token": csrf_for(settings, user_id)},
                           follow_redirects=False)
    assert response.status_code == 303
    assert calls[0]["method"] == "DELETE"
    assert rows(settings, "steps") == []
    assert integrations.connection_row(settings, user_id, "garmin") is None
