"""Exact Svix bytes, durable retries and locally linked tenant boundaries."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from anamna import openwearables as ow
from anamna import openwearables_archive as archive
from anamna import openwearables_webhooks as hooks
from anamna.db import connect, migrate, utc_now
from anamna.security import create_user
from anamna.web.openwearables_routes import register_routes
from test_openwearables import BASE, REMOTE, OTHER_REMOTE, configure, link
from test_openwearables import seed_import, seed_day
from test_web_panels import settings_for

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
OLD_SECRET = "whsec_" + base64.b64encode(b"b" * 32).decode()


@pytest.fixture
def linked_record(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", "local-fixture-password")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES (?,?,?,?)", ("patient-one", owner, "owner", utc_now()))
    configure(settings)
    link(settings, owner)
    with connect(settings) as db:
        db.execute("""INSERT INTO openwearables_subscriptions(id,server_url,endpoint_id,callback_url,secret,status,created_at,updated_at)
            VALUES ('receiver',?,'ep_one','https://ledger.example/webhooks/openwearables/receiver',?,'active',?,?)""", (BASE, SECRET, utc_now(), utc_now()))
    return settings, owner


def archived(settings, owner=None, remote=REMOTE):
    """Every archived sample payload, through the archive's one reader."""
    with connect(settings) as db:
        owners = [owner] if owner else [r[0] for r in db.execute("SELECT id FROM users")]
        return [s for o in owners for s in archive.iter_samples(db, o, BASE, remote, "2000-01-01", "2100-01-01")]


def signed(body, message_id="msg_one", secret=SECRET, now=None):
    stamp = str(int(time.time() if now is None else now))
    content = message_id.encode() + b"." + stamp.encode() + b"." + body
    signature = base64.b64encode(hmac.new(base64.b64decode(secret[6:]), content, hashlib.sha256).digest()).decode()
    return {"svix-id": message_id, "svix-timestamp": stamp, "svix-signature": "v1," + signature}


def payload(remote=REMOTE, event_type="heart_rate.created", **data):
    return json.dumps({"type": event_type, "data": {"user_id": remote, "provider": "oura",
        "series_type": "heart_rate", "sample_count": 1, "start_time": "2026-08-01T01:00:00Z", "end_time": "2026-08-01T01:00:00Z",
        "samples": [{"timestamp": "2026-08-01T01:00:00Z", "type": "heart_rate", "value": 61, "unit": "bpm",
                     "source": {"provider": "oura", "device": "ring", "source": "Oura App"}}], **data}}, ensure_ascii=False).encode()


def test_signature_raw_body_rotation_clock_and_multiple_signatures(linked_record):
    settings, owner = linked_record
    body = payload()
    headers = signed(body)
    headers["svix-signature"] = "v2,unsupported v1,wrong " + headers["svix-signature"]
    assert hooks.verify_signature(body, headers, [OLD_SECRET, SECRET]) == "msg_one"
    for wrong in (body + b" ", body.replace(b"61", b"62")):
        with pytest.raises(hooks.WebhookError, match="invalid_signature"):
            hooks.verify_signature(wrong, headers, [SECRET])
    for difference in (-301, 301):
        with pytest.raises(hooks.WebhookError, match="expired_signature"):
            hooks.verify_signature(body, signed(body, now=1000), [SECRET], now=1000 + difference)
    with connect(settings) as db:
        db.execute("UPDATE openwearables_subscriptions SET previous_secret=?,previous_secret_until=?", (OLD_SECRET, time.time() + 60))
    assert hooks.receive(settings, "receiver", body, signed(body, secret=OLD_SECRET))["ok"]
    with connect(settings) as db:
        db.execute("UPDATE openwearables_subscriptions SET previous_secret_until=0")
    with pytest.raises(hooks.WebhookError, match="invalid_signature"):
        hooks.receive(settings, "receiver", body, signed(body, secret=OLD_SECRET))


