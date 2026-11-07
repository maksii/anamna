"""OpenWearables sync engine — the merge, the windowed recompute, the link.

The contract this guards is *coexistence*.  An aggregation server re-serves
data the record may already hold from the device that produced it, so every
test here is really asking one of two questions: does a fresh day arrive, and
does an existing day survive.  A row this integration writes must never
displace a direct import, never delete one, and never be listed twice beside
one; a remote account swapped for a different person's must take its rows with
it and nothing else.

All HTTP goes through ``openwearables._request`` — one seam, stubbed with a
URL router, exactly like the Oura and Paperless tests stub theirs.  Payload
shapes are copied from the live API (probed 2026-08-07), including the ones
that look wrong and are not: an old phone-only night reporting every sleep
stage as zero, an activity day with null floors, a recovery summary with no
rows at all.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

from anamna import openwearables
from anamna.db import connect, utc_now
from anamna.devices.catalog import canonical_source_vendor, source_priority
from anamna.devices.queries import device_metric_comparison, device_metric_values, device_overview

from test_web_panels import build

BASE = "https://ow.example.test"
REMOTE = "5c9837a8-07e4-4c31-bcb8-251d8ed01674"
OTHER_REMOTE = "0a92af96-e78d-4886-b74e-503919c4604d"
EMAIL = "owner@example.com"

USERS = "/users"
ACTIVITY = f"/users/{REMOTE}/summaries/activity"
SLEEP = f"/users/{REMOTE}/summaries/sleep"
RECOVERY = f"/users/{REMOTE}/summaries/recovery"
SCORES = f"/users/{REMOTE}/health-scores"
SERIES = f"/users/{REMOTE}/timeseries"
WORKOUTS = f"/users/{REMOTE}/events/workouts"
CYCLES = f"/users/{REMOTE}/events/menstrual-cycles"


# --- harness -----------------------------------------------------------------


def configure(settings, *, url: str = BASE, api_key: str = "ow-api-key", enabled: str = "1") -> None:
    openwearables.save_settings(settings, {
        "openwearables_enabled": enabled,
        "openwearables_url": url,
        "openwearables_api_key": api_key,
    })
    openwearables.reset_module_state()


def fake_api(monkeypatch, routes: dict[str, object], calls: list | None = None):
    """Route by path prefix under /api/v1 (longest match wins).  A reply may be
    a dict, an Exception, or a callable(url, kwargs)."""

    def request(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        path = url.split("/api/v1", 1)[-1].split("?")[0]
        for prefix in sorted(routes, key=len, reverse=True):
            if path.startswith(prefix):
                reply = routes[prefix]
                if isinstance(reply, Exception):
                    raise reply
                return reply(url, kwargs) if callable(reply) else reply
        raise AssertionError(f"unexpected openwearables path {path}")

    monkeypatch.setattr(openwearables, "_request", request)
    return request


def page(rows: list[dict], *, cursor: str | None = None) -> dict:
    return {
        "data": rows,
        "pagination": {"next_cursor": cursor, "previous_cursor": None,
                       "has_more": bool(cursor), "total_count": len(rows)},
        "metadata": {"resolution": None, "sample_count": len(rows)},
    }


EMPTY = page([])


_PATHS = {
    "activity": ACTIVITY, "sleep": SLEEP, "recovery": RECOVERY, "scores": SCORES,
    "series": SERIES, "workouts": WORKOUTS, "cycles": CYCLES,
}


def routes(**overrides) -> dict[str, object]:
    """Every endpoint answering nothing, so a test states only what it cares
    about and a stray call still fails loudly rather than silently."""
    base: dict[str, object] = {path: EMPTY for path in _PATHS.values()}
    return {**base, **{_PATHS[name]: reply for name, reply in overrides.items()}}


def link(settings, user_id: str, remote: str = REMOTE) -> bool:
    return openwearables.link_account(settings, user_id, remote, EMAIL)


def metric_rows(settings, key: str) -> list:
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM device_metric_days WHERE metric_key=? ORDER BY day, source_name", (key,)
        ).fetchall()


def seed_import(settings, user_id: str, import_id: str, adapter_key: str) -> str:
    """A file-import envelope beside the API one, so 'this row came from an
    export' is expressible in these tests."""
    with connect(settings) as db:
        patient_id = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        vendor_id = db.execute("SELECT id FROM vendors LIMIT 1").fetchone()[0]
        db.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 10, 1, 'complete', '{}', ?)""",
            (import_id, user_id, patient_id, vendor_id, adapter_key,
             f"/exports/{import_id}", import_id, utc_now()),
        )
    return import_id


def seed_day(settings, user_id: str, import_id: str, source_name: str, metric_key: str,
             day: str, value: float, *, name: str = "Daily steps", category: str = "device_activity",
             unit: str = "steps", aggregation: str = "sum") -> None:
    with connect(settings) as db:
        patient_id = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        db.execute(
            """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id,
                   source_name, source_vendor, metric_key, metric_name, category, day,
                   aggregation, unit, value, sample_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (f"{import_id}-{metric_key}-{day}", user_id, patient_id, import_id, source_name,
             canonical_source_vendor(source_name), metric_key, name, category, day,
             aggregation, unit, value, utc_now()),
        )


