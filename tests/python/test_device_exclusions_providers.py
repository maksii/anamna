"""'Not my reading' for the direct provider APIs, and for a rule that arrives
while a sync or an import is already running.

Oura and Garmin write the same tables as OpenWearables, through their own
mappers and their own write transactions.  A rule must hold there too: a
re-sync of the same answer keeps the reading out, undo brings it back, and a
rule saved between a sync's fetch and its write still wins.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from anamna import garmin, garmin_personal, openwearables, oura
from anamna.db import connect
from anamna.devices import exclusions
from anamna.devices import importer

import test_oura
from test_device_exclusions import HIS, SCALE_LABEL, exclude, value, weigh_ins
from test_garmin import GARMIN_USER, KEY, connect_business, deliver, epoch, personal_api
from test_garmin import configure as configure_garmin
from test_openwearables import configure, fake_api, link, page, routes
from test_web_panels import build

DAY = "2026-08-05"


def stored(settings, key: str, day: str, source: str):
    with connect(settings) as db:
        row = db.execute("SELECT value FROM device_metric_days WHERE metric_key=? AND day=? AND source_name=?",
                         (key, day, source)).fetchone()
    return None if row is None else round(row[0], 3)


# --- Oura ----------------------------------------------------------------------


def oura_routes(monkeypatch):
    test_oura.fake_api(monkeypatch, {
        "/v2/usercollection/heartrate": {"data": [
            {"bpm": 60, "source": "awake", "timestamp": f"{DAY}T07:00:00+00:00"},
            {"bpm": 120, "source": "awake", "timestamp": f"{DAY}T11:00:00+00:00"},
        ]},
        "/v2/usercollection/daily_activity": {"data": [
            {"day": "2026-08-04", "steps": 4000, "active_calories": 300, "total_calories": 2100},
            {"day": DAY, "steps": 5000, "active_calories": 350, "total_calories": 2200},
        ]},
        "/v2/usercollection/": {"data": []},
    })


def test_oura_readings_and_days_stay_out_on_resync_and_come_back_on_undo(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    test_oura.configure(settings)
    test_oura.connect_account(settings, user_id)
    oura_routes(monkeypatch)
    oura.sync_heartrate(settings, user_id, DAY, DAY)
    oura.sync_range(settings, user_id, "daily_activity", "2026-08-04", DAY)
    assert stored(settings, "daily_heart_rate", DAY, "Oura") == 90
    assert stored(settings, "steps", DAY, "Oura") == 5000

    pulse = exclusions.create(settings, user_id, user_id, provider="oura_api", source="Oura", scope="reading",
                              from_text=f"{DAY}T11:00:00Z")
    # The page's day button: the person's own local day, one series.
    steps = exclusions.create(settings, user_id, user_id, provider="oura_api", source="Oura", scope="window",
                              from_text=f"{DAY}T00:00", until_text=f"{DAY}T23:59", series=["steps"])
    exclusions.run_pending(settings, user_id)
    assert stored(settings, "daily_heart_rate", DAY, "Oura") == 60
    assert stored(settings, "steps", DAY, "Oura") is None
    # Oura dates a day in the person's zone: the day before is untouched.
    assert stored(settings, "steps", "2026-08-04", "Oura") == 4000
    assert stored(settings, "active_energy", DAY, "Oura") == 350

    oura.sync_heartrate(settings, user_id, DAY, DAY)
    oura.sync_range(settings, user_id, "daily_activity", "2026-08-04", DAY)
    assert stored(settings, "daily_heart_rate", DAY, "Oura") == 60
    assert stored(settings, "steps", DAY, "Oura") is None

    for rule in (pulse, steps):
        exclusions.undo(settings, user_id, user_id, rule)
    exclusions.run_pending(settings, user_id)
    assert stored(settings, "daily_heart_rate", DAY, "Oura") == 90
    assert stored(settings, "steps", DAY, "Oura") == 5000


def test_oura_rules_need_the_network_so_they_settle_in_the_background(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    test_oura.configure(settings)
    test_oura.connect_account(settings, user_id)
    oura_routes(monkeypatch)
    oura.sync_heartrate(settings, user_id, DAY, DAY)
    exclusions.create(settings, user_id, user_id, provider="oura_api", source="Oura", scope="reading",
                      from_text=f"{DAY}T11:00:00Z")
    spawned = []
    monkeypatch.setattr(exclusions, "_spawn", lambda *args: spawned.append(args))
    assert exclusions.settle(settings, user_id) == "queued" and spawned


# --- Garmin, pushed summaries ----------------------------------------------------


def body_comp(summary_id: str, stamp: str, grams: int, bmi: float) -> dict:
    return {"userId": GARMIN_USER, "summaryId": summary_id, "measurementTimeInSeconds": epoch(stamp),
            "measurementTimeOffsetInSeconds": 10800, "weightInGrams": grams, "bodyMassIndex": bmi}


def test_garmin_pushed_weigh_ins_are_rebuilt_from_the_mirror(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure_garmin(settings)
    connect_business(settings, user_id)
    deliver(settings, {"bodyComps": [
        body_comp("b-her", f"{DAY}T07:00:00+03:00", 55000, 20.1),
        body_comp("b-his", f"{DAY}T21:00:00+03:00", 110000, 40.8),
    ]})
    garmin.process_pending(settings)
    assert stored(settings, "body_weight", DAY, "Garmin") == 110

    rule = exclusions.create(settings, user_id, user_id, provider="garmin_api", source="Garmin", scope="reading",
                             from_text=f"{DAY}T18:00:00Z")
    assert exclusions.settle(settings, user_id) == "applied"  # the mirror is local
    assert stored(settings, "body_weight", DAY, "Garmin") == 55
    assert stored(settings, "body_mass_index", DAY, "Garmin") == 20.1

    # The same summary delivered again stays out.
    deliver(settings, {"bodyComps": [body_comp("b-his", f"{DAY}T21:00:00+03:00", 110000, 40.8)]})
    garmin.process_pending(settings)
    assert stored(settings, "body_weight", DAY, "Garmin") == 55

    exclusions.undo(settings, user_id, user_id, rule)
    exclusions.run_pending(settings, user_id)
    assert stored(settings, "body_weight", DAY, "Garmin") == 110


# --- Garmin, personal key ----------------------------------------------------------


def test_garmin_personal_scale_and_device_exclusions(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure_garmin(settings, personal=True)
    personal_api(monkeypatch)
    garmin_personal.link_key(settings, user_id, KEY)
    garmin_personal.sync_dataset(settings, user_id, "weight", "2026-08-01", "2026-08-31")
    garmin_personal.sync_activities(settings, user_id, "2026-11-01", "2026-11-03")
    assert stored(settings, "body_weight", "2026-08-08", garmin.SCALE_SOURCE_NAME) == 110
    scale_instant = datetime.fromtimestamp(1786199811, UTC).isoformat()

    rule = exclude(settings, user_id, provider="garmin_personal_api", source=garmin.SCALE_SOURCE_NAME,
                   scope="reading", from_text=scale_instant)
    assert stored(settings, "body_weight", "2026-08-08", garmin.SCALE_SOURCE_NAME) is None
    assert stored(settings, "body_fat_percentage", "2026-08-08", garmin.SCALE_SOURCE_NAME) is None
    # Another source on the same day is not this rule's.
    assert stored(settings, "body_weight", "2026-08-08", garmin.MANUAL_WEIGHT_SOURCE_NAME) == 110.5
    garmin_personal.sync_dataset(settings, user_id, "weight", "2026-08-01", "2026-08-31")
    assert stored(settings, "body_weight", "2026-08-08", garmin.SCALE_SOURCE_NAME) is None

    device = exclude(settings, user_id, provider="garmin_personal_api", source=garmin.SOURCE_NAME, scope="origin")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
    garmin_personal.sync_activities(settings, user_id, "2026-11-01", "2026-11-03")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0

    for undone in (rule, device):
        exclusions.undo(settings, user_id, user_id, undone)
    exclusions.run_pending(settings, user_id)
    assert stored(settings, "body_weight", "2026-08-08", garmin.SCALE_SOURCE_NAME) == 110
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 1


def test_the_review_page_offers_provider_api_rows(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    test_oura.configure(settings)
    test_oura.connect_account(settings, user_id)
    oura_routes(monkeypatch)
    oura.sync_range(settings, user_id, "daily_activity", "2026-08-04", DAY)
    from anamna.web import app as web

    assert web._review_url("steps", DAY, "Oura").replace("&", "&amp;") in client.get("/devices/metrics/steps").text
    review = client.get(web._review_url("steps", DAY, "Oura")).text
    assert 'name="origin_provider" value="oura_api"' in review and "Not my device" in review
    assert "provider&#39;s own connection" in review or "provider's own connection" in review


# --- a rule that arrives mid-sync ----------------------------------------------------


def test_a_rule_saved_between_the_fetch_and_the_write_wins(tmp_path: Path, monkeypatch):
    """The sync fetched the weigh-in; the person excluded it before the sync
    wrote.  Rules are read inside the write transaction, so it never lands."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(series=page(weigh_ins())))
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    original = openwearables.ensure_envelope

    def rule_arrives(*args):
        if not exclusions.version(connect(settings), user_id)[0]:
            exclusions.create(settings, user_id, user_id, provider="apple", source="Connect",
                              device="iPhone16,2", scope="reading", from_text=HIS)
        return original(*args)

    monkeypatch.setattr(openwearables, "ensure_envelope", rule_arrives)
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    assert value(settings, "body_weight", "2026-04-27") == 55.27


