"""Regression tests for defects found reviewing the wearable paths (2026-11-05).

Each test names the failure it guards: Oura's exclusive end_date hiding
today, a whole-second page boundary failing an OpenWearables window, the
0.11 walking-heart-rate rename reading as deleted days, a naive token expiry
crashing every caller, and a concurrent 401 expiring a freshly rotated token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from anamna import integrations, openwearables, oura
from anamna.db import connect

from test_oura import EXTERNAL_ID, configure, connect_account, fake_api, metric_rows
from test_web_panels import build


def test_oura_asks_past_the_end_day_and_keeps_only_the_window(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    calls: list = []
    fake_api(monkeypatch, {
        "/v2/usercollection/personal_info": {"id": EXTERNAL_ID},
        "/v2/usercollection/daily_sleep": {"data": [
            {"id": "a", "day": "2026-11-05", "score": 80},
            {"id": "b", "day": "2026-11-06", "score": 70},  # outside [start, end]
        ]},
    }, calls)
    oura.sync_range(settings, user_id, "daily_sleep", "2026-11-01", "2026-11-05")
    assert "end_date=2026-11-06" in [c["url"] for c in calls if "daily_sleep" in c["url"]][0]
    assert [(r["day"], r["value"]) for r in metric_rows(settings, "sleep_score")] == [("2026-11-05", 80)]


def test_a_page_ending_on_the_last_whole_second_still_advances():
    window = {"start_time": "2026-11-01T00:00:00Z", "end_time": "2026-11-05T23:59:59.999999Z"}
    advanced = openwearables._advance_timestamps([{"timestamp": "2026-11-05T23:59:59Z"}], window)
    assert advanced is not None and advanced["start_time"] == "2026-11-05T23:59:59Z"
    assert openwearables._advance_timestamps([{"timestamp": "2026-11-06T00:00:00Z"}], window) is None


def test_renamed_walking_heart_rate_series_still_maps():
    bucket: dict = {}
    openwearables.map_raw_metrics([
        {"type": "walking_heart_rate", "timestamp": "2026-11-05T10:00:00Z", "value": 98, "unit": "bpm"},
        {"type": "walking_heart_rate_average", "timestamp": "2026-11-04T10:00:00Z", "value": 96, "unit": "bpm"},
    ], bucket)
    assert sorted((key[0], key[1]) for key in bucket) == [
        ("walking_heart_rate", "2026-11-04"), ("walking_heart_rate", "2026-11-05")]


def test_a_naive_expiry_is_read_as_utc_not_a_crash():
    soon = (datetime.now(UTC) + timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    assert 200 < integrations.expires_in({"token_expires_at": soon}) <= 300


def test_a_401_only_expires_the_token_that_failed(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure(settings)
    connect_account(settings, user_id)
    later = (datetime.now(UTC) + timedelta(hours=10)).replace(microsecond=0).isoformat()

    def rotated_meanwhile(url, kwargs):
        # Another request rotated the pair between our GET and its 401.
        with connect(settings) as db:
            db.execute("UPDATE provider_connections SET access_token='fresh', token_expires_at=? WHERE provider='oura'", (later,))
        raise integrations.IntegrationError("HTTP 401", status=401)

    calls: list = []
    fake_api(monkeypatch, {"/v2/usercollection/personal_info": rotated_meanwhile}, calls)
    try:
        oura.api_get(settings, user_id, "/v2/usercollection/personal_info")
    except integrations.IntegrationError:
        pass
    row = integrations.connection_row(settings, user_id, "oura")
    assert row["token_expires_at"] == later  # the fresh token was not expired
    assert not any("/oauth/token" in c["url"] for c in calls)  # and no refresh was burned