def seed_workout(settings, user_id: str, import_id: str, source_name: str,
                 workout_type: str, started_at: str) -> None:
    with connect(settings) as db:
        patient_id = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        db.execute(
            """INSERT INTO device_workouts(id, owner_user_id, patient_id, import_id,
                   source_name, source_vendor, workout_type, started_at, ended_at,
                   duration_minutes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 13, ?)""",
            (f"{import_id}-{started_at}", user_id, patient_id, import_id, source_name,
             canonical_source_vendor(source_name), workout_type, started_at, utc_now()),
        )


# --- payload fixtures, shaped on the live API --------------------------------


def activity_row(date: str, *, steps=12235, distance=9514.692, floors=4,
                 active_kcal=803.046, active_minutes=61, moderate=7, vigorous=0,
                 avg=81, low=56, high=130) -> dict:
    return {
        "date": date,
        "source": {"provider": "Ivan’s Apple Watch", "device": "Watch7,5"},
        "steps": steps, "distance_meters": distance, "floors_climbed": floors,
        "elevation_meters": None, "active_calories_kcal": active_kcal,
        "total_calories_kcal": 3467.76, "active_minutes": active_minutes,
        "sedentary_minutes": 35,
        "intensity_minutes": {"light": 35, "moderate": moderate, "vigorous": vigorous},
        "heart_rate": {"avg_bpm": avg, "max_bpm": high, "min_bpm": low},
    }


def sleep_row(date: str, *, asleep=281, in_bed=490, efficiency=57.39,
              awake=27, light=183, deep=3, rem=94, hrv=31.4, breath=12.26, spo2=95.8) -> dict:
    return {
        "date": date, "source": {"provider": "Oura", "device": "iPhone18,1"},
        "start_time": f"{date}T00:10:36Z", "end_time": f"{date}T05:19:27Z",
        "zone_offset": "+03:00", "duration_minutes": asleep,
        "total_duration_minutes": asleep, "time_in_bed_minutes": in_bed,
        "efficiency_percent": efficiency,
        "stages": {"awake_minutes": awake, "light_minutes": light,
                   "deep_minutes": deep, "rem_minutes": rem},
        "interruptions_count": None, "nap_count": 0, "nap_duration_minutes": 0,
        "sessions": [], "avg_heart_rate_bpm": 62, "avg_hrv_sdnn_ms": hrv,
        "avg_hrv_rmssd_ms": None, "avg_respiratory_rate": breath, "avg_spo2_percent": spo2,
    }


def user_page(*items: dict) -> dict:
    return {"items": list(items), "total": len(items), "page": 1, "limit": 100,
            "pages": 1, "has_next": False, "has_prev": False}


REMOTE_USER = {
    "id": REMOTE, "created_at": "2026-08-06T18:07:01Z", "first_name": "Maks",
    "last_name": None, "email": EMAIL, "external_user_id": "owner",
    "last_synced_at": "2026-08-07T13:45:57Z", "last_synced_provider": "apple",
    "has_active_connection": True,
}


# --- configuration, probe and the remote account list ------------------------