def test_receipt_replay_full_samples_and_granular_dedup(linked_record):
    settings, owner = linked_record
    body = payload()
    first = hooks.receive(settings, "receiver", body, signed(body))
    assert not first["duplicate"]
    assert hooks.receive(settings, "receiver", body, signed(body))["duplicate"]
    granular = payload(event_type="series.heart_rate.created")
    hooks.receive(settings, "receiver", granular, signed(granular, "msg_two"))
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_sync_jobs").fetchone()[0] == 1
        assert db.execute("SELECT body FROM openwearables_receipts ORDER BY id LIMIT 1").fetchone()[0] == body
    samples = archived(settings, owner)
    assert len(samples) == 1 and samples[0]["source"]["source"] == "Oura App"
    changed = payload(sample_count=2)
    with pytest.raises(hooks.WebhookError, match="message_conflict"):
        hooks.receive(settings, "receiver", changed, signed(changed))


def test_chunk_payloads_retained_and_unknown_events_visible(linked_record):
    settings, owner = linked_record
    body = payload(chunk_index=1, total_chunks=2, sample_count=3000)
    hooks.receive(settings, "receiver", body, signed(body))
    unknown = json.dumps({"type": "future.event", "data": {"user_id": REMOTE, "new_field": [1, 2]}}).encode()
    hooks.receive(settings, "receiver", unknown, signed(unknown, "future"))
    with connect(settings) as db:
        rows = db.execute("SELECT body,status FROM openwearables_receipts ORDER BY id").fetchall()
    assert rows[0]["body"] == body
    assert rows[1]["body"] == unknown and rows[1]["status"] == "unsupported"


def test_unknown_remote_and_subscription_scope_cannot_cross_owner(linked_record):
    settings, owner = linked_record
    unknown = payload(remote=OTHER_REMOTE)
    hooks.receive(settings, "receiver", unknown, signed(unknown))
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM patients").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM openwearables_raw_days").fetchone()[0] == 0
        assert db.execute("SELECT body,status FROM openwearables_receipts").fetchone()[:] == (b"", "unlinked")
        db.execute("UPDATE openwearables_subscriptions SET remote_user_id=?", (OTHER_REMOTE,))
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body, "wrong_scope"))
    assert not hooks.operational_status(settings, owner)["receipts"]


def test_unlink_relink_same_remote_cancels_old_generation(linked_record, monkeypatch):
    settings, owner = linked_record
    job = hooks.enqueue_sync(settings, [owner], start="2026-08-01", end="2026-08-01")[0]
    old = ow.account_identity(settings, owner)
    ow.unlink_account(settings, owner)
    link(settings, owner)
    assert old != ow.account_identity(settings, owner)
    with connect(settings) as db:
        assert db.execute("SELECT status FROM openwearables_sync_jobs WHERE id=?", (job,)).fetchone()[0] == "cancelled"
        with pytest.raises(ow.OpenWearablesError):
            ow._check_sync_account(db, settings, owner, old)
    ow.save_settings(settings, {"openwearables_url": "https://different.example"})
    body = payload()
    with pytest.raises(hooks.WebhookError, match="receiver_unavailable"):
        hooks.receive(settings, "receiver", body, signed(body))


def test_signed_body_ack_requires_atomic_persistence(linked_record, monkeypatch):
    settings, owner = linked_record
    body = payload()
    def fail(*args):
        raise RuntimeError("disk unavailable")
    monkeypatch.setattr(archive, "merge_samples", fail)
    with pytest.raises(RuntimeError):
        hooks.receive(settings, "receiver", body, signed(body))
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_receipts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM openwearables_sync_jobs").fetchone()[0] == 0


def test_retry_restart_lease_and_completion(linked_record, monkeypatch):
    settings, owner = linked_record
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body))
    monkeypatch.setattr(ow, "_sync_window", lambda *args: ({}, {"sleep": "http_503"}))
    monkeypatch.setattr(hooks, "sync_raw_timeseries", lambda *args: 3)
    assert hooks.process_one(settings, now=time.time() + 20)
    with connect(settings) as db:
        row = db.execute("SELECT * FROM openwearables_sync_jobs").fetchone()
        assert row["status"] == "retry" and row["attempts"] == 1
        assert db.execute("SELECT status FROM openwearables_receipts").fetchone()[0] == "queued"
        # Simulate a process dying after claiming the retry.
        db.execute("UPDATE openwearables_sync_jobs SET status='running',lease_until=1,lease_token='dead'")
    ow.reset_module_state()
    monkeypatch.setattr(ow, "_sync_window", lambda *args: ({"sleep": 2}, {}))
    assert hooks.process_one(settings)
    with connect(settings) as db:
        assert db.execute("SELECT status FROM openwearables_sync_jobs").fetchone()[0] == "complete"
        assert db.execute("SELECT status FROM openwearables_receipts").fetchone()[0] == "complete"


