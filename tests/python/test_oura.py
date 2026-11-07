"""Oura sync engine — the contract of the windowed recompute.

Under test: token refresh rotates the single-use pair and stores it before
use, and only a refused refresh (not a rate limit) marks the connection
`reauthorize`; pagination follows next_token; each dataset maps to the device
metric keys it owns with Oura's period/type semantics respected; a re-synced
window removes days the API no longer reports and leaves days outside the
window alone; webhook events become synced windows and are marked processed
exactly once; subscription upkeep creates what is missing, renews what is
expiring, and honestly reports "no public address" instead of pretending.

All HTTP goes through ``integrations._request`` — one seam, stubbed with a
URL router, exactly like the Paperless tests stub theirs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anamna import integrations, oura
from anamna.db import connect

from test_web_panels import build

EXTERNAL_ID = "oura-user-1"


def reset_module_state() -> None:
    oura._last_subscription_check = 0.0
    oura._refresh_locks.clear()


def configure(settings, public_url: str = "") -> None:
    integrations.save_integration_settings(settings, {
        "oura_client_id": "oura-client-id",
        "oura_client_secret": "oura-client-secret",
        "integrations_public_url": public_url,
        "oura_verification_token": "vt-secret",
    })
    reset_module_state()


def connect_account(settings, user_id: str, *, expires_in_seconds: int = 3600) -> None:
    integrations.save_connection(
        settings, user_id, "oura",
        access_token="access-live", refresh_token="refresh-live",
        expires_at=(datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).isoformat(),
        external_user_id=EXTERNAL_ID, scopes="daily",
    )


def fake_api(monkeypatch, routes: dict[str, object], calls: list | None = None):
    """Route by path prefix (longest match wins). A reply may be a dict/list,
    an Exception, or a callable(url, kwargs)."""

    def request(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        path = url.split("ouraring.com", 1)[-1].split("?")[0]
        for prefix in sorted(routes, key=len, reverse=True):
            if path.startswith(prefix):
                reply = routes[prefix]
                if isinstance(reply, Exception):
                    raise reply
                return reply(url, kwargs) if callable(reply) else reply
        raise AssertionError(f"unexpected oura path {path}")

    monkeypatch.setattr(integrations, "_request", request)
    return request


def metric_rows(settings, key: str) -> list:
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM device_metric_days WHERE metric_key=? ORDER BY day", (key,)
        ).fetchall()


def sleep_doc(day: str, kind: str = "long_sleep", *, total=27000, deep=5400, rem=6000,
              light=15600, awake=1800, in_bed=30000, lowest_hr=44, hrv=52,
              breath=13.5, efficiency=91) -> dict:
    return {
        "id": f"sleep-{day}-{kind}", "day": day, "type": kind,
        "total_sleep_duration": total, "deep_sleep_duration": deep,
        "rem_sleep_duration": rem, "light_sleep_duration": light,
        "awake_time": awake, "time_in_bed": in_bed,
        "lowest_heart_rate": lowest_hr, "average_hrv": hrv,
        "average_breath": breath, "efficiency": efficiency,
        "bedtime_start": f"{day}T23:10:00+03:00",
    }


# --- token refresh -----------------------------------------------------------


def test_refresh_rotates_the_single_use_pair_before_using_it(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id, expires_in_seconds=10)  # inside the slack window
    calls: list = []
    fake_api(monkeypatch, {
        "/oauth/token": {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 86400},
        "/v2/usercollection/personal_info": {"id": EXTERNAL_ID},
    }, calls)
    payload = oura.api_get(settings, user_id, "/v2/usercollection/personal_info")
    assert payload == {"id": EXTERNAL_ID}
    assert calls[0]["url"] == integrations.PROVIDERS["oura"].token_url
    assert calls[0]["data"]["grant_type"] == "refresh_token"
    assert calls[0]["data"]["refresh_token"] == "refresh-live"
    row = integrations.connection_row(settings, user_id, "oura")
    assert row["access_token"] == "access-2" and row["refresh_token"] == "refresh-2"
    assert calls[1]["headers"]["Authorization"] == "Bearer access-2"


def test_a_401_answer_refreshes_once_and_retries(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)  # fresh expiry: no proactive refresh
    seen: list = []

    def personal_info(url, kwargs):
        seen.append(kwargs["headers"]["Authorization"])
        if kwargs["headers"]["Authorization"] == "Bearer access-live":
            raise integrations.IntegrationError("HTTP 401: expired", status=401)
        return {"id": EXTERNAL_ID}

    fake_api(monkeypatch, {
        "/oauth/token": {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 86400},
        "/v2/usercollection/personal_info": personal_info,
    })
    assert oura.api_get(settings, user_id, "/v2/usercollection/personal_info") == {"id": EXTERNAL_ID}
    assert seen == ["Bearer access-live", "Bearer access-2"]


def test_a_refused_refresh_marks_reauthorize_but_a_rate_limit_does_not(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id, expires_in_seconds=10)
    # The body of a proxy error page may well contain the text "HTTP 401" —
    # classification must come from the status attribute, never the message.
    fake_api(monkeypatch, {"/oauth/token": integrations.IntegrationError(
        "HTTP 429: slow down, also this body mentions HTTP 401", status=429)})
    try:
        oura.api_get(settings, user_id, "/v2/usercollection/personal_info")
        raise AssertionError("expected IntegrationError")
    except oura.ReauthorizeError:
        raise AssertionError("a rate limit must not kill the connection")
    except integrations.IntegrationError:
        pass
    assert integrations.connection_row(settings, user_id, "oura")["status"] == "active"

    fake_api(monkeypatch, {"/oauth/token": integrations.IntegrationError("HTTP 401: invalid_grant", status=401)})
    try:
        oura.api_get(settings, user_id, "/v2/usercollection/personal_info")
        raise AssertionError("expected ReauthorizeError")
    except oura.ReauthorizeError:
        pass
    assert integrations.connection_row(settings, user_id, "oura")["status"] == "reauthorize"
    # Reconnecting resets it.
    connect_account(settings, user_id)
    assert integrations.connection_row(settings, user_id, "oura")["status"] == "active"


# --- fetching and mapping ----------------------------------------------------


def test_pagination_follows_next_token(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)

    def daily_sleep(url, kwargs):
        if "next_token=page2" in url:
            return {"data": [{"id": "b", "day": "2026-08-02", "score": 80}], "next_token": None}
        return {"data": [{"id": "a", "day": "2026-08-01", "score": 75}], "next_token": "page2"}

    fake_api(monkeypatch, {"/v2/usercollection/daily_sleep": daily_sleep})
    oura.sync_range(settings, user_id, "daily_sleep", "2026-08-01", "2026-08-07")
    rows = metric_rows(settings, "sleep_score")
    assert [(row["day"], row["value"]) for row in rows] == [("2026-08-01", 75.0), ("2026-08-02", 80.0)]
    assert rows[0]["source_name"] == "Oura" and rows[0]["unit"] == "score"


def test_sleep_periods_sum_naps_and_ignore_rest(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    day = "2026-08-03"
    documents = [
        sleep_doc(day),  # the night: 7.5 h
        sleep_doc(day, "late_nap", total=3600, deep=600, rem=300, light=2700, awake=300,
                  in_bed=4200, lowest_hr=51, hrv=40, breath=14.0, efficiency=80),
        sleep_doc(day, "rest", total=0, deep=0, rem=0, light=0, awake=0, in_bed=1800),
        sleep_doc(day, "deleted", total=90000),  # Oura's own tombstone
    ]
    fake_api(monkeypatch, {"/v2/usercollection/sleep": {"data": documents, "next_token": None}})
    oura.sync_range(settings, user_id, "sleep", day, day)

    by_key = {row["metric_key"]: row for row in (
        metric_rows(settings, key)[0] for key in (
            "sleep_duration", "sleep_deep", "sleep_rem", "sleep_core", "sleep_awake",
            "time_in_bed", "lowest_sleeping_heart_rate", "heart_rate_variability_rmssd",
            "respiratory_rate", "sleep_efficiency",
        )
    )}
    assert round(by_key["sleep_duration"]["value"], 3) == round((27000 + 3600) / 3600, 3)
    assert round(by_key["sleep_core"]["value"], 3) == round((15600 + 2700) / 3600, 3)
    # time_in_bed counts the rest period; the deleted doc counts nowhere.
    assert round(by_key["time_in_bed"]["value"], 3) == round((30000 + 4200 + 1800) / 3600, 3)
    assert by_key["lowest_sleeping_heart_rate"]["value"] == 44  # the lowest across sleep periods
    # HRV, breath and efficiency come from the main (longest) sleep, not the nap.
    assert by_key["heart_rate_variability_rmssd"]["value"] == 52
    assert by_key["respiratory_rate"]["value"] == 13.5
    assert by_key["sleep_efficiency"]["value"] == 91
    assert by_key["sleep_duration"]["aggregation"] == "sum"


def test_resync_removes_days_the_api_no_longer_reports(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    fake_api(monkeypatch, {"/v2/usercollection/daily_sleep": {"data": [
        {"id": "a", "day": "2026-07-01", "score": 70},
        {"id": "b", "day": "2026-08-01", "score": 75},
    ], "next_token": None}})
    oura.sync_range(settings, user_id, "daily_sleep", "2026-07-01", "2026-08-07")
    assert [row["day"] for row in metric_rows(settings, "sleep_score")] == ["2026-07-01", "2026-08-01"]

    # August 1st was deleted at Oura; July 1st is outside the window and must survive.
    fake_api(monkeypatch, {"/v2/usercollection/daily_sleep": {"data": [], "next_token": None}})
    oura.sync_range(settings, user_id, "daily_sleep", "2026-08-01", "2026-08-07")
    assert [row["day"] for row in metric_rows(settings, "sleep_score")] == ["2026-07-01"]


def test_daily_activity_derives_resting_energy_and_minutes(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    fake_api(monkeypatch, {"/v2/usercollection/daily_activity": {"data": [{
        "id": "a", "day": "2026-08-05", "steps": 9000, "score": 88,
        "active_calories": 500, "total_calories": 2600,
        "medium_activity_time": 1800, "high_activity_time": 600,
    }], "next_token": None}})
    oura.sync_range(settings, user_id, "daily_activity", "2026-08-05", "2026-08-05")
    assert metric_rows(settings, "steps")[0]["value"] == 9000
    assert metric_rows(settings, "active_energy")[0]["value"] == 500
    assert metric_rows(settings, "resting_energy")[0]["value"] == 2100
    assert metric_rows(settings, "moderate_activity")[0]["value"] == 30
    assert metric_rows(settings, "vigorous_activity")[0]["value"] == 10
    assert metric_rows(settings, "activity_score")[0]["value"] == 88


def test_heartrate_series_becomes_daily_average_with_range(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    fake_api(monkeypatch, {"/v2/usercollection/heartrate": {"data": [
        {"timestamp": "2026-08-05T06:00:00+00:00", "bpm": 50, "source": "sleep"},
        {"timestamp": "2026-08-05T12:00:00+00:00", "bpm": 80, "source": "awake"},
        {"timestamp": "2026-08-05T18:00:00+00:00", "bpm": 110, "source": "workout"},
        # A sample with no timestamp must be dropped, not written as day=''.
        {"timestamp": None, "bpm": 200, "source": "live"},
    ], "next_token": None}})
    oura.sync_heartrate(settings, user_id, "2026-08-05", "2026-08-05")
    (row,) = metric_rows(settings, "daily_heart_rate")
    assert row["day"] == "2026-08-05"
    assert row["value"] == 80.0 and row["value_min"] == 50 and row["value_max"] == 110
    assert row["sample_count"] == 3 and row["aggregation"] == "average"


def test_api_resync_never_deletes_file_imported_oura_days(tmp_path: Path, monkeypatch):
    """A direct Oura export can hold days the API no longer serves; the API's
    windowed recompute must only prune days its own envelope owns."""
    from anamna.db import utc_now

    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    with connect(settings) as db:
        patient_id = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        vendor_id = db.execute("SELECT id FROM vendors LIMIT 1").fetchone()[0]
        db.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES ('file-import', ?, ?, ?, 'oura', '/exports/oura', 'f1', 10, 1,
                       'complete', '{}', ?)""",
            (user_id, patient_id, vendor_id, utc_now()),
        )
        db.execute(
            """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id,
                   source_name, source_vendor, metric_key, metric_name, category, day,
                   aggregation, unit, value, sample_count, created_at)
               VALUES ('old-row', ?, ?, 'file-import', 'Oura', 'Oura', 'sleep_score',
                       'Sleep score', 'device_sleep', '2020-01-01', 'latest', 'score', 70, 1, ?)""",
            (user_id, patient_id, utc_now()),
        )
    fake_api(monkeypatch, {"/v2/usercollection/daily_sleep": {"data": [
        {"id": "a", "day": "2026-08-01", "score": 75},
    ], "next_token": None}})
    oura.sync_range(settings, user_id, "daily_sleep", "2015-10-01", "2026-08-07")
    days = [row["day"] for row in metric_rows(settings, "sleep_score")]
    assert days == ["2020-01-01", "2026-08-01"]  # the file-era day survived