def test_the_feature_is_invisible_until_url_and_key_are_both_stored(tmp_path: Path, monkeypatch):
    settings, _user_id, _client = build(tmp_path)
    for name in ("ANAMNA_OPENWEARABLES_URL", "ANAMNA_OPENWEARABLES_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert openwearables.configured(settings) is False
    configure(settings, api_key="")
    assert openwearables.configured(settings) is False
    configure(settings)
    assert openwearables.configured(settings) is True
    configure(settings, enabled="")
    assert openwearables.configured(settings) is False


def test_probe_separates_reachable_unauthorized_and_down(tmp_path: Path, monkeypatch):
    """Three different answers because they send the operator to three
    different places: nothing to fix, the key, or the network."""
    settings, _user_id, _client = build(tmp_path)
    configure(settings)

    fake_api(monkeypatch, {USERS: user_page(REMOTE_USER)})
    assert openwearables.probe(settings) == {"ok": True, "status": "ok", "user_count": 1}

    fake_api(monkeypatch, {USERS: openwearables.OpenWearablesError(
        "HTTP 401: {\"detail\": \"Could not validate credentials\"}", status=401)})
    assert openwearables.probe(settings)["status"] == "unauthorized"

    fake_api(monkeypatch, {USERS: openwearables.OpenWearablesError(
        str(urllib.error.URLError("connection refused")))})
    assert openwearables.probe(settings) == {"ok": False, "status": "unreachable", "user_count": None}


def test_remote_users_reads_the_list_because_the_single_user_get_lies(tmp_path: Path, monkeypatch):
    settings, _user_id, _client = build(tmp_path)
    configure(settings)
    fake_api(monkeypatch, {USERS: user_page(REMOTE_USER)})
    (person,) = openwearables.remote_users(settings)
    assert person == {"id": REMOTE, "email": EMAIL, "name": "Maks",
                      "last_synced_at": "2026-08-07T13:45:57Z", "connected": True}


def test_changing_the_server_unlinks_every_account_but_keeps_the_data(tmp_path: Path, monkeypatch):
    """A remote uuid means nothing on a different server, so the links go.  The
    days already synced are the person's own measurements and stay."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(activity=page([activity_row("2026-08-01")])))
    openwearables.backfill(settings, user_id)
    assert metric_rows(settings, "steps")

    openwearables.save_settings(settings, {"openwearables_url": "https://elsewhere.example.test"})
    assert openwearables.linked(settings, user_id) is None
    assert [row["value"] for row in metric_rows(settings, "steps")] == [12235.0]

    # Saving the same address again is not a change and must not unlink.
    link(settings, user_id)
    openwearables.save_settings(settings, {"openwearables_url": "https://elsewhere.example.test/"})
    assert openwearables.linked(settings, user_id) is not None


# --- mapping -----------------------------------------------------------------


def test_activity_maps_every_field_it_claims_and_derives_nothing(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(activity=page([activity_row("2026-08-01")])))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-08-01", "2026-08-01")

    assert metric_rows(settings, "steps")[0]["value"] == 12235
    # Metres in, kilometres out — the unit every other importer stores.
    assert round(metric_rows(settings, "walking_running_distance")[0]["value"], 4) == 9.5147
    assert metric_rows(settings, "flights_climbed")[0]["value"] == 4
    assert metric_rows(settings, "active_energy")[0]["value"] == 803.046
    assert metric_rows(settings, "active_minutes")[0]["value"] == 61
    assert metric_rows(settings, "sedentary_minutes")[0]["value"] == 35
    assert metric_rows(settings, "light_activity")[0]["value"] == 35
    assert metric_rows(settings, "total_energy")[0]["value"] == 3467.76
    assert metric_rows(settings, "moderate_activity")[0]["value"] == 7
    heart = metric_rows(settings, "daily_heart_rate")[0]
    assert (heart["value"], heart["value_min"], heart["value_max"]) == (81, 56, 130)
    assert heart["unit"] == "bpm" and heart["source_name"] == "OpenWearables · Ivan’s Apple Watch · Watch7,5"
    # Total expenditure remains total expenditure; it is never relabelled as
    # basal energy by subtracting the active component.
    assert metric_rows(settings, "resting_energy") == []


def test_sleep_minutes_become_hours_and_a_stageless_night_keeps_its_duration(
    tmp_path: Path, monkeypatch
):
    """An old phone-only night reports all four stages as 0 and efficiency as
    100: writing four zero-hour stages would draw a night with no sleep in it,
    so the stages are skipped and the duration is kept."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(sleep=page([
        sleep_row("2026-08-01"),
        sleep_row("2023-03-16", asleep=415, in_bed=415, efficiency=100.0,
                  awake=0, light=0, deep=0, rem=0, hrv=None, breath=None, spo2=None),
    ])))
    openwearables.sync_datatype(settings, user_id, "sleep", "2023-03-16", "2026-08-01")

    asleep = {row["day"]: row["value"] for row in metric_rows(settings, "sleep_duration")}
    assert round(asleep["2026-08-01"], 4) == round(281 / 60, 4)
    assert round(asleep["2023-03-16"], 4) == round(415 / 60, 4)
    assert round(metric_rows(settings, "time_in_bed")[1]["value"], 4) == round(490 / 60, 4)
    assert metric_rows(settings, "sleep_efficiency")[1]["value"] == 57.39
    staged = {row["day"]: row["value"] for row in metric_rows(settings, "sleep_deep")}
    assert list(staged) == ["2026-08-01"] and round(staged["2026-08-01"], 4) == round(3 / 60, 4)
    assert [row["day"] for row in metric_rows(settings, "sleep_core")] == ["2026-08-01"]
    assert metric_rows(settings, "heart_rate_variability")[0]["value"] == 31.4
    assert metric_rows(settings, "blood_oxygen")[0]["value"] == 95.8
    assert metric_rows(settings, "sleeping_heart_rate")[0]["value"] == 62
    # The server answers 0 naps for every night it has: "cannot detect
    # naps", not a measurement, so nothing is stored for it (OPS-09).
    assert metric_rows(settings, "sleep_naps") == []
    assert metric_rows(settings, "sleep_nap_duration") == []