def test_arrivals_during_running_job_get_followup(linked_record, monkeypatch):
    settings, owner = linked_record
    hooks.enqueue_sync(settings, [owner], start="2026-08-01", end="2026-08-01")
    def arrival(*args):
        body = payload()
        hooks.receive(settings, "receiver", body, signed(body))
        return {}, {}
    monkeypatch.setattr(ow, "_sync_window", arrival)
    monkeypatch.setattr(hooks, "sync_raw_timeseries", lambda *args: 0)
    hooks.process_one(settings)
    with connect(settings) as db:
        assert [r[0] for r in db.execute("SELECT status FROM openwearables_sync_jobs ORDER BY created_at,id")] .count("queued") == 1
        assert db.execute("SELECT status FROM openwearables_receipts").fetchone()[0] == "queued"


def test_scheduled_all_user_and_selected_user_jobs_are_independent(linked_record):
    settings, owner = linked_record
    other = create_user(settings, "partner@example.com", "Olena", "local-fixture-password")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES (?,?,?,?)", ("patient-two", other, "Olena", utc_now()))
    ow.link_account(settings, other, OTHER_REMOTE, "partner@example.com")
    assert len(hooks.enqueue_sync(settings, [other])) == 1
    assert hooks.schedule_due(settings, now=1000) == 2
    assert hooks.schedule_due(settings, now=1001) == 0
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_sync_jobs WHERE reason='backfill'").fetchone()[0] == 2
    own = hooks.operational_status(settings, owner)
    assert all(job["owner_user_id"] == owner for job in own["jobs"])
    assert own["subscriptions"] == []


@pytest.mark.parametrize("status", ["queued", "running", "retry", "attention"])
def test_monthly_schedule_preserves_unfinished_history_progress(linked_record, status):
    settings, owner = linked_record
    hooks.schedule_due(settings, now=1000)
    with connect(settings) as db:
        db.execute("UPDATE openwearables_sync_jobs SET next_day='2020-01-01',status=? WHERE reason='backfill'", (status,))
    hooks.schedule_due(settings, now=1000 + 31 * 86400)
    with connect(settings) as db:
        history = db.execute("SELECT next_day,status FROM openwearables_sync_jobs WHERE reason='backfill'").fetchall()
        assert len(history) == 1
        assert tuple(history[0]) == ("2020-01-01", status)


def test_history_yields_to_recent_and_other_account_between_chunks(linked_record, monkeypatch):
    settings, owner = linked_record
    other = create_user(settings, "second@example.test", "Second", "local-fixture-password")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES (?,?,?,?)", ("patient-fairness", other, "Second", utc_now()))
    ow.link_account(settings, other, OTHER_REMOTE, "second@example.test")
    history = hooks.enqueue_sync(settings, [owner], backfill=True)[0]
    clock = [time.time() + 1]
    monkeypatch.setattr(hooks.time, "time", lambda: clock[0])
    visited = []
    def capture(_settings, user_id, start, end, expected):
        visited.append((user_id, start))
        return {}, {}
    monkeypatch.setattr(ow, "_sync_window", capture)
    monkeypatch.setattr(hooks, "sync_raw_timeseries", lambda *args: 0)
    assert hooks.process_one(settings)
    hooks.enqueue_sync(settings, [owner, other], start="2026-08-06", end="2026-08-07")
    for _ in range(2):
        clock[0] += 3
        assert hooks.process_one(settings)
    assert visited[0] == (owner, ow.EPOCH_DAY)
    assert set(visited[1:]) == {(owner, "2026-08-06"), (other, "2026-08-06")}
    with connect(settings) as db:
        row = db.execute("SELECT status,next_day FROM openwearables_sync_jobs WHERE id=?", (history,)).fetchone()
        assert tuple(row) == ("queued", "2015-01-08")


