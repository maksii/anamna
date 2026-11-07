"""Oura days are the person's days, and Oura nights land on the night's day.

Regressions for the 2026-11-06 sandbox audit:

* OPS-03 -- the heart-rate series was cut at UTC midnight; it is cut at the
  person's local midnight (users.timezone, Europe/Kyiv by default).
* OPS-04 -- the first Takeout adapter filed each sleep period under its bedtime
  date and published 14.6 h "nights" beside 0.1 h ones.  Periods belong to
  Oura's own `day`; a day holding more than 16 h is withheld, not charted; and
  re-importing the same export repairs what the old grouping wrote.
* OPS-05 -- a webhook for the newest night synced a window that started on the
  wake day, which Oura's /sleep (filtered by bedtime date) never answers with
  that night.  Sleep stopped updating while every event read "processed".
* OPS-36 -- pending webhook events are drained on a timer, and the daily
  catch-up runs once a day per account, surviving a locked database.

All data here is synthetic.
"""

from __future__ import annotations

import csv
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from anamna import oura
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.devices.importer import import_device_export
from anamna.devices.oura_export import OuraAdapter
from anamna.security import create_user

from test_oura import EXTERNAL_ID, configure, connect_account, fake_api, metric_rows, pending, record
from test_web_panels import build

EMPTY = {"data": [], "next_token": None}


def hours(rows) -> dict[str, float]:
    return {row["day"]: round(row["value"], 3) for row in rows}


# --- OPS-05: the sleep window reaches the night that began the evening before --