def test_scores_recovery_and_the_sparse_body_series(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(
        scores=page([
            {"category": "sleep", "value": 91.0, "qualifier": None,
             "recorded_at": "2026-08-07T07:33:56Z", "components": {}, "provider": "internal"},
            {"category": "stress", "value": 40.0, "recorded_at": "2026-08-07T07:33:56Z"},
            {"category": "body-battery", "value": 72.0, "recorded_at": "2026-08-07T07:33:56Z"},
        ]),
        recovery=page([{"date": "2026-08-07", "source": {"provider": "Oura"},
                        "sleep_duration_seconds": 25260, "sleep_efficiency_percent": 79.5,
                        "resting_heart_rate_bpm": 54, "avg_hrv_sdnn_ms": 66.1,
                        "avg_spo2_percent": 95.8, "recovery_score": 78.0}]),
        series=page([
            {"timestamp": "2016-01-01T05:09:00Z", "type": "weight", "value": 115.0, "unit": "kg",
             "source": {"provider": "Health"}, "is_daily_total": None},
            {"timestamp": "2016-01-01T21:00:00Z", "type": "weight", "value": 113.0, "unit": "kg",
             "source": {"provider": "Health"}, "is_daily_total": None},
            {"timestamp": "2016-01-02T06:00:00Z", "type": "height", "value": 190.0, "unit": "cm",
             "source": {"provider": "Health"}, "is_daily_total": None},
            # heart_rate is dense and already arrives as a daily summary; a
            # sample of it must never become a row here.
            {"timestamp": "2016-01-02T06:00:01Z", "type": "heart_rate", "value": 57.0,
             "unit": "bpm", "source": {"provider": "Oura"}, "is_daily_total": None},
        ]),
    ))
    for datatype in ("scores", "recovery", "body_series"):
        openwearables.sync_datatype(settings, user_id, datatype, "2016-01-01", "2026-08-07")

    assert metric_rows(settings, "sleep_score")[0]["value"] == 91.0
    assert metric_rows(settings, "stress_score")[0]["value"] == 40.0
    assert metric_rows(settings, "body_battery_score")[0]["value"] == 72.0
    assert metric_rows(settings, "sleep_score")[0]["day"] == "2026-08-07"
    assert metric_rows(settings, "recovery_score")[0]["value"] == 78.0
    assert metric_rows(settings, "recovery_score")[0]["unit"] == "score"
    assert metric_rows(settings, "resting_heart_rate")[0]["value"] == 54
    # Two weights on one day: "latest" keeps the last sample of the day.
    weight = metric_rows(settings, "body_weight")
    assert len(weight) == 1 and weight[0]["value"] == 113.0 and weight[0]["unit"] == "kg"
    assert metric_rows(settings, "body_height")[0]["value"] == 190.0
    assert metric_rows(settings, "daily_heart_rate") == []