def test_management_uses_api_key_json_crud_and_retains_rotating_secret(linked_record, monkeypatch):
    settings, owner = linked_record
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["headers"]["X-Open-Wearables-API-Key"] == "ow-api-key"
        if url.endswith("/secret"):
            return {"key": OLD_SECRET}
        if kwargs.get("method") == "PATCH":
            return {"id": "ep_one"}
        if url.endswith("/test"):
            return {"message_id": "msg_test"}
        if kwargs.get("method") == "DELETE":
            return None
        raise AssertionError(url)
    monkeypatch.setattr(ow, "_request", request)
    hooks.save_subscription(settings, "https://ledger.example", receiver_id="receiver", filter_types=["sleep.created"])
    assert calls[0][1]["data"]["user_id"] is None
    assert calls[0][1]["data"]["filter_types"] == ["sleep.created"]
    with connect(settings) as db:
        sub = db.execute("SELECT * FROM openwearables_subscriptions").fetchone()
    assert sub["secret"] == OLD_SECRET and sub["previous_secret"] == SECRET
    assert SECRET not in json.dumps(hooks.operational_status(settings))
    hooks.test_subscription(settings, "receiver")
    hooks.delete_subscription(settings, "receiver")
    assert hooks.operational_status(settings)["subscriptions"][0]["status"] == "disabled"


def test_receiver_stream_limit_and_unauthenticated_signature_route(linked_record):
    settings, owner = linked_record
    app = FastAPI()
    register_routes(app, settings, lambda request: (_ for _ in ()).throw(AssertionError("receiver must not require session")), lambda *args: None)
    client = TestClient(app)
    body = payload()
    assert client.post("/webhooks/openwearables/receiver", content=body, headers=signed(body)).status_code == 202
    assert client.post("/webhooks/openwearables/receiver", content=body).status_code == 401
    assert client.post("/webhooks/openwearables/receiver", content=b"x" * (hooks.MAX_BODY_BYTES + 1)).status_code == 413


def test_raw_pull_keeps_fractional_samples_and_failed_pagination_keeps_previous(linked_record, monkeypatch):
    settings, owner = linked_record
    rows = [json.loads(payload())["data"]["samples"][0]]
    rows[0]["timestamp"] = "2026-08-01T23:59:59.999Z"
    def api(settings, path, params):
        assert "types" not in params  # Preserve every series, including unfamiliar types.
        assert params["end_time"] == "2026-08-01T23:59:59.999999Z"
        return {"data": rows, "pagination": {"has_more": False}}
    monkeypatch.setattr(ow, "_api", api)
    assert hooks.sync_raw_timeseries(settings, owner, "2026-08-01", "2026-08-01") == 1
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": [], "pagination": {"has_more": True, "next_cursor": "same"}})
    with pytest.raises(ow.OpenWearablesError):
        hooks.sync_raw_timeseries(settings, owner, "2026-08-01", "2026-08-01")
    assert hooks.operational_status(settings)["raw_sample_count"] == 1


def test_documented_hrv_methods_stay_distinct():
    bucket = {}
    ow._map_sleep([{"date": "2026-08-01", "avg_hrv_sdnn_ms": 33, "avg_hrv_rmssd_ms": 44,
                    "source": {"provider": "oura"}}], bucket)
    assert {item.definition.key: item.value for item in bucket.values()} == {
        "heart_rate_variability": 33, "heart_rate_variability_rmssd": 44}


def test_extra_raw_metrics_totals_fractional_units_and_sources(linked_record, monkeypatch):
    settings, owner = linked_record
    source = {"provider": "apple", "device": "Apple Watch", "source": "Health"}
    samples = [
        {"type": "distance_cycling", "timestamp": "2026-08-01T10:00:00Z", "value": 2000, "unit": "m", "source": source, "is_daily_total": False},
        {"type": "distance_cycling", "timestamp": "2026-08-01T11:00:00Z", "value": 5000, "unit": "m", "source": source, "is_daily_total": True},
        {"type": "distance_cycling", "timestamp": "2026-08-01T12:00:00Z", "value": 6500, "unit": "m", "source": source, "is_daily_total": True},
        {"type": "blood_pressure_systolic", "timestamp": "2026-08-01T20:59:59.999Z", "value": 120, "unit": "mmHg", "source": {"provider": "garmin", "device": "Index BPM"}},
    ]
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": samples, "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        values = {r["metric_key"]: dict(r) for r in db.execute("SELECT * FROM device_metric_days")}
    assert values["cycling_distance"]["value"] == 6.5
    assert values["cycling_distance"]["sample_count"] == 1
    assert values["systolic_blood_pressure"]["value"] == 120
    assert "garmin" in values["systolic_blood_pressure"]["source_name"]
    assert hooks.operational_status(settings)["raw_sample_count"] == 4