def test_workouts_sessions_and_tags_land_in_their_tables(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    fake_api(monkeypatch, {
        "/v2/usercollection/workout": {"data": [{
            "id": "w1", "activity": "running", "day": "2026-08-05",
            "start_datetime": "2026-08-05T07:00:00+03:00",
            "end_datetime": "2026-08-05T07:40:00+03:00",
            "calories": 320.5, "distance": 6200.0, "intensity": "moderate",
        }], "next_token": None},
        "/v2/usercollection/session": {"data": [{
            "id": "s1", "type": "meditation", "day": "2026-08-05",
            "start_datetime": "2026-08-05T21:00:00+03:00",
            "end_datetime": "2026-08-05T21:15:00+03:00",
        }], "next_token": None},
        "/v2/usercollection/enhanced_tag": {"data": [{
            "id": "t1", "tag_type_code": "tag_generic_caffeine",
            "start_time": "2026-08-05T15:00:00+03:00", "start_day": "2026-08-05",
            "comment": "double espresso",
        }], "next_token": None},
    })
    oura.sync_workouts(settings, user_id, "2026-08-05", "2026-08-05")
    with connect(settings) as db:
        workouts = db.execute("SELECT * FROM device_workouts ORDER BY started_at").fetchall()
        events = db.execute("SELECT * FROM device_events WHERE event_type='Oura tag'").fetchall()
    assert [(w["workout_type"], w["duration_minutes"]) for w in workouts] == [
        ("running", 40.0), ("meditation", 15.0),
    ]
    assert workouts[0]["energy_kcal"] == 320.5 and workouts[0]["distance_km"] == 6.2
    assert events[0]["value_text"] == "tag_generic_caffeine: double espresso"
    # Idempotent: the same window twice is one row, not two.
    oura.sync_workouts(settings, user_id, "2026-08-05", "2026-08-05")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 2


# --- webhook event processing ------------------------------------------------


def record(settings, event: dict) -> None:
    integrations.record_event(settings, "oura", json.dumps(event).encode())


def pending(settings) -> list:
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM provider_events WHERE provider='oura' AND processed_at IS NULL"
        ).fetchall()