def test_workouts_and_cycles_land_in_their_tables(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(
        workouts=page([{
            "id": "dfd96510", "type": "walking", "name": None,
            "start_time": "2026-04-09T10:07:00Z", "end_time": "2026-04-09T10:20:00Z",
            "zone_offset": None, "duration_seconds": 780,
            "source": {"provider": "Oura", "device": "iPhone18,1"},
            "calories_kcal": 57.134, "distance_meters": 543.606,
            "avg_heart_rate_bpm": 116, "max_heart_rate_bpm": None,
        }]),
        cycles=page([
            {"id": "c1", "start_time": "2026-06-01T00:00:00Z", "end_time": "2026-06-05T00:00:00Z",
             "current_phase_type": "menstrual", "cycle_length": 28, "period_length": 5,
             "is_predicted_cycle": False},
            # A forecast of a period that has not happened is not an observation.
            {"id": "c2", "start_time": "2026-07-01T00:00:00Z", "end_time": None,
             "current_phase_type": "predicted", "cycle_length": 28, "is_predicted_cycle": True},
        ]),
    ))
    openwearables.sync_workouts(settings, user_id, "2026-01-01", "2026-12-31")
    openwearables.sync_cycles(settings, user_id, "2026-01-01", "2026-12-31")
    with connect(settings) as db:
        (workout,) = db.execute("SELECT * FROM device_workouts").fetchall()
        events = db.execute("SELECT * FROM device_events").fetchall()
    assert workout["workout_type"] == "walking" and workout["duration_minutes"] == 13.0
    assert workout["energy_kcal"] == 57.134
    assert round(workout["distance_km"], 6) == 0.543606
    assert len(events) == 1
    assert events[0]["event_type"] == "Menstrual cycle" and events[0]["value_numeric"] == 28
    assert events[0]["value_text"] == "menstrual" and events[0]["unit"] == "days"


def test_pagination_follows_the_cursor_the_offset_and_the_page_number(
    tmp_path: Path, monkeypatch
):
    """Three endpoint families, three pagination styles; reading only the first
    page of any of them would silently truncate a decade."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)

    def activity(url, _kwargs):
        if "cursor=next" in url:
            return page([activity_row("2026-08-02", steps=7503)])
        return page([activity_row("2026-08-01")], cursor="next")

    def scores(url, _kwargs):
        offset = int(url.split("offset=")[1].split("&")[0])
        rows = [{"category": "sleep", "value": 90.0 - offset,
                 "recorded_at": f"2026-08-0{offset + 1}T07:00:00Z"}]
        return {"data": rows, "pagination": {"next_cursor": None, "has_more": offset < 1}}

    monkeypatch.setattr(openwearables, "_SCORE_LIMIT", 1)
    fake_api(monkeypatch, routes(activity=activity, scores=scores))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-08-01", "2026-08-02")
    openwearables.sync_datatype(settings, user_id, "scores", "2026-08-01", "2026-08-02")
    assert [row["day"] for row in metric_rows(settings, "steps")] == ["2026-08-01", "2026-08-02"]
    assert [row["value"] for row in metric_rows(settings, "sleep_score")] == [90.0, 89.0]


# --- the merge ---------------------------------------------------------------


def test_a_direct_import_wins_the_days_it_covers_and_the_server_fills_the_rest(
    tmp_path: Path, monkeypatch
):
    """The whole point of the integration in one assertion: history stays owned
    by the richer direct export, and the days after that export — the ones
    nobody has exported yet — are no longer blank."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    oura = seed_import(settings, user_id, "oura-export", "oura")
    seed_day(settings, user_id, apple, "Ivan's Apple Watch", "steps", "2026-08-01", 11000)
    seed_day(settings, user_id, oura, "Oura", "sleep_duration", "2026-08-01", 6.5,
             name="Time asleep", category="device_sleep", unit="hours")

    fake_api(monkeypatch, routes(
        activity=page([activity_row("2026-08-01"), activity_row("2026-08-02", steps=7503)]),
        sleep=page([sleep_row("2026-08-01"), sleep_row("2026-08-02", asleep=382)]),
    ))
    openwearables.backfill(settings, user_id)

    with connect(settings) as connection:
        steps = {str(row["day"]): row
                 for row in device_metric_values(connection, user_id, "steps")}
    assert steps["2026-08-01"]["source_name"] == "Ivan's Apple Watch"
    assert steps["2026-08-01"]["value"] == 11000
    assert steps["2026-08-02"]["source_name"] == "OpenWearables · Ivan’s Apple Watch · Watch7,5"
    assert steps["2026-08-02"]["value"] == 7503
    with connect(settings) as connection:
        asleep = {str(row["day"]): row for row in device_metric_values(
            connection, user_id, "sleep_duration")}
    assert asleep["2026-08-01"]["source_name"] == "Oura" and asleep["2026-08-01"]["value"] == 6.5
    assert asleep["2026-08-02"]["source_name"] == "OpenWearables · Oura · iPhone18,1"
    # Both rows are still there — the merge chooses, it never deletes.
    assert len(metric_rows(settings, "steps")) == 3


def test_a_record_with_nothing_else_in_it_shows_the_server_rows(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(activity=page([activity_row("2026-08-01")])))
    openwearables.backfill(settings, user_id)
    with connect(settings) as connection:
        values = device_metric_values(connection, user_id, "steps")
    assert len(values) == 1 and values[0]["source_name"] == "OpenWearables · Ivan’s Apple Watch · Watch7,5"
    assert values[0]["source_vendor"] == "OpenWearables"


