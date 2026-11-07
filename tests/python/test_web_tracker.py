"""Tracker dashboards on the activity, mobility and sleep areas.

The fixture seeds a miniature wearable record — steps with a deliberate gap
day, a previous month at a different level, a heart metric filed under the
sleep category, and staged nights plus one unstaged night — because the
defects these tests guard against are wrong *windows* (a missing day averaged
in as zero, the comparison month bleeding into the current one) and wrong
*placement* (blood pressure rendered on the sleep page).
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate, utc_now
from anamna.devices.queries import area_tracker
from anamna.security import create_user
from anamna.web.app import create_app, format_date

from test_web_security import PASSWORD, seed_patient, settings_for
from test_web_profile import login


ANCHOR = datetime.date(2026, 8, 4)


def day(offset: int) -> str:
    return (ANCHOR - datetime.timedelta(days=offset)).isoformat()


def seed_days(settings, user_id, patient_id, metric_key, metric_name, category, unit, aggregation, rows):
    with connect(settings) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO vendors(id, canonical_name, created_at) VALUES ('vendor-watch', 'Test Watch', ?)",
            (utc_now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, imported_at
               ) VALUES ('import-watch', ?, ?, 'vendor-watch', 'apple_health', 'x', 'f', 1, ?)""",
            (user_id, patient_id, utc_now()),
        )
        for row_day, value in rows:
            connection.execute(
                """INSERT INTO device_metric_days(
                       id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit, value,
                       sample_count, created_at
                   ) VALUES (?, ?, ?, 'import-watch', 'Apple Watch', 'Apple Health',
                             ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    f"dmd-{metric_key}-{row_day}", user_id, patient_id,
                    metric_key, metric_name, category, row_day, aggregation, unit, value, utc_now(),
                ),
            )


GAP_DAY = day(3)


def build(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "tracker@example.test", "Tracker", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Tracker Patient")
    # Steps: the last 30 days at 10 000 with one unrecorded day, the 30 days
    # before that at 8 000 — a +25% month-on-month change.
    steps = [(day(offset), 10000.0) for offset in range(0, 30) if day(offset) != GAP_DAY]
    steps += [(day(offset), 8000.0) for offset in range(30, 60)]
    seed_days(settings, user_id, patient_id, "steps", "Daily steps", "device_activity", "steps", "sum", steps)
    # Recovery metrics land on the sleep page — except blood pressure, whose
    # primary area is the heart.
    seed_days(
        settings, user_id, patient_id, "daily_heart_rate", "Daily heart rate",
        "device_recovery", "bpm", "average", [(day(offset), 60.0) for offset in range(0, 10)],
    )
    seed_days(
        settings, user_id, patient_id, "systolic_blood_pressure", "Systolic blood pressure",
        "device_recovery", "mmHg", "average", [(day(offset), 120.0) for offset in range(0, 5)],
    )
    # Nights: the anchor night fully staged (7.5 h total), the night before
    # recorded only as a duration — it must draw as one unstaged block.
    for key, name, value in (
        ("sleep_deep", "Deep sleep", 1.0),
        ("sleep_core", "Core sleep", 4.0),
        ("sleep_rem", "REM sleep", 2.0),
        ("sleep_awake", "Awake during sleep", 0.5),
    ):
        seed_days(settings, user_id, patient_id, key, name, "device_sleep", "hours", "sum", [(day(0), value)])
    seed_days(
        settings, user_id, patient_id, "sleep_duration", "Time asleep", "device_sleep", "hours", "sum",
        [(day(0), 7.0), (day(1), 6.0)],
    )
    return settings, user_id


def test_windows_average_only_recorded_days_and_compare_months(tmp_path: Path):
    settings, user_id = build(tmp_path)
    with connect(settings) as connection:
        tracker = area_tracker(connection, user_id, "activity")
    assert tracker is not None
    card = next(item for item in tracker["cards"] if item["metric_key"] == "steps")
    # The gap day is a visible hole, not a zero — and not averaged in.
    assert len(card["bars"]) == 14
    hole = next(bar for bar in card["bars"] if bar["day"] == GAP_DAY)
    assert hole["value"] is None and hole["frac"] == 0.0
    assert math.isclose(card["avg7"], 10000.0)
    assert math.isclose(card["avg30"], 10000.0)
    assert math.isclose(card["prev30"], 8000.0)
    assert math.isclose(card["delta_pct"], 25.0)
    # Every recorded bar is scaled to the window's own peak.
    assert all(bar["frac"] == 1.0 for bar in card["bars"] if bar["value"] is not None)


def test_sleep_area_stacks_stages_and_keeps_blood_pressure_on_the_heart(tmp_path: Path):
    settings, user_id = build(tmp_path)
    with connect(settings) as connection:
        tracker = area_tracker(connection, user_id, "sleep")
    assert tracker is not None
    keys = {card["metric_key"] for card in tracker["cards"]}
    assert "daily_heart_rate" in keys
    assert "systolic_blood_pressure" not in keys, "blood pressure belongs to the heart page"
    assert not keys & {"sleep_deep", "sleep_core", "sleep_rem", "sleep_awake", "sleep_duration", "time_in_bed"}, (
        "the stacked chart already shows these; a bar card each would say it twice"
    )
    sleep = tracker["sleep"]
    assert sleep is not None
    nights = {night["day"]: night for night in sleep["nights"]}
    staged = nights[day(0)]
    assert staged["has_stages"]
    # 7.5 h is the fullest night, so its stack fills the track: fractions are
    # value / 7.5 and sum to 1.
    fracs = {segment["key"]: segment["frac"] for segment in staged["stages"]}
    assert math.isclose(fracs["sleep_core"], 4.0 / 7.5, abs_tol=1e-3)
    assert math.isclose(sum(fracs.values()), 1.0, abs_tol=1e-3)
    unstaged = nights[day(1)]
    assert not unstaged["has_stages"]
    assert math.isclose(unstaged["asleep_frac"], 6.0 / 7.5, abs_tol=1e-3)
    # This fixture draws an unstaged night, so the state that column is in is
    # named last, after the four stages and in their reading order.
    assert [item["key"] for item in sleep["legend"]] == [
        "sleep_deep", "sleep_core", "sleep_rem", "sleep_awake", "unstaged",
    ]


def test_area_pages_render_the_tracker_once(tmp_path: Path):
    settings, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "tracker@example.test")
        activity = client.get("/areas/activity").text
        assert 'class="an-tracker-card"' in activity
        assert "an-tracker-bar--empty" in activity, "the unrecorded day must stay visible as a gap"
        # The tracker covers every device metric here, so the flat measurement
        # grid must not repeat them (and must not render as an empty section).
        assert 'class="result-card an-metric-card"' not in activity

        sleep_page = client.get("/areas/sleep").text
        assert 'data-stage="sleep_deep"' in sleep_page
        assert 'data-stage="unstaged"' in sleep_page, "a night without stages still happened"
        assert '/devices/metrics/sleep_deep' in sleep_page, "the legend links each stage to its history"
        # Blood pressure's primary area is the heart: it may stay in the flat
        # measurement grid as related evidence, but never becomes a tracker
        # card on the sleep page.
        assert 'href="/devices/metrics/systolic_blood_pressure"' not in sleep_page.split("an-tracker-grid")[1].split("</section>")[0]

        # An area with no device data keeps its ordinary page.
        assert client.get("/areas/heart").status_code == 200


def build_duration_only(tmp_path: Path):
    """A sleeper whose device reports a nightly total and nothing else.

    No stage rows, no time in bed — an iPhone without a watch, a pre-watchOS-9
    export, a Fitbit or Mi Band import. The main fixture always stages the
    anchor night, which is exactly why this case stayed invisible.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "unstaged@example.test", "Unstaged", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Unstaged Patient")
    seed_days(
        settings, user_id, patient_id, "sleep_duration", "Time asleep", "device_sleep", "hours", "sum",
        [(day(offset), 7.0 - offset * 0.5) for offset in range(0, 5)],
    )
    return settings, user_id


def test_nights_without_stages_still_draw(tmp_path: Path):
    settings, user_id = build_duration_only(tmp_path)
    with connect(settings) as connection:
        tracker = area_tracker(connection, user_id, "sleep")
    assert tracker is not None
    sleep = tracker["sleep"]
    assert sleep is not None
    nights = {night["day"]: night for night in sleep["nights"]}
    assert not any(night["has_stages"] for night in sleep["nights"])
    # The peak that scales the chart has to be measured on the same quantity
    # the columns draw: scaled against the stages alone every night divided by
    # zero and fourteen invisible columns sat under a correct 30-day average.
    assert math.isclose(nights[day(0)]["asleep_frac"], 1.0)
    assert math.isclose(nights[day(4)]["asleep_frac"], 5.0 / 7.0, abs_tol=1e-3)
    assert all(nights[day(offset)]["asleep_frac"] > 0 for offset in range(0, 5))

    # The grey column has a colour and no other carrier of meaning, so the
    # legend names it — with no link and no average, because there is no such
    # metric page and no separate series.
    unstaged_row = next(item for item in sleep["legend"] if item["key"] == "unstaged")
    assert unstaged_row["url"] is None and unstaged_row["avg30"] is None
    assert unstaged_row["name"] and unstaged_row["hint"]

    with TestClient(create_app(settings)) as client:
        login(client, "unstaged@example.test")
        page = client.get("/areas/sleep").text
    assert 'data-stage="unstaged"' in page
    assert f"Sleep stages per night for the 14 days up to {format_date(day(0))}" in page
    assert "Stage not recorded" in page
    # Reachable without a hover, which a phone cannot perform.
    assert "did not break it into stages" in page
    assert '<a href="/devices/metrics/unstaged"' not in page


def test_unstaged_legend_row_stays_away_when_every_night_is_staged(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "staged@example.test", "Staged", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Staged Patient")
    for key, name, value in (
        ("sleep_deep", "Deep sleep", 1.0),
        ("sleep_core", "Core sleep", 4.0),
        ("sleep_rem", "REM sleep", 2.0),
        ("sleep_awake", "Awake during sleep", 0.5),
    ):
        seed_days(settings, user_id, patient_id, key, name, "device_sleep", "hours", "sum", [(day(0), value)])
    seed_days(
        settings, user_id, patient_id, "sleep_duration", "Time asleep", "device_sleep", "hours", "sum",
        [(day(0), 7.0)],
    )
    with connect(settings) as connection:
        tracker = area_tracker(connection, user_id, "sleep")
    legend = tracker["sleep"]["legend"]
    assert "unstaged" not in {item["key"] for item in legend}, (
        "a state nothing on the chart is in should not be advertised"
    )
    with TestClient(create_app(settings)) as client:
        login(client, "staged@example.test")
        assert "Stage not recorded" not in client.get("/areas/sleep").text


def test_area_filter_matches_the_python_classification(tmp_path: Path):
    """The page reads its own area in SQL now; the rule must not have shifted.

    A metric belongs to the area its `DEVICE_PRIMARY_AREA_BY_METRIC` entry
    names, else to its category's area, else to activity — and that last
    default is the one a `category IN (...)` filter silently loses.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "areas@example.test", "Areas", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Areas Patient")
    seed_days(
        settings, user_id, patient_id, "steps", "Daily steps", "device_activity", "steps", "sum",
        [(day(offset), 10000.0) for offset in range(0, 5)],
    )
    # A category no map knows: it falls to activity, and must still get there.
    seed_days(
        settings, user_id, patient_id, "surf_time", "Surf time", "device_watersports", "min", "sum",
        [(day(offset), 45.0) for offset in range(0, 5)],
    )
    seed_days(
        settings, user_id, patient_id, "walking_speed", "Walking speed", "device_mobility", "km/h",
        "average", [(day(offset), 4.8) for offset in range(0, 5)],
    )
    # Categorised as recovery (the sleep page) but named to the heart page.
    seed_days(
        settings, user_id, patient_id, "systolic_blood_pressure", "Systolic blood pressure",
        "device_recovery", "mmHg", "average", [(day(offset), 120.0) for offset in range(0, 5)],
    )
    with connect(settings) as connection:
        areas = {
            area: area_tracker(connection, user_id, area)
            for area in ("activity", "mobility", "sleep")
        }
    assert {card["metric_key"] for card in areas["activity"]["cards"]} == {"steps", "surf_time"}
    assert {card["metric_key"] for card in areas["mobility"]["cards"]} == {"walking_speed"}
    # Blood pressure is the heart's, and it was the only recovery-categorised
    # metric here — so the sleep page has no tracker at all rather than a card.
    assert areas["sleep"] is None


def build_dormant(tmp_path: Path):
    """One live metric and one whose sensor stopped six weeks ago."""
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "dormant@example.test", "Dormant", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Dormant Patient")
    seed_days(
        settings, user_id, patient_id, "steps", "Daily steps", "device_activity", "steps", "sum",
        [(day(offset), 10000.0) for offset in range(0, 10)],
    )
    seed_days(
        settings, user_id, patient_id, "flights_climbed", "Flights climbed", "device_activity",
        "count", "sum", [(day(offset), 12.0) for offset in range(40, 45)],
    )
    return settings, user_id


def test_dormant_metric_says_so_instead_of_showing_an_empty_strip(tmp_path: Path):
    settings, user_id = build_dormant(tmp_path)
    with connect(settings) as connection:
        tracker = area_tracker(connection, user_id, "activity")
    assert tracker is not None
    cards = {card["metric_key"]: card for card in tracker["cards"]}
    stale = cards["flights_climbed"]
    # The window is anchored on the area's newest day, so this metric's own
    # readings fall outside it entirely.
    assert stale["dormant"] is True
    assert stale["latest_day"] == day(40)
    assert all(bar["value"] is None for bar in stale["bars"])
    assert cards["steps"]["dormant"] is False

    with TestClient(create_app(settings)) as client:
        login(client, "dormant@example.test")
        page = client.get("/areas/activity").text
    assert (
        f"Nothing recorded in the last 14 days. The most recent reading is from {format_date(day(40))}."
        in page
    )
    # Only the live metric draws a strip; the dormant card explains itself.
    assert page.count('class="an-tracker-bars"') == 1
    assert f"daily values for the 14 days up to {format_date(day(0))}" in page