def test_a_rule_saved_while_the_sync_holds_its_write_wins(tmp_path: Path, monkeypatch):
    """The rule's save waits for the sync's write lock; its rebuild then runs
    after the sync committed and removes what the sync wrote."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(series=page(weigh_ins())))
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    holding, done = threading.Event(), threading.Event()
    original = openwearables._in_window

    def slow_window(*args):
        holding.set()
        time.sleep(0.5)  # the sync holds its write transaction here
        return original(*args)

    def save_rule():
        holding.wait(5)
        exclusions.create(settings, user_id, user_id, provider="apple", source="Connect",
                          device="iPhone16,2", scope="reading", from_text=HIS)
        exclusions.settle(settings, user_id)
        done.set()

    monkeypatch.setattr(openwearables, "_in_window", slow_window)
    worker = threading.Thread(target=save_rule)
    worker.start()
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    worker.join(10)
    assert done.is_set()
    assert value(settings, "body_weight", "2026-04-27") == 55.27


def test_a_rule_saved_while_a_file_is_parsed_makes_the_import_parse_again(tmp_path: Path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    export = tmp_path / "export" / "export.xml"
    export.parent.mkdir()
    export.write_text("<HealthData>\n" + "\n".join(
        f'<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Connect" unit="kg" '
        f'startDate="{stamp}" endDate="{stamp}" value="{amount}"/>'
        for stamp, amount in (("2026-04-27 08:00:00 +0300", 55.2), ("2026-04-27 14:18:48 +0300", 109.87))
    ) + "\n</HealthData>", encoding="utf-8")
    with connect(settings) as db:
        patient_id = db.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
    importer.import_device_export(settings, owner_user_id=user_id, patient_id=patient_id,
                                  vendor_key="apple_health", source=export)
    from anamna.devices import apple_health

    parses = []
    original = apple_health.AppleHealthAdapter.parse

    def parse(self, *args, **kwargs):
        parses.append(1)
        if len(parses) == 1:
            exclusions.create(settings, user_id, user_id, provider="apple_health", source="Connect",
                              scope="reading", from_text=HIS)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(apple_health.AppleHealthAdapter, "parse", parse)
    importer.import_device_export(settings, owner_user_id=user_id, patient_id=patient_id,
                                  vendor_key="apple_health", source=export)
    assert len(parses) == 2
    assert stored(settings, "body_weight", "2026-04-27", "Connect") == 55.2


def test_the_scale_label_is_unchanged():
    assert exclusions.ow_label("apple", "Connect", "iPhone16,2") == SCALE_LABEL