def test_comparison_retains_every_source_and_marks_one_value_per_day(tmp_path: Path):
    settings, user_id, _client = build(tmp_path)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    oura = seed_import(settings, user_id, "oura-export", "oura")
    bridge = seed_import(settings, user_id, "bridge-export", "openwearables_api")
    seed_day(settings, user_id, apple, "Ivan's Apple Watch", "steps", "2026-08-01", 10000)
    seed_day(settings, user_id, oura, "Oura", "steps", "2026-08-01", 9000)
    seed_day(settings, user_id, bridge, "OpenWearables · Apple · Watch", "steps", "2026-08-01", 9900)
    seed_day(settings, user_id, bridge, "OpenWearables · Apple · Watch", "steps", "2026-08-02", 8000)

    with connect(settings) as connection:
        comparison = device_metric_comparison(connection, user_id, "steps")

    assert comparison is not None
    assert comparison["source_count"] == 3
    assert comparison["stored_row_count"] == 4
    assert comparison["overlap_days"] == 1
    assert [row["value"] for row in comparison["preferred"]] == [8000, 10000]
    shared = next(day for day in comparison["days"] if day["day"] == "2026-08-01")
    assert len(shared["rows"]) == 3
    assert sum(bool(row["selected"]) for row in shared["rows"]) == 1
    assert next(row for row in shared["rows"] if row["selected"])["source_name"] == "Ivan's Apple Watch"


