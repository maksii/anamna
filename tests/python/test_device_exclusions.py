"""'Not my reading': a shared scale's weigh-ins and the energy derived from them.

The case these tests are shaped on is real: a Garmin Index scale paired to one
phone writes both partners' weigh-ins into that phone's Apple Health, and
OpenWearables serves all of them as the phone owner's.  Her watch then
computes resting and total energy from his weight until her next weigh-in.

What is guarded is that a rule, once made, holds at every place rows enter
aggregation: a re-sync of the same payload, the raw recompute (including the
summary fallback that fills a day no raw sample covers), the offline
re-aggregation, and a file re-import; and that undo puts everything back.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import openwearables
from anamna import openwearables_archive as archive
from anamna.db import connect, transaction, utc_now
from anamna.devices import exclusions
from anamna.devices.importer import import_device_export
from anamna.devices.reaggregate import reaggregate_openwearables
from anamna.openwearables_webhooks import _sample_rows
from anamna.security import create_session, create_user
from anamna.web import app as web
from anamna.web.app import create_app

from test_openwearables import BASE, REMOTE, configure, fake_api, link, page, routes
from test_web_panels import PASSWORD, build

SCALE = {"provider": "apple", "source": "Connect", "device": "iPhone16,2",
         "device_name": "iPhone 15 Pro Max", "device_type": "phone"}
WATCH = {"provider": "apple", "source": "Olena Apple Watch", "device": "Watch7,2",
         "device_name": "Apple Watch Series 9 45mm (GPS)", "device_type": "watch"}
SCALE_LABEL = "OpenWearables · apple · Connect · iPhone16,2"
WATCH_LABEL = "OpenWearables · apple · Olena Apple Watch · Watch7,2"
HIS = "2026-04-27T11:18:48Z"
HER_NEXT = "2026-05-03T08:35:38Z"


def body(stamp: str, kind: str, value: float, unit: str) -> dict:
    return {"timestamp": stamp, "type": kind, "value": value, "unit": unit, "source": SCALE,
            "is_daily_total": None, "zone_offset": None}


def weigh_ins() -> list[dict]:
    rows = [body(f"2026-04-{day:02d}T05:00:00Z", "weight", 55.0 + day / 100, "kg") for day in range(20, 28)]
    return rows + [body(HIS, "weight", 109.87, "kg"), body(HIS, "body_mass_index", 40.8, "kg_m2"),
                   body(HIS, "body_fat_percentage", 40.0, "percent")]


def activity(day: str, total: float = 1400.0) -> dict:
    return {"date": day, "source": WATCH, "steps": 205, "distance_meters": 135.9, "floors_climbed": None,
            "elevation_meters": None, "active_calories_kcal": 37.5, "total_calories_kcal": total,
            "active_minutes": 2, "sedentary_minutes": 6, "intensity_minutes": {"light": 2, "moderate": 0, "vigorous": 0},
            "heart_rate": {"avg_bpm": 72, "max_bpm": 104, "min_bpm": 58}}


def value(settings, key: str, day: str, source: str = SCALE_LABEL):
    with connect(settings) as db:
        row = db.execute("SELECT value FROM device_metric_days WHERE metric_key=? AND day=? AND source_name=?",
                         (key, day, source)).fetchone()
    return None if row is None else round(row[0], 3)


def linked_with_body(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    fake_api(monkeypatch, routes(series=page(weigh_ins())))
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    return settings, user_id, client


def store_samples(settings, user_id: str, samples: list[dict]) -> None:
    with transaction(settings) as db:
        archive.merge_samples(db, (user_id, BASE, REMOTE), _sample_rows(samples))


def exclude(settings, user_id: str, **fields) -> str:
    exclusion_id = exclusions.create(settings, user_id, user_id, **fields)
    exclusions.run_pending(settings, user_id)
    return exclusion_id


def test_one_weigh_in_goes_with_its_bmi_and_fat_and_stays_out_on_every_rebuild(tmp_path, monkeypatch):
    settings, user_id, _client = linked_with_body(tmp_path, monkeypatch)
    assert value(settings, "body_weight", "2026-04-27") == 109.87
    assert value(settings, "body_mass_index", "2026-04-27") == 40.8

    rule = exclude(settings, user_id, provider="apple", source="Connect", device="iPhone16,2",
                   scope="reading", from_text=HIS)
    # The day keeps her own earlier weigh-in; the BMI and fat written at his
    # instant leave with it, though the rule named no series.
    assert value(settings, "body_weight", "2026-04-27") == 55.27
    assert value(settings, "body_mass_index", "2026-04-27") is None
    assert value(settings, "body_fat_percentage", "2026-04-27") is None
    assert value(settings, "body_weight", "2026-04-26") == 55.26

    # The same payload again: a re-sync cannot bring it back.
    openwearables.sync_datatype(settings, user_id, "body_series", "2026-04-20", "2026-04-28")
    assert value(settings, "body_weight", "2026-04-27") == 55.27
    # Nor can the offline re-cut over the whole archive.
    reaggregate_openwearables(settings, user_id, pause=0)
    assert value(settings, "body_weight", "2026-04-27") == 55.27

    # The archive itself is untouched.
    with connect(settings) as db:
        archived = [json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM openwearables_raw_records WHERE datatype='body_series' AND day='2026-04-27'")]
    assert {row["value"] for row in archived} >= {109.87, 40.8, 40.0}

    assert exclusions.undo(settings, user_id, user_id, rule)
    exclusions.run_pending(settings, user_id)
    assert value(settings, "body_weight", "2026-04-27") == 109.87
    assert value(settings, "body_mass_index", "2026-04-27") == 40.8
    with connect(settings) as db:
        actions = [row[0] for row in db.execute(
            "SELECT action FROM audit_events WHERE entity_type='device_exclusion' ORDER BY id")]
    assert actions == ["device_exclusion_created", "device_exclusion_undone"]


def test_a_link_made_before_the_server_was_recorded_still_rebuilds(tmp_path, monkeypatch):
    """Older links keep no remote_server_url in their state (the live record
    has one); the archive names the server instead."""
    settings, user_id, _client = linked_with_body(tmp_path, monkeypatch)
    with connect(settings) as db:
        row = db.execute("SELECT id, metadata_json FROM device_imports WHERE adapter_key=?",
                         (openwearables.ADAPTER_KEY,)).fetchone()
        state = json.loads(row["metadata_json"])
        state.pop("remote_server_url")
        db.execute("UPDATE device_imports SET metadata_json=? WHERE id=?", (json.dumps(state), row["id"]))
    exclude(settings, user_id, provider="apple", source="Connect", device="iPhone16,2",
            scope="reading", from_text=HIS)
    assert value(settings, "body_weight", "2026-04-27") == 55.27


def test_summary_fallback_cannot_bring_an_excluded_raw_reading_back(tmp_path, monkeypatch):
    """recompute_raw_days fills a day no raw sample covers from the activity
    summary.  An excluded sample still covers its day, so the summary's own
    copy of the same steps stays out."""
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    store_samples(settings, user_id, [{"timestamp": "2026-04-27T09:00:00Z", "type": "steps", "value": 205,
                                       "unit": "count", "source": WATCH, "is_daily_total": False}])
    fake_api(monkeypatch, routes(activity=page([activity("2026-04-27")])))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-04-27", "2026-04-27")
    assert value(settings, "steps", "2026-04-27", WATCH_LABEL) == 205

    exclude(settings, user_id, provider="apple", source=WATCH["source"], device="Watch7,2",
            scope="reading", from_text="2026-04-27T09:00:00Z")
    assert value(settings, "steps", "2026-04-27", WATCH_LABEL) is None
    # The day's own summary totals were not that reading.
    assert value(settings, "total_energy", "2026-04-27", WATCH_LABEL) == 1400.0
    openwearables.sync_datatype(settings, user_id, "activity", "2026-04-27", "2026-04-27")
    assert value(settings, "steps", "2026-04-27", WATCH_LABEL) is None


def test_a_window_removes_energy_derived_from_the_wrong_weight(tmp_path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    configure(settings)
    link(settings, user_id)
    store_samples(settings, user_id, [
        {"timestamp": f"2026-04-27T{hour:02d}:00:00Z", "type": "basal_energy", "value": 50, "unit": "kcal",
         "source": WATCH, "is_daily_total": False} for hour in range(24)])
    days = ["2026-04-26", "2026-04-27", "2026-04-28", "2026-05-03", "2026-05-04"]
    fake_api(monkeypatch, routes(activity=page([activity(day) for day in days])))
    openwearables.sync_datatype(settings, user_id, "activity", "2026-04-26", "2026-05-04")
    assert value(settings, "resting_energy", "2026-04-27", WATCH_LABEL) == 1050  # Kyiv day: 00-20 UTC

    exclude(settings, user_id, provider="apple", source=WATCH["source"], device="Watch7,2", scope="window",
            from_text=HIS, until_text=HER_NEXT, series=["resting_energy", "total_energy"])
    totals = {day: value(settings, "total_energy", day, WATCH_LABEL) for day in days}
    # A daily total that overlaps the window goes whole; its neighbours stay.
    assert totals == {"2026-04-26": 1400.0, "2026-04-27": None, "2026-04-28": None,
                      "2026-05-03": None, "2026-05-04": 1400.0}
    # Hourly samples are cut at the instant: 00:00-11:00 UTC are hers.
    assert value(settings, "resting_energy", "2026-04-27", WATCH_LABEL) == 600
    # Series the rule did not name are untouched.
    assert value(settings, "steps", "2026-04-28", WATCH_LABEL) == 205


def test_a_whole_device_and_its_workouts(tmp_path, monkeypatch):
    settings, user_id, _client = linked_with_body(tmp_path, monkeypatch)
    fake_api(monkeypatch, routes(workouts=page([{
        "id": "w1", "type": "walking", "start_time": "2026-04-27T10:00:00Z", "end_time": "2026-04-27T10:20:00Z",
        "duration_seconds": 1200, "source": SCALE, "calories_kcal": 50, "distance_meters": 900}])))
    openwearables.sync_workouts(settings, user_id, "2026-04-01", "2026-04-30")
    rule = exclude(settings, user_id, provider="apple", source="Connect", device="iPhone16,2", scope="origin")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days WHERE source_name=?", (SCALE_LABEL,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
    openwearables.sync_workouts(settings, user_id, "2026-04-01", "2026-04-30")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
    exclusions.undo(settings, user_id, user_id, rule)
    exclusions.run_pending(settings, user_id)
    assert value(settings, "body_weight", "2026-04-27") == 109.87
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 1


def test_a_file_export_re_import_keeps_the_reading_out(tmp_path, monkeypatch):
    settings, user_id, _client = build(tmp_path)
    export = tmp_path / "export" / "export.xml"
    export.parent.mkdir()

    def record(kind, stamp, amount, unit):
        return (f'<Record type="HKQuantityTypeIdentifier{kind}" sourceName="Connect" unit="{unit}" '
                f'startDate="{stamp}" endDate="{stamp}" value="{amount}"/>')

    export.write_text("<HealthData>\n" + "\n".join([
        record("BodyMass", "2026-04-27 08:00:00 +0300", 55.2, "kg"),
        record("BodyMass", "2026-04-27 14:18:48 +0300", 109.87, "kg"),
        record("BodyMassIndex", "2026-04-27 14:18:48 +0300", 40.8, "count"),
    ]) + "\n</HealthData>", encoding="utf-8")
    with connect(settings) as db:
        patient_id = db.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]

    def reimport():
        import_device_export(settings, owner_user_id=user_id, patient_id=patient_id,
                             vendor_key="apple_health", source=export)

    reimport()
    assert value(settings, "body_weight", "2026-04-27", "Connect") == 109.87
    exclusions.create(settings, user_id, user_id, provider="apple_health", source="Connect",
                      scope="reading", from_text=HIS)
    # A file is re-read whole, so this is never done inside a request.
    spawned = []
    monkeypatch.setattr(exclusions, "_spawn", lambda *args: spawned.append(args))
    assert exclusions.settle(settings, user_id) == "queued" and spawned
    exclusions.run_pending(settings, user_id)
    assert value(settings, "body_weight", "2026-04-27", "Connect") == 55.2
    assert value(settings, "body_mass_index", "2026-04-27", "Connect") is None
    reimport()
    assert value(settings, "body_weight", "2026-04-27", "Connect") == 55.2


def test_rules_are_validated_and_one_rule_is_made_once(tmp_path, monkeypatch):
    settings, user_id, _client = linked_with_body(tmp_path, monkeypatch)
    with pytest.raises(exclusions.ExclusionError):
        exclusions.create(settings, user_id, user_id, provider="apple", source="Unknown", scope="origin")
    with pytest.raises(exclusions.ExclusionError):
        exclusions.create(settings, user_id, user_id, provider="apple", source="Connect", device="iPhone16,2",
                          scope="window", from_text=HER_NEXT, until_text=HIS)
    with pytest.raises(exclusions.ExclusionError):
        exclusions.create(settings, user_id, user_id, provider="apple", source="Connect", device="iPhone16,2",
                          scope="reading", from_text=HIS, series=["'; DROP TABLE users"])
    first = exclusions.create(settings, user_id, user_id, provider="apple", source="Connect",
                              device="iPhone16,2", scope="reading", from_text=HIS)
    again = exclusions.create(settings, user_id, user_id, provider="apple", source="Connect",
                              device="iPhone16,2", scope="reading", from_text="2026-04-27T14:18:48+03:00")
    assert first == again


# --- the web flow ------------------------------------------------------------


def csrf(settings, client: TestClient) -> str:
    digest = hashlib.sha256(client.cookies["anamna_session"].encode()).hexdigest()
    with connect(settings) as db:
        return db.execute("SELECT csrf_token FROM sessions WHERE token_hash=?", (digest,)).fetchone()[0]


def test_the_page_offers_the_check_and_the_post_goes_through_the_app(tmp_path, monkeypatch):
    settings, user_id, client = linked_with_body(tmp_path, monkeypatch)
    page_html = client.get("/devices/metrics/body_weight").text
    review = web._review_url("body_weight", "2026-04-27", SCALE_LABEL)
    assert review.replace("&", "&amp;") in page_html
    # 109.87 against a median of about 55: suggested, never excluded.
    assert "Readings that may not be yours" in page_html

    reading = client.get(review)
    assert reading.status_code == 200
    assert "2026-04-27T11:18:48.000000+00:00" in reading.text and "Not my device" in reading.text
    client.cookies.set("anamna_lang", "uk")
    assert "Не моє вимірювання" in client.get(review).text
    assert "Виключені вимірювання" in client.get("/devices/exclusions").text
    client.cookies.set("anamna_lang", "en")

    form = {"scope": "reading", "origin_provider": "apple", "origin_source": "Connect",
            "origin_device": "iPhone16,2", "from_utc": HIS, "next": review}
    assert client.post("/devices/exclusions", data=form, follow_redirects=False).status_code == 403

    with connect(settings) as db:
        before = web._FINGERPRINT_SQL["device"]
        print_before = tuple(db.execute(before, (user_id,) * before.count("?")).fetchone())
    response = client.post("/devices/exclusions", data={**form, "csrf_token": csrf(settings, client)},
                           follow_redirects=False)
    assert response.status_code == 303 and "status=applied" in response.headers["location"]
    with connect(settings) as db:
        assert tuple(db.execute(before, (user_id,) * before.count("?")).fetchone()) != print_before
    assert value(settings, "body_weight", "2026-04-27") == 55.27

    listing = client.get(response.headers["location"])
    assert "Done. The affected days" in listing.text and "One reading" in listing.text
    detail = client.get("/devices/metrics/body_weight").text
    assert "calculated without the readings you marked" in detail
    client.cookies.set("anamna_lang", "uk")
    assert "Застосовано" in client.get("/devices/exclusions").text
    client.cookies.set("anamna_lang", "en")

    with connect(settings) as db:
        rule = db.execute("SELECT id FROM device_exclusions").fetchone()[0]
    undone = client.post(f"/devices/exclusions/{rule}/undo", data={"csrf_token": csrf(settings, client)},
                         follow_redirects=False)
    assert undone.status_code == 303 and "status=undone" in undone.headers["location"]
    assert value(settings, "body_weight", "2026-04-27") == 109.87


def test_a_viewer_of_a_shared_record_cannot_exclude(tmp_path, monkeypatch):
    settings, owner_id, _client = linked_with_body(tmp_path, monkeypatch)
    viewer_id = create_user(settings, "viewer@example.test", "Viewer", PASSWORD)
    with connect(settings) as db:
        owner_email = db.execute("SELECT email FROM users WHERE id=?", (owner_id,)).fetchone()[0]
        db.execute("INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at) VALUES ('s1', ?, ?, ?, ?)",
                   (owner_id, "viewer@example.test", viewer_id, utc_now()))
    viewer = TestClient(create_app(settings))
    token, _ = create_session(settings, viewer_id)
    viewer.cookies.set("anamna_session", token)
    viewer.cookies.set("anamna_lang", "en")
    viewer.cookies.set("anamna_record", owner_id)
    page_html = viewer.get("/devices/metrics/body_weight").text
    assert "/devices/readings?" not in page_html
    assert viewer.get(web._review_url("body_weight", "2026-04-27", SCALE_LABEL)).status_code == 403
    form = {"scope": "reading", "origin_provider": "apple", "origin_source": "Connect",
            "origin_device": "iPhone16,2", "from_utc": HIS, "csrf_token": csrf(settings, viewer)}
    assert viewer.post("/devices/exclusions", data=form, follow_redirects=False).status_code == 403
    # Without the viewing cookie the viewer acts on their own record, where
    # that source wrote nothing.
    viewer.cookies.delete("anamna_record")
    assert viewer.post("/devices/exclusions", data=form, follow_redirects=False).status_code == 400
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_exclusions").fetchone()[0] == 0
    # The person a reading belongs to is chosen among people sharing a record.
    with connect(settings) as db:
        assert [row["id"] for row in exclusions.connected_people(db, owner_id)] == [viewer_id]
    assert owner_email