def test_events_become_synced_windows_and_are_marked_processed(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    calls: list = []
    fake_api(monkeypatch, {
        "/v2/usercollection/daily_sleep/doc-1": {"id": "doc-1", "day": "2026-08-02", "score": 75},
        "/v2/usercollection/daily_sleep": {"data": [{"id": "doc-1", "day": "2026-08-02", "score": 75}], "next_token": None},
        "/v2/usercollection/heartrate": {"data": [], "next_token": None},
    }, calls)
    record(settings, {"event_type": "create", "data_type": "daily_sleep",
                      "object_id": "doc-1", "user_id": EXTERNAL_ID})
    record(settings, {"event_type": "create", "data_type": "daily_resilience",
                      "object_id": "r-1", "user_id": EXTERNAL_ID})  # retained raw only
    record(settings, {"event_type": "create", "data_type": "daily_sleep",
                      "object_id": "x-1", "user_id": "somebody-else"})  # not our account
    handled = oura.process_pending(settings)
    assert handled == 3 and pending(settings) == []
    assert metric_rows(settings, "sleep_score")[0]["day"] == "2026-08-02"
    # The window opened at the changed document's day, not at the wide fallback.
    sync_calls = [c for c in calls if "daily_sleep?" in c["url"] or c["url"].endswith("daily_sleep")]
    assert any("start_date=2026-08-02" in c["url"] for c in sync_calls)
    # Running again with nothing pending does nothing.
    assert oura.process_pending(settings) == 0


def test_a_failed_window_leaves_its_events_for_the_next_run(tmp_path: Path, monkeypatch):
    """Oura never redelivers an event answered 200, so an event whose sync
    window failed must stay pending rather than being stamped processed."""
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    record(settings, {"event_type": "delete", "data_type": "daily_sleep",
                      "object_id": "gone", "user_id": EXTERNAL_ID})
    fake_api(monkeypatch, {
        "/v2/usercollection/daily_sleep": integrations.IntegrationError("HTTP 502: bad gateway", status=502),
        "/v2/usercollection/heartrate": {"data": [], "next_token": None},
    })
    assert oura.process_pending(settings) == 0
    assert len(pending(settings)) == 1  # kept for the next run
    fake_api(monkeypatch, {
        "/v2/usercollection/daily_sleep": {"data": [], "next_token": None},
        "/v2/usercollection/heartrate": {"data": [], "next_token": None},
    })
    assert oura.process_pending(settings) == 1
    assert pending(settings) == []


def test_a_delete_event_widens_the_window(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    calls: list = []
    fake_api(monkeypatch, {
        "/v2/usercollection/daily_sleep": {"data": [], "next_token": None},
        "/v2/usercollection/heartrate": {"data": [], "next_token": None},
    }, calls)
    record(settings, {"event_type": "delete", "data_type": "daily_sleep",
                      "object_id": "gone", "user_id": EXTERNAL_ID})
    oura.process_pending(settings)
    # Counted back from the person's own today (Europe/Kyiv by default), not UTC's.
    wide = (datetime.now(oura.user_timezone_for(settings, user_id)).date()
            - timedelta(days=oura.DELETE_WINDOW_DAYS)).isoformat()
    assert any(f"start_date={wide}" in c["url"] for c in calls)


# --- subscriptions -----------------------------------------------------------


def test_subscriptions_report_no_public_url_instead_of_pretending(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, public_url="")
    connect_account(settings, user_id)
    oura.ensure_envelope(settings, user_id)
    fake_api(monkeypatch, {})  # any network call would raise
    status = oura.ensure_subscriptions(settings, force=True)
    assert status["reason"] == "no_public_url" and status["active"] == 0
    assert oura.sync_state(settings, user_id)["subscriptions"]["reason"] == "no_public_url"


def test_subscriptions_create_renew_and_replace_stale_callbacks(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings, public_url="https://health.example.test")
    connect_account(settings, user_id)
    oura.ensure_envelope(settings, user_id)
    callback = "https://health.example.test/integrations/oura/webhook"
    soon = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    later = (datetime.now(UTC) + timedelta(days=60)).isoformat()
    existing = [
        {"id": "keep", "callback_url": callback, "event_type": "create",
         "data_type": "daily_sleep", "expiration_time": later},
        {"id": "expiring", "callback_url": callback, "event_type": "update",
         "data_type": "daily_sleep", "expiration_time": soon},
        {"id": "stale", "callback_url": "https://old.example/webhook", "event_type": "delete",
         "data_type": "daily_sleep", "expiration_time": later},
    ]
    calls: list = []

    def router(url, kwargs):
        method = kwargs.get("method", "GET")
        if method == "GET":
            return existing
        return {"id": "new"}

    fake_api(monkeypatch, {"/v2/webhook/subscription": router}, calls)
    status = oura.ensure_subscriptions(settings, force=True)
    created = [c for c in calls if c.get("method") == "POST"]
    renewed = [c for c in calls if c.get("method") == "PUT" and "/renew/" in c["url"]]
    deleted = [c for c in calls if c.get("method") == "DELETE"]
    expected_slots = len(oura.SUBSCRIBED_DATATYPES) * 3
    # Two usable subscriptions existed; the stale-callback one was replaced.
    assert len(deleted) == 1 and deleted[0]["url"].endswith("/stale")
    assert len(renewed) == 1 and renewed[0]["url"].endswith("/renew/expiring")
    assert len(created) == expected_slots - 2
    assert created[0]["headers"]["x-client-id"] == "oura-client-id"
    assert created[0]["json_data"]["callback_url"] == callback
    assert created[0]["json_data"]["verification_token"] == "vt-secret"
    assert status["active"] == expected_slots
    # The daily check is rate-limited per process.
    assert oura.ensure_subscriptions(settings) == {"skipped": "checked recently"}


# --- backfill and state ------------------------------------------------------


def test_backfill_pulls_everything_and_records_state(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    empty = {"data": [], "next_token": None}
    fake_api(monkeypatch, {
        "/v2/usercollection/personal_info": {"id": EXTERNAL_ID},
        "/v2/usercollection/ring_configuration": {"data": [
            {"id": "r", "hardware_type": "gen3", "size": 9, "firmware_version": "2.9.5"}
        ], "next_token": None},
        "/v2/usercollection/sleep": {"data": [sleep_doc("2026-08-03")], "next_token": None},
        "/v2/usercollection/daily_sleep": {"data": [{"id": "a", "day": "2026-08-03", "score": 75}], "next_token": None},
        "/v2/usercollection/daily_readiness": {"data": [{"id": "b", "day": "2026-08-03", "score": 82,
                                                          "temperature_deviation": -0.3}], "next_token": None},
        "/v2/usercollection/daily_activity": empty,
        "/v2/usercollection/daily_spo2": {"data": [{"id": "c", "day": "2026-08-03",
                                                     "spo2_percentage": {"average": 97.2},
                                                     "breathing_disturbance_index": 3}], "next_token": None},
        "/v2/usercollection/daily_stress": {"data": [{"id": "d", "day": "2026-08-03",
                                                       "stress_high": 3600, "recovery_high": 5400}], "next_token": None},
        "/v2/usercollection/daily_cardiovascular_age": {"data": [{"id": "e", "day": "2026-08-03",
                                                                   "vascular_age": 31,
                                                                   "pulse_wave_velocity": 6.8}], "next_token": None},
        "/v2/usercollection/vO2_max": {"data": [{"id": "f", "day": "2026-08-03",
                                                  "vo2_max": 44}], "next_token": None},
        "/v2/usercollection/workout": empty,
        "/v2/usercollection/session": empty,
        "/v2/usercollection/enhanced_tag": empty,
        "/v2/usercollection/heartrate": empty,
    })
    counts = oura.backfill(settings, user_id)
    assert counts["sleep"] == 10  # every sleep-owned key wrote its day
    assert metric_rows(settings, "blood_oxygen")[0]["value"] == 97.2
    assert metric_rows(settings, "stress_high_time")[0]["value"] == 60
    assert metric_rows(settings, "recovery_high_time")[0]["value"] == 90
    assert metric_rows(settings, "cardiovascular_age")[0]["value"] == 31
    assert metric_rows(settings, "pulse_wave_velocity")[0]["value"] == 6.8
    assert metric_rows(settings, "vo2_max")[0]["value"] == 44
    assert metric_rows(settings, "temperature_deviation")[0]["value"] == -0.3
    row = integrations.connection_row(settings, user_id, "oura")
    assert row["external_user_id"] == EXTERNAL_ID
    state = oura.sync_state(settings, user_id)
    assert state["last_backfill_at"] and state["ring"]["hardware_type"] == "gen3"
    # The envelope is one row, owned by the API, and counts what it wrote.
    with connect(settings) as db:
        envelope = db.execute("SELECT * FROM device_imports WHERE adapter_key='oura_api'").fetchone()
    assert envelope["source_path"] == "oura://api"
    with connect(settings) as db:
        total = db.execute(
            "SELECT COUNT(*) FROM device_metric_days WHERE import_id=?", (envelope["id"],)
        ).fetchone()[0]
    assert envelope["raw_record_count"] == total == 20


def test_a_failed_dataset_is_recorded_in_state_and_the_rest_still_import(tmp_path: Path, monkeypatch):
    """A dataset Oura refuses (a withheld heart_health scope) must not be only
    a server log line: the failure lands in the envelope metadata where the
    /devices page can read it, and every other dataset still syncs."""
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    empty = {"data": [], "next_token": None}
    routes: dict[str, object] = {
        "/v2/usercollection/personal_info": {"id": EXTERNAL_ID},
        "/v2/usercollection/ring_configuration": empty,
        "/v2/usercollection/sleep": empty,
        "/v2/usercollection/daily_sleep": {"data": [{"id": "a", "day": "2026-08-03", "score": 75}], "next_token": None},
        "/v2/usercollection/daily_readiness": empty,
        "/v2/usercollection/daily_activity": empty,
        "/v2/usercollection/daily_spo2": empty,
        "/v2/usercollection/daily_stress": empty,
        "/v2/usercollection/daily_cardiovascular_age": integrations.IntegrationError(
            "HTTP 403: insufficient scope", status=403),
        "/v2/usercollection/vO2_max": empty,
        "/v2/usercollection/workout": empty,
        "/v2/usercollection/session": empty,
        "/v2/usercollection/enhanced_tag": empty,
        "/v2/usercollection/heartrate": empty,
    }
    fake_api(monkeypatch, routes)
    counts = oura.backfill(settings, user_id)
    assert "daily_cardiovascular_age" not in counts
    assert counts["daily_sleep"] == 1  # the failure cost only its own dataset
    assert metric_rows(settings, "sleep_score")[0]["day"] == "2026-08-03"
    state = oura.sync_state(settings, user_id)
    assert state["failed_datatypes"] == {"daily_cardiovascular_age": "HTTP 403: insufficient scope"}
    # A later sync that succeeds clears the recorded failure.
    routes["/v2/usercollection/daily_cardiovascular_age"] = empty
    oura.sync_recent(settings, user_id)
    assert oura.sync_state(settings, user_id)["failed_datatypes"] == {}


def test_profile_shows_the_sync_card_for_a_connected_account(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    oura.ensure_envelope(settings, user_id)
    page = client.get("/profile?tab=connections").text
    assert "/integrations/oura/sync" in page  # the Sync now button
    assert "/integrations/oura/disconnect" in page
    # A dead refresh token surfaces as a reconnect prompt, not silence.
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET status='reauthorize' WHERE user_id=?", (user_id,))
    page = client.get("/profile?tab=connections").text
    assert "stopped accepting" in page