def test_metric_page_shows_every_source_and_the_selection_policy(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    oura = seed_import(settings, user_id, "oura-export", "oura")
    bridge = seed_import(settings, user_id, "bridge-export", "openwearables_api")
    seed_day(settings, user_id, apple, "Ivan's Apple Watch", "steps", "2026-08-01", 10000)
    seed_day(settings, user_id, oura, "Oura", "steps", "2026-08-01", 9000)
    seed_day(settings, user_id, bridge, "OpenWearables · Apple · Watch", "steps", "2026-08-01", 9900)

    page = client.get("/devices/metrics/steps")
    assert page.status_code == 200
    assert "3 measurement sources" in page.text
    # The policy itself stays on the page (collapsed); the separate explainer was cut.
    assert "The timeline uses one selected source for each metric and day." in page.text
    assert "Direct device exports take precedence over bridge copies" not in page.text
    assert "Ivan&#39;s Apple Watch" in page.text
    assert "Oura" in page.text
    # One readable name per source: the origin, then the transport (UX-14).
    assert "Watch · OpenWearables" in page.text
    assert page.text.count('class="an-selected-source-row"') == 1
    # Each source can be charted on its own (its series loads on demand).
    assert page.text.count("data-chart-source=") == 4


def test_syncing_the_same_payloads_twice_changes_nothing(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(
        activity=page([activity_row("2026-08-01")]),
        sleep=page([sleep_row("2026-08-01")]),
        workouts=page([{"id": "w", "type": "walking", "start_time": "2026-04-09T10:07:00Z",
                        "end_time": "2026-04-09T10:20:00Z", "duration_seconds": 780}]),
    ))
    openwearables.backfill(settings, user_id)

    def snapshot() -> list[tuple]:
        with connect(settings) as db:
            return [
                tuple(row) for row in db.execute(
                    "SELECT metric_key, day, value, sample_count FROM device_metric_days"
                    " ORDER BY metric_key, day"
                )
            ] + [
                tuple(row) for row in db.execute(
                    "SELECT workout_type, started_at, duration_minutes FROM device_workouts"
                )
            ]

    first = snapshot()
    openwearables.backfill(settings, user_id)
    assert snapshot() == first and first


# --- the windowed recompute --------------------------------------------------


def test_a_resync_drops_days_the_server_no_longer_reports_and_nothing_else(
    tmp_path: Path, monkeypatch
):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    # Same metric, same day range, another importer: never this sync's to touch.
    seed_day(settings, user_id, apple, "Ivan's Apple Watch", "steps", "2026-08-05", 11000)

    fake_api(monkeypatch, routes(activity=page([
        activity_row("2026-07-01"), activity_row("2026-08-05"),
    ])))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-07-01", "2026-08-07")
    assert [row["day"] for row in metric_rows(settings, "steps")] == [
        "2026-07-01", "2026-08-05", "2026-08-05",
    ]

    # August 5th was withdrawn at the server; July 1st is outside the window.
    fake_api(monkeypatch, routes(activity=EMPTY))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-08-01", "2026-08-07")
    surviving = [(row["day"], row["source_name"]) for row in metric_rows(settings, "steps")]
    assert surviving == [
        ("2026-07-01", "OpenWearables · Ivan’s Apple Watch · Watch7,5"),
        ("2026-08-05", "Ivan's Apple Watch"),
    ]


def test_one_refused_dataset_costs_only_itself_and_is_named_for_the_page(
    tmp_path: Path, monkeypatch
):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    live = routes(
        activity=page([activity_row("2026-08-01")]),
        sleep=openwearables.OpenWearablesError("HTTP 502: bad gateway", status=502),
    )
    fake_api(monkeypatch, live)
    counts = openwearables.backfill(settings, user_id)

    assert counts["activity"] == 11 and "sleep" not in counts
    assert metric_rows(settings, "steps")[0]["value"] == 12235
    state = openwearables.sync_state(settings, user_id)
    assert state["failed_datatypes"] == {"sleep": "HTTP 502: bad gateway"}
    assert state["last_backfill_at"] and state["remote_user_id"] == REMOTE
    # Named by what the person lost, not by an API identifier.
    (label,) = openwearables.failed_datatype_labels(settings, user_id)
    assert "Time asleep" in label and "Deep sleep" in label

    # A later clean sync clears the recorded failure.
    live[SLEEP] = EMPTY
    openwearables.sync_recent(settings, user_id)
    assert openwearables.sync_state(settings, user_id)["failed_datatypes"] == {}


# --- linking, relinking, unlinking -------------------------------------------


def test_linking_a_different_remote_account_purges_its_predecessor_only(
    tmp_path: Path, monkeypatch
):
    """A remote account is a person.  Swapping it and keeping the rows would
    merge two people's measurements into one record."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    seed_day(settings, user_id, apple, "Ivan's Apple Watch", "steps", "2026-08-01", 11000)
    assert link(settings, user_id) is False  # nothing to replace
    fake_api(monkeypatch, routes(
        activity=page([activity_row("2026-08-01")]),
        workouts=page([{"id": "w", "type": "walking", "start_time": "2026-04-09T10:07:00Z",
                        "end_time": "2026-04-09T10:20:00Z", "duration_seconds": 780}]),
    ))
    openwearables.backfill(settings, user_id)
    assert len(metric_rows(settings, "steps")) == 2

    assert openwearables.link_account(settings, user_id, OTHER_REMOTE, "partner@example.com") is True
    rows = metric_rows(settings, "steps")
    assert [(row["day"], row["source_name"]) for row in rows] == [
        ("2026-08-01", "Ivan's Apple Watch")
    ]
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
    state = openwearables.sync_state(settings, user_id)
    assert state["remote_user_id"] == OTHER_REMOTE and state["last_sync_at"] == ""


def test_unlinking_keeps_the_data_and_relinking_the_same_account_resumes(
    tmp_path: Path, monkeypatch
):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(activity=page([activity_row("2026-08-01")])))
    openwearables.backfill(settings, user_id)

    openwearables.unlink_account(settings, user_id)
    assert openwearables.linked(settings, user_id) is None
    assert len(metric_rows(settings, "steps")) == 1  # the person's own record, kept

    assert link(settings, user_id) is False  # same account: nothing was purged
    assert len(metric_rows(settings, "steps")) == 1
    assert openwearables.linked(settings, user_id)["external_user_id"] == REMOTE


# --- what the pages show -----------------------------------------------------


def test_one_walk_recorded_twice_is_listed_once(tmp_path: Path, monkeypatch):
    """The Apple export writes local time with an offset, the server writes
    UTC.  Same instant, two strings, and until they are grouped by the minute
    they resolve to, the page lists the same walk twice."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    apple = seed_import(settings, user_id, "apple-export", "apple_health")
    seed_workout(settings, user_id, apple, "Ivan's Apple Watch", "Walking",
                 "2026-04-09T13:07:00+03:00")
    fake_api(monkeypatch, routes(workouts=page([
        {"id": "w1", "type": "walking", "start_time": "2026-04-09T10:07:00Z",
         "end_time": "2026-04-09T10:20:00Z", "duration_seconds": 780},
        {"id": "w2", "type": "swimming", "start_time": "2026-05-01T06:00:00Z",
         "end_time": "2026-05-01T06:30:00Z", "duration_seconds": 1800},
    ])))
    openwearables.sync_workouts(settings, user_id, "2026-01-01", "2026-12-31")

    with connect(settings) as connection:
        overview = device_overview(connection, user_id)
    listed = [(row["source_name"], row["workout_type"]) for row in overview["workouts"]]
    # The watch's own record wins the shared minute; the server-only session
    # is the one nothing else has.
    assert listed == [("OpenWearables", "Swimming"), ("Ivan's Apple Watch", "Walking")]
    shared = overview["workouts"][1]
    assert shared["source_count"] == 2
    assert shared["alternates"][0]["source_name"] == "OpenWearables"
    # The count is rows held, not sessions: it must keep matching the table.
    assert overview["counts"]["workouts"] == 3
    (vendor,) = [item for item in overview["vendors"] if item["key"] == "openwearables"]
    assert vendor["name"] == "OpenWearables"


def test_source_priority_places_the_aggregator_below_every_named_vendor(tmp_path: Path):
    """Asserted branch by branch: this ordering is the only thing standing
    between a re-served copy and the measurement it was copied from."""
    assert canonical_source_vendor("OpenWearables") == "OpenWearables"

    sleep = lambda vendor, name: source_priority("sleep_duration", vendor, name)  # noqa: E731
    assert sleep("Oura", "Oura") == 0
    assert sleep("Apple Health", "Ivan's Apple Watch") == 1
    assert sleep("OpenWearables", "OpenWearables") == 90
    assert sleep("Zepp Life", "Zepp Life") == 10

    body = lambda vendor, name: source_priority("body_weight", vendor, name)  # noqa: E731
    assert body("Garmin", "Connect") == 0
    assert body("Zepp Life", "Zepp Life") == 1
    assert body("OpenWearables", "OpenWearables") == 90
    assert body("Apple Health", "Health") == 10

    steps = lambda vendor, name: source_priority("steps", vendor, name)  # noqa: E731
    assert steps("Apple Health", "Ivan's Apple Watch") == 0
    assert steps("Oura", "Oura") == 1
    assert steps("Apple Health", "Ivan's iPhone") == 2
    assert steps("OpenWearables", "OpenWearables") == 90
    assert steps("Zepp Life", "Zepp Life") == 10


def test_every_metric_key_is_owned_by_exactly_one_datatype(tmp_path: Path):
    """Two datatypes owning one key would make each sync delete the other's
    days, and the loser would be whichever ran first."""
    owned = [key for keys in openwearables.DATATYPE_KEYS.values() for key in keys]
    assert len(owned) == len(set(owned))
    assert set(owned) <= set(openwearables.DEFS)


def test_the_envelope_is_one_row_that_counts_what_it_wrote(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(activity=page([activity_row("2026-08-01")])))
    openwearables.backfill(settings, user_id)
    with connect(settings) as db:
        rows = db.execute(
            "SELECT * FROM device_imports WHERE adapter_key='openwearables_api'"
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) FROM device_metric_days WHERE import_id=?", (rows[0]["id"],)
        ).fetchone()[0]
    assert len(rows) == 1
    assert rows[0]["source_path"] == "openwearables://api"
    assert rows[0]["source_fingerprint"] == "api"
    assert rows[0]["raw_record_count"] == total == 11