def test_full_boundary_does_not_skip_same_timestamp_or_fractional_samples(linked_record, monkeypatch):
    settings, owner = linked_record
    rows = [{"timestamp": "2026-08-01T10:00:00.123Z", "type": "heart_rate", "value": 60, "unit": "bpm"}]
    monkeypatch.setattr(ow, "_PAGE_LIMIT", 1)
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": rows, "pagination": {"has_more": False}})
    with pytest.raises(ow.OpenWearablesError, match="boundary"):
        hooks.sync_raw_timeseries(settings, owner, "2026-08-01", "2026-08-01")
    assert hooks.operational_status(settings)["raw_sample_count"] == 0


def test_delete_last_owner_erases_receipt_bytes_and_samples(linked_record):
    settings, owner = linked_record
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body))
    with connect(settings) as db:
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert db.execute("SELECT body FROM openwearables_receipts").fetchone()[0] == b""
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM openwearables_raw_days").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_replacing_remote_account_erases_previous_raw_medical_data(linked_record):
    settings, owner = linked_record
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body))
    ow.link_account(settings, owner, OTHER_REMOTE, "other@example.test")
    with connect(settings) as db:
        assert db.execute("SELECT body FROM openwearables_receipts").fetchone()[0] == b""
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM openwearables_raw_days").fetchone()[0] == 0


def test_persist_original_raw_even_when_unit_mapping_fails(linked_record, monkeypatch):
    settings, owner = linked_record
    rows = [{"timestamp": "2026-08-01T10:00:00Z", "type": "blood_pressure_systolic", "value": 120, "unit": "unexpected-unit"}]
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": rows, "pagination": {"has_more": False}})
    with pytest.raises(ow.OpenWearablesError):
        hooks.sync_raw_timeseries(settings, owner, "2026-08-01", "2026-08-01")
    assert archived(settings, owner) == [rows[0]]
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM device_metric_days").fetchone()[0] == 0


def test_resting_hr_from_raw_when_recovery_summary_has_no_provider(linked_record, monkeypatch):
    settings, owner = linked_record
    def api(settings, path, params):
        assert params.get("end_time", params.get("end_date")) in {"2026-08-02", "2026-08-01T23:59:59.999999Z"}
        rows = [] if "summaries" in path else [{"timestamp": "2026-08-01T10:00:00Z", "type": "resting_heart_rate", "value": 53,
            "unit": "bpm", "source": {"provider": "apple", "device": "Apple Watch"}}]
        return {"data": rows, "pagination": {"has_more": False}}
    monkeypatch.setattr(ow, "_api", api)
    ow.sync_datatype(settings, owner, "recovery", "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        row = db.execute("SELECT * FROM device_metric_days WHERE metric_key='resting_heart_rate'").fetchone()
    assert row["value"] == 53 and "apple" in row["source_name"]


def test_oura_hrv_migration_is_adapter_scoped_and_preserves_values(linked_record):
    from pathlib import Path
    settings, owner = linked_record
    for import_id, adapter in (("oura-file", "oura"), ("oura-api", "oura_api"), ("healthkit-oura", "apple_health")):
        seed_import(settings, owner, import_id, adapter)
        seed_day(settings, owner, import_id, "Oura " + import_id, "heart_rate_variability", "2026-08-01", 44,
                 unit="ms", aggregation="average", name="Heart rate variability (SDNN)")
    # Destination collision must retain the older value, not drop either row.
    seed_day(settings, owner, "oura-file", "Oura oura-file", "heart_rate_variability_rmssd", "2026-08-01", 45,
             unit="ms", aggregation="average", name="Heart rate variability (RMSSD)")
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET source_vendor='Oura'")
        before = {r["id"]: r["value"] for r in db.execute("SELECT id,value FROM device_metric_days")}
        db.executescript(Path("migrations/030_oura_hrv_method.sql").read_text(encoding="utf-8"))
        after = {r["id"]: r["value"] for r in db.execute("SELECT id,value FROM device_metric_days")}
        assert before == after
        healthkit = db.execute("SELECT metric_key,metric_name FROM device_metric_days WHERE import_id='healthkit-oura'").fetchone()
        assert tuple(healthkit) == ("heart_rate_variability", "Heart rate variability (SDNN)")
        assert db.execute("SELECT count(*) FROM device_metric_days WHERE metric_key='heart_rate_variability_rmssd'").fetchone()[0] == 3
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_cleanup_upgrade_handles_pretrigger_installations(linked_record):
    from pathlib import Path
    settings, owner = linked_record
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body))
    with connect(settings) as db:
        db.execute("DROP TRIGGER ow_receipt_last_owner_deleted")
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert db.execute("SELECT body FROM openwearables_receipts").fetchone()[0] == body
        db.executescript(Path("migrations/031_openwearables_receipt_owner_cleanup.sql").read_text(encoding="utf-8"))
        assert db.execute("SELECT body FROM openwearables_receipts").fetchone()[0] == b""
        assert db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='ow_receipt_last_owner_deleted'").fetchone()