def test_a_sleep_webhook_window_reaches_the_night_that_began_the_evening_before(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    # 1 November is already stored, complete: its night began on 31 October.
    first_night = {"id": "a", "day": "2026-11-01", "type": "long_sleep",
                   "bedtime_start": "2026-10-31T23:00:00+02:00", "total_sleep_duration": 27000,
                   "time_in_bed": 28800}
    fake_api(monkeypatch, {"/v2/usercollection/sleep": {"data": [first_night], "next_token": None}})
    oura.sync_range(settings, user_id, "sleep", "2026-11-01", "2026-11-01")
    assert hours(metric_rows(settings, "sleep_duration")) == {"2026-11-01": 7.5}

    # The new night wakes on 2 November but began at 23:30 on 1 November.
    night = {"id": "n", "day": "2026-11-02", "type": "long_sleep",
             "bedtime_start": "2026-11-01T23:30:00+02:00", "bedtime_end": "2026-11-02T07:00:00+02:00",
             "total_sleep_duration": 25200, "time_in_bed": 27000}
    # An afternoon nap on 1 November: all of that day the extra fetched day holds.
    nap = {"id": "p", "day": "2026-11-01", "type": "late_nap",
           "bedtime_start": "2026-11-01T15:00:00+02:00", "total_sleep_duration": 1800, "time_in_bed": 2000}
    calls: list = []

    def sleep_by_bedtime(url, kwargs):
        query = parse_qs(urlsplit(url).query)
        start, end = query["start_date"][0], query["end_date"][0]
        # What Oura does: /sleep filters a period by the date it started.
        return {"data": [d for d in (first_night, nap, night)
                         if start <= d["bedtime_start"][:10] < end], "next_token": None}

    fake_api(monkeypatch, {
        "/v2/usercollection/sleep/n": night,
        "/v2/usercollection/sleep": sleep_by_bedtime,
        "/v2/usercollection/heartrate": EMPTY,
    }, calls)
    record(settings, {"event_type": "create", "data_type": "sleep", "object_id": "n", "user_id": EXTERNAL_ID})
    assert oura.process_pending(settings) == 1

    assert any("/sleep?" in c["url"] and "start_date=2026-11-01" in c["url"] for c in calls)
    stored = hours(metric_rows(settings, "sleep_duration"))
    assert stored["2026-11-02"] == 7.0  # the night that was being missed
    # The partial extra day was not written over the complete one.
    assert stored["2026-11-01"] == 7.5


# --- OPS-03: heart rate is cut at the person's midnight -------------------------


def test_heart_rate_days_are_cut_at_the_persons_midnight(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    calls: list = []
    fake_api(monkeypatch, {"/v2/usercollection/heartrate": {"data": [
        {"timestamp": "2026-08-04T21:30:00+00:00", "bpm": 60},   # 00:30 on 5 Aug in Kyiv
        {"timestamp": "2026-08-05T20:30:00+00:00", "bpm": 100},  # 23:30 on 5 Aug in Kyiv
        {"timestamp": "2026-08-05T21:30:00+00:00", "bpm": 140},  # 00:30 on 6 Aug: not this day
    ], "next_token": None}}, calls)
    oura.sync_heartrate(settings, user_id, "2026-08-05", "2026-08-05")
    (row,) = metric_rows(settings, "daily_heart_rate")
    assert (row["day"], row["value"], row["sample_count"]) == ("2026-08-05", 80.0, 2)
    # The request covers the whole local day (EEST, UTC+3), not the UTC day.
    query = parse_qs(urlsplit(calls[-1]["url"]).query)
    assert query["start_datetime"] == ["2026-08-04T21:00:00+00:00"]
    assert query["end_datetime"] == ["2026-08-05T21:00:00+00:00"]

    # Winter is UTC+2: DST is honoured, not a fixed offset.
    oura.sync_heartrate(settings, user_id, "2026-01-15", "2026-01-15")
    query = parse_qs(urlsplit(calls[-1]["url"]).query)
    assert query["start_datetime"] == ["2026-01-14T22:00:00+00:00"]

    # The person's own zone setting decides, not a constant.
    with connect(settings) as db:
        db.execute("UPDATE users SET timezone='UTC' WHERE id=?", (user_id,))
    oura.sync_heartrate(settings, user_id, "2026-08-05", "2026-08-05")
    (row,) = metric_rows(settings, "daily_heart_rate")
    assert (row["value"], row["sample_count"]) == (120.0, 2)


# --- OPS-04: implausible nights are withheld, API and export alike ------------


def test_api_sleep_day_over_sixteen_hours_is_withheld_and_its_stale_copy_removed(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    night = {"id": "a", "day": "2026-08-03", "type": "long_sleep", "total_sleep_duration": 27000,
             "time_in_bed": 28800, "average_hrv": 50}
    other = {**night, "id": "b", "day": "2026-08-04"}
    fake_api(monkeypatch, {"/v2/usercollection/sleep": {"data": [night, other], "next_token": None}})
    oura.sync_range(settings, user_id, "sleep", "2026-08-03", "2026-08-04")
    assert hours(metric_rows(settings, "sleep_duration")) == {"2026-08-03": 7.5, "2026-08-04": 7.5}

    piled = [{**night, "id": f"x{i}", "total_sleep_duration": 21000, "time_in_bed": 21600} for i in range(3)]
    fake_api(monkeypatch, {"/v2/usercollection/sleep": {"data": [*piled, other], "next_token": None}})
    oura.sync_range(settings, user_id, "sleep", "2026-08-03", "2026-08-04")
    assert hours(metric_rows(settings, "sleep_duration")) == {"2026-08-04": 7.5}
    assert "2026-08-03" not in hours(metric_rows(settings, "heart_rate_variability_rmssd"))


SLEEP_COLUMNS = ["id", "day", "type", "bedtime_start", "bedtime_end", "total_sleep_duration",
                 "deep_sleep_duration", "rem_sleep_duration", "light_sleep_duration", "awake_time",
                 "time_in_bed", "lowest_heart_rate", "average_hrv", "average_breath", "efficiency"]


def period(pid: str, day: str, kind: str, start: str, end: str, asleep: int, in_bed: int) -> dict:
    return {"id": pid, "day": day, "type": kind, "bedtime_start": start, "bedtime_end": end,
            "total_sleep_duration": asleep, "light_sleep_duration": asleep, "time_in_bed": in_bed,
            "lowest_heart_rate": 50, "average_hrv": 40, "average_breath": 14, "efficiency": 90}


#: The shape the audit found (evening bedtimes, a rest period, an evening nap,
#: a period without `day`), with invented numbers.
PERIODS = [
    period("a", "2026-02-19", "long_sleep", "2026-02-19T00:40:00.000+02:00", "2026-02-19T07:30:00.000+02:00", 24000, 25200),
    period("b", "2026-02-20", "long_sleep", "2026-02-19T22:00:00.000+02:00", "2026-02-20T07:00:00.000+02:00", 28800, 32400),
    period("c", "2026-02-21", "rest", "2026-02-20T20:10:00.000+02:00", "2026-02-20T20:50:00.000+02:00", 900, 2400),
    period("d", "2026-02-21", "long_sleep", "2026-02-20T23:50:00.000+02:00", "2026-02-21T06:50:00.000+02:00", 22800, 25200),
    period("e", "2026-02-22", "sleep", "2026-02-21T18:40:00.000+02:00", "2026-02-21T19:10:00.000+02:00", 600, 1800),
    # No `day`: filed by the local day it ended on.
    period("f", "", "long_sleep", "2026-02-22T00:30:00.000+02:00", "2026-02-22T07:55:00.000+02:00", 21600, 26640),
    # Three long periods all claiming 25 Feb: 17.5 h, not a night anyone slept.
    *(period(f"q{i}", "2026-02-25", "long_sleep", "2026-02-24T23:00:00.000+02:00",
             "2026-02-25T06:00:00.000+02:00", 21000, 21600) for i in range(3)),
]


def write_takeout(root: Path) -> Path:
    app = root / "App Data"
    app.mkdir(parents=True, exist_ok=True)
    for name, columns, rows in (
        ("sleepmodel.csv", SLEEP_COLUMNS, PERIODS),
        ("heartrate.csv", ["timestamp", "bpm", "source"],
         [{"timestamp": "2026-02-18T22:30:00.000Z", "bpm": 58, "source": "rest"}]),
    ):
        with (app / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
    return root


def sleep_hours(parsed, key: str = "sleep_duration") -> dict[str, float]:
    return {item.day: round(item.value, 3) for item in parsed.aggregates if item.definition.key == key}


def test_takeout_files_each_period_under_its_own_day_and_withholds_impossible_nights(tmp_path: Path):
    parsed = OuraAdapter().parse(write_takeout(tmp_path))
    assert sleep_hours(parsed) == {
        "2026-02-19": 6.667,   # not 6.7 + the 22:00 bedtime that woke on the 20th
        "2026-02-20": 8.0,
        "2026-02-21": 6.333,   # the rest period is not sleep...
        "2026-02-22": 6.167,   # the 18:40 nap and the day-less night, both the 22nd
    }
    assert sleep_hours(parsed, "time_in_bed")["2026-02-21"] == round((2400 + 25200) / 3600, 3)  # ...but is in bed
    assert parsed.metadata["quarantined_sleep_days"] == [
        {"day": "2026-02-25", "source": "Oura", "sleep_duration": 17.5, "time_in_bed": 18.0}
    ]
    assert not any(item.day == "2026-02-25" for item in parsed.aggregates
                   if item.definition.key in oura.DATATYPE_KEYS["sleep"])
    # A UTC heart-rate sample at 22:30 is 00:30 the next morning in Kyiv...
    assert sleep_hours(parsed, "daily_heart_rate") == {"2026-02-19": 58.0}
    # ...and stays on the 18th for a person whose zone is UTC.
    parsed_utc = OuraAdapter().parse(tmp_path, tz=ZoneInfo("UTC"))
    assert sleep_hours(parsed_utc, "daily_heart_rate") == {"2026-02-18": 58.0}


def test_reimporting_the_same_export_replaces_the_bedtime_grouped_nights(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "health.sqlite3", source_dir=tmp_path / "sources",
                        secret_key="oura-reimport-secret")
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    migrate(settings)
    user_id = create_user(settings, "oura@example.test", "Oura", "a-long-local-password")
    patient_id = f"patient-{user_id}"
    with connect(settings) as db:
        db.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""",
            (patient_id, user_id, utc_now()),
        )
    source = write_takeout(tmp_path / "export")

    def run() -> dict:
        return import_device_export(settings, owner_user_id=user_id, patient_id=patient_id,
                                    vendor_key="oura", source=source)

    import_id = run()["import_id"]
    # What the bedtime-date grouping wrote under this same import: a 14.7 h
    # "night" on the 19th and a lone evening nap on a day of its own.
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET value=14.667, value_sum=14.667, sample_count=2 "
                   "WHERE import_id=? AND metric_key='sleep_duration' AND day='2026-02-19'", (import_id,))
        db.execute(
            """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id, source_name,
                   source_vendor, metric_key, metric_name, category, day, aggregation, unit, value,
                   value_sum, sample_count, created_at)
               VALUES ('bedtime-grouped', ?, ?, ?, 'Oura', 'Oura', 'sleep_duration', 'Time asleep',
                       'device_sleep', '2026-02-24', 'sum', 'hours', 17.5, 17.5, 3, ?)""",
            (user_id, patient_id, import_id, utc_now()),
        )

    assert run()["import_id"] == import_id  # same bytes, same fingerprint, same import
    assert hours(metric_rows(settings, "sleep_duration")) == {
        "2026-02-19": 6.667, "2026-02-20": 8.0, "2026-02-21": 6.333, "2026-02-22": 6.167,
    }
    with connect(settings) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


# --- OPS-05 / OPS-36: the scheduler -------------------------------------------


def test_daily_catch_up_runs_once_a_day_per_usable_account(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    synced: list[str] = []
    monkeypatch.setattr(oura, "sync_recent", lambda s, uid: synced.append(uid))
    assert oura.sync_due(settings) == 1 and synced == [user_id]
    # Throttled by state stored in the envelope: a restart does not refire it.
    assert oura.sync_due(settings) == 0 and synced == [user_id]
    # A day later it is due again.
    stale = "2000-01-01T00:00:00+00:00"
    oura._update_state(settings, user_id, last_recent_sync_at=stale)
    assert oura.sync_due(settings) == 1
    # An account waiting for reconnection is left alone.
    oura._update_state(settings, user_id, last_recent_sync_at=stale)
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET status='reauthorize' WHERE user_id=?", (user_id,))
    assert oura.sync_due(settings) == 0


def test_scheduler_drains_pending_events_and_survives_a_locked_database(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    fake_api(monkeypatch, {
        "/v2/usercollection/daily_sleep/doc-1": {"id": "doc-1", "day": "2026-08-02", "score": 75},
        "/v2/usercollection/daily_sleep": {"data": [{"id": "doc-1", "day": "2026-08-02", "score": 75}],
                                           "next_token": None},
        "/v2/usercollection/heartrate": EMPTY,
    })
    # The last webhook of the day: nothing else will arrive to process it.
    record(settings, {"event_type": "create", "data_type": "daily_sleep", "object_id": "doc-1",
                      "user_id": EXTERNAL_ID})
    passes = threading.Semaphore(0)

    def locked(_settings):
        passes.release()
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(oura, "sync_due", locked)
    monkeypatch.setattr(oura, "SCHEDULE_SECONDS", 0.01)
    stop, thread = oura.start_scheduler(settings)
    try:
        for _ in range(3):  # three failing passes, and the thread is still going
            assert passes.acquire(timeout=10)
        deadline = time.monotonic() + 10
        while pending(settings) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pending(settings) == []
        assert metric_rows(settings, "sleep_score")[0]["day"] == "2026-08-02"
        assert thread.is_alive()
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


def test_heartrate_chunks_never_ask_oura_for_more_than_30_days(monkeypatch):
    """Oura answers HTTP 400 to a heart-rate range over 30 days; chunks are
    whole local days, so the chunk length is the window length."""
    from datetime import datetime

    from anamna import oura

    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(oura, "ensure_envelope", lambda *a: "import")
    monkeypatch.setattr(oura, "_sync_account", lambda *a: ("acct",))
    monkeypatch.setattr(oura, "_write_days", lambda *a, **k: 0)

    def paged(settings, user_id, path, params):
        asked.append((params["start_datetime"], params["end_datetime"]))
        return []

    monkeypatch.setattr(oura, "_paged", paged)
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(oura, "user_timezone_for", lambda *a: ZoneInfo("Europe/Kyiv"))
    oura.sync_heartrate(None, "user", "2026-01-01", "2026-03-15")
    assert asked
    for start, end in asked:
        span = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        assert span.total_seconds() <= 30 * 86400, (start, end)