def test_a_cursor_chain_that_gives_up_early_is_not_believed(tmp_path: Path, monkeypatch):
    """The live server answered ``has_more: false`` on a *full* page with two
    more years of nights still behind it (measured 2026-08-07: owner's sleep
    stopped at 2024-07-21 of 2026-08-07).  A full final page reopens the window
    from the next day, so every stored night arrives anyway; a short page is
    still trusted as the genuine end."""
    import urllib.parse as _parse

    from datetime import date as _date, timedelta as _timedelta

    history = [( _date(2023, 1, 1) + _timedelta(days=n)).isoformat() for n in range(250)]

    def sleep_endpoint(url, kwargs):
        query = _parse.parse_qs(_parse.urlparse(url).query)
        start = query["start_date"][0]
        cursor = (query.get("cursor") or [None])[0]
        remaining = [day for day in history if day >= start]
        if cursor is None:
            # First page of a window: full, honestly promising more.
            return page([sleep_row(day) for day in remaining[:100]], cursor="c1")
        # Second page: full again, but the chain lies and declares the end.
        return page([sleep_row(day) for day in remaining[100:200]])

    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(sleep=sleep_endpoint))
    openwearables.sync_datatype(settings, user_id, "sleep", "2023-01-01", "2026-08-07")
    days = {str(row["day"]) for row in metric_rows(settings, "sleep_duration")}
    assert len(days) == 250
    assert max(days) == history[-1]