def test_deployed_units_and_complete_daily_query_edges(linked_record, monkeypatch):
    settings, owner = linked_record
    bucket = {}
    ow._map_body_series([
        {"type":"body_fat_percentage","timestamp":"2026-08-07T23:59:59.999Z","value":20,"unit":"percent"},
        {"type":"body_mass_index","timestamp":"2026-08-07T01:00:00Z","value":22,"unit":"kg_m2"},
        {"type":"vo2_max","timestamp":"2026-08-07T01:00:00Z","value":42,"unit":"ml_kg_min"}], bucket)
    assert {a.definition.unit for a in bucket.values()} == {"%", "kg/m²", "mL/kg/min"}
    extra = {}
    ow.map_raw_metrics([{"type":"walking_speed","timestamp":"2026-08-07T01:00:00Z","value":1,"unit":"m_per_s"}],extra)
    assert next(iter(extra.values())).value == pytest.approx(3.6)
    def api(settings,path,params):
        # Scores are dated from a timestamp, so their fetch reaches back one
        # day for the first local day's early hours (the previous UTC day).
        assert params["start_date"] == ("2026-08-06" if "summaries" in path else "2026-08-05")
        assert params["end_date"] == "2026-08-08"
        if "summaries" in path:
            data=[{"date":"2026-08-06","steps":1},{"date":"2026-08-07","steps":2},{"date":"2026-08-08","steps":3}]
        else:
            # The edges of 2026-08-07 in the person's zone (Kyiv, UTC+3).
            data=[{"recorded_at":"2026-08-07T20:59:59.999Z","category":"sleep","value":80},
                  {"recorded_at":"2026-08-07T21:00:00Z","category":"sleep","value":90}]
        return {"data":data,"pagination":{"has_more":False}}
    monkeypatch.setattr(ow,"_api",api)
    assert len(ow._fetch(settings,REMOTE,"activity","2026-08-06","2026-08-07")) == 2
    assert len(ow._fetch(settings,REMOTE,"scores","2026-08-06","2026-08-07")) == 1


def test_management_bearer_is_explicit_path_and_server_scoped(linked_record, monkeypatch):
    settings, owner = linked_record
    monkeypatch.setenv("ANAMNA_OPENWEARABLES_WEBHOOK_TOKEN", "private-developer-token")
    calls=[]
    def request(url,**kwargs):
        calls.append((url,kwargs))
        return []
    monkeypatch.setattr(ow,"_request",request)
    hooks.management_api(settings,"/webhooks/endpoints")
    assert calls[-1][1]["headers"] == {"Authorization":"Bearer private-developer-token"}
    ow._api(settings,"/users")
    assert calls[-1][1]["headers"] == {"X-Open-Wearables-API-Key":"ow-api-key"}
    with pytest.raises(hooks.WebhookError,match="invalid_management_path"):
        hooks.management_api(settings,"/users")
    ow.save_settings(settings,{"openwearables_url":"https://different.example"})
    with pytest.raises(hooks.WebhookError,match="server_changed"):
        hooks.management_api(settings,"/webhooks/endpoints")


def test_expired_job_lease_cannot_overwrite_current_measurements(linked_record):
    settings, owner = linked_record
    job=hooks.enqueue_sync(settings,[owner],start="2026-08-01",end="2026-08-01")[0]
    expected=(*ow.account_identity(settings,owner),job,"stale-token")
    with connect(settings) as db:
        db.execute("UPDATE openwearables_sync_jobs SET status='running',lease_token='replacement-token',lease_until=? WHERE id=?",(time.time()+180,job))
        with pytest.raises(ow.OpenWearablesError,match="lease expired"):
            ow._check_sync_account(db,settings,owner,expected)
