"""Provider event queue: a poisoned delivery is set aside after a few tries,
one account's failure cannot hold up the others, processed deliveries are
pruned, and a failing personal account cannot stop the scheduler's pass."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anamna import garmin, garmin_personal, integrations, oura
from anamna.db import connect, migrate, utc_now
from anamna.security import create_user

from test_web_panels import PASSWORD, build, settings_for


def future() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def insert_event(settings, provider: str, payload: str, processed_at: str | None) -> int:
    with connect(settings) as db:
        cursor = db.execute(
            "INSERT INTO provider_events(provider, payload, received_at, processed_at) VALUES (?, ?, ?, ?)",
            (provider, payload, utc_now(), processed_at),
        )
        return int(cursor.lastrowid)


def event_row(settings, row_id: int):
    with connect(settings) as db:
        return db.execute("SELECT * FROM provider_events WHERE id=?", (row_id,)).fetchone()


def test_migration_adds_the_attempt_columns(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(provider_events)")}
    assert {"attempts", "last_error"} <= columns


def test_a_poisoned_garmin_delivery_is_set_aside_and_the_queue_runs_on(tmp_path: Path, monkeypatch):
    settings, first_user, _ = build(tmp_path)
    second_user = create_user(settings, "second@example.test", "Second", PASSWORD)
    for user_id, external in ((first_user, "garmin-poison"), (second_user, "garmin-fine")):
        integrations.save_connection(settings, user_id, "garmin", access_token="a", refresh_token="r",
                                     expires_at=future(), external_user_id=external, scopes="HEALTH_EXPORT")
    poison = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-poison"}]}), None)
    fine = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-fine"}]}), None)
    calls: list[str] = []

    def process(settings_, payload, connections, received_at=""):
        user = payload["dailies"][0]["userId"]
        calls.append(user)
        if user == "garmin-poison":
            raise ValueError("boom with secret")
        return set()

    monkeypatch.setattr(garmin, "process_event", process)
    assert garmin.process_pending(settings) == 1
    assert event_row(settings, fine)["processed_at"] is not None
    poisoned = event_row(settings, poison)
    assert (poisoned["attempts"], poisoned["last_error"], poisoned["processed_at"]) == (1, "ValueError", None)
    for _ in range(garmin.MAX_EVENT_ATTEMPTS - 1):
        garmin.process_pending(settings)
    poisoned = event_row(settings, poison)
    assert poisoned["attempts"] == garmin.MAX_EVENT_ATTEMPTS
    assert poisoned["processed_at"] is not None
    calls.clear()
    garmin.process_pending(settings)
    assert calls == []  # set aside: not picked up again


def test_a_garmin_provider_outage_is_not_set_aside_at_the_code_limit(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    integrations.save_connection(settings, user_id, "garmin", access_token="a", refresh_token="r",
                                 expires_at=future(), external_user_id="garmin-outage", scopes="HEALTH_EXPORT")
    outage = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-outage"}]}), None)
    calls: list[str] = []

    def process(settings_, payload, connections, received_at=""):
        calls.append("try")
        raise integrations.IntegrationError("garmin: provider unreachable")

    monkeypatch.setattr(garmin, "process_event", process)
    for _ in range(garmin.MAX_EVENT_ATTEMPTS + 1):
        garmin.process_pending(settings)
    row = event_row(settings, outage)
    assert (row["attempts"], row["last_error"], row["processed_at"]) == (
        garmin.MAX_EVENT_ATTEMPTS + 1, "IntegrationError", None)
    calls.clear()
    garmin.process_pending(settings)
    assert calls == ["try"]  # still pending: the next pass tries again


def test_a_garmin_provider_outage_is_set_aside_at_the_transient_limit(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    integrations.save_connection(settings, user_id, "garmin", access_token="a", refresh_token="r",
                                 expires_at=future(), external_user_id="garmin-outage", scopes="HEALTH_EXPORT")
    outage = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-outage"}]}), None)

    def process(settings_, payload, connections, received_at=""):
        raise integrations.IntegrationError("garmin: provider unreachable")

    monkeypatch.setattr(garmin, "process_event", process)
    monkeypatch.setattr(garmin, "MAX_TRANSIENT_ATTEMPTS", 3)
    garmin.process_pending(settings)
    garmin.process_pending(settings)
    assert event_row(settings, outage)["processed_at"] is None
    garmin.process_pending(settings)
    row = event_row(settings, outage)
    assert (row["attempts"], row["processed_at"] is not None) == (3, True)


def test_a_garmin_account_needing_reauthorization_is_not_called_again_in_the_pass(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    integrations.save_connection(settings, user_id, "garmin", access_token="a", refresh_token="r",
                                 expires_at=future(), external_user_id="garmin-revoked", scopes="HEALTH_EXPORT")
    first = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-revoked"}]}), None)
    second = insert_event(settings, "garmin", json.dumps({"dailies": [{"userId": "garmin-revoked"}]}), None)
    calls: list = []

    def process(settings_, payload, connections, received_at=""):
        calls.append(payload)
        raise integrations.ReauthorizeError("refused")

    monkeypatch.setattr(garmin, "process_event", process)
    garmin.process_pending(settings)
    assert len(calls) == 1
    assert event_row(settings, first)["attempts"] == 1
    assert (event_row(settings, second)["attempts"], event_row(settings, second)["processed_at"]) == (0, None)

    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET status='reauthorize' WHERE provider='garmin'")
    calls.clear()
    garmin.process_pending(settings)
    assert calls == []  # status says reauthorize: nothing is called and nothing counted
    assert event_row(settings, second)["attempts"] == 0


def test_processed_deliveries_are_kept():
    """Stored deliveries are the provider's original data; nothing deletes them on a timer."""
    assert not hasattr(garmin, "prune_events")
    assert not hasattr(oura, "prune_events")


def test_one_oura_accounts_failing_window_does_not_hold_up_the_others(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    other = create_user(settings, "second@example.test", "Second", PASSWORD)
    for uid, external in ((user_id, "oura-poison"), (other, "oura-fine")):
        integrations.save_connection(settings, uid, "oura", access_token="access-live", refresh_token="refresh-live",
                                     expires_at=future(), external_user_id=external, scopes="daily")
    deleted = {"event_type": "delete", "data_type": "daily_sleep", "object_id": "gone"}
    poison = insert_event(settings, "oura", json.dumps({**deleted, "user_id": "oura-poison"}), None)
    fine = insert_event(settings, "oura", json.dumps({**deleted, "user_id": "oura-fine"}), None)
    def sync(settings_, uid, slot, start, end):
        if uid == user_id:
            raise ValueError("boom with secret")

    monkeypatch.setattr(oura, "sync_range", sync)
    monkeypatch.setattr(oura, "sync_heartrate", lambda *args: None)
    monkeypatch.setattr(oura, "ensure_subscriptions", lambda settings_: None)
    assert oura.process_pending(settings) == 1
    assert event_row(settings, fine)["processed_at"] is not None
    poisoned = event_row(settings, poison)
    assert (poisoned["attempts"], poisoned["last_error"], poisoned["processed_at"]) == (1, "ValueError", None)
    for _ in range(oura.MAX_EVENT_ATTEMPTS - 1):
        oura.process_pending(settings)
    assert event_row(settings, poison)["processed_at"] is not None


def _oura_outage_event(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    integrations.save_connection(settings, user_id, "oura", access_token="access-live", refresh_token="refresh-live",
                                 expires_at=future(), external_user_id="oura-outage", scopes="daily")
    deleted = {"event_type": "delete", "data_type": "daily_sleep", "object_id": "gone", "user_id": "oura-outage"}
    event = insert_event(settings, "oura", json.dumps(deleted), None)
    monkeypatch.setattr(oura, "sync_heartrate", lambda *args: None)
    monkeypatch.setattr(oura, "ensure_subscriptions", lambda settings_: None)
    return settings, event


def test_an_oura_provider_outage_is_not_set_aside_at_the_code_limit(tmp_path: Path, monkeypatch):
    settings, outage = _oura_outage_event(tmp_path, monkeypatch)
    calls: list = []

    def sync(settings_, uid, slot, start, end):
        calls.append(slot)
        raise integrations.IntegrationError("oura: provider unreachable")

    monkeypatch.setattr(oura, "sync_range", sync)
    for _ in range(oura.MAX_EVENT_ATTEMPTS + 1):
        oura.process_pending(settings)
    row = event_row(settings, outage)
    assert (row["attempts"], row["last_error"], row["processed_at"]) == (
        oura.MAX_EVENT_ATTEMPTS + 1, "IntegrationError", None)
    calls.clear()
    oura.process_pending(settings)
    assert calls  # still pending: the next pass syncs the window again


def test_an_oura_provider_outage_is_set_aside_at_the_transient_limit(tmp_path: Path, monkeypatch):
    settings, outage = _oura_outage_event(tmp_path, monkeypatch)

    def sync(settings_, uid, slot, start, end):
        raise integrations.IntegrationError("oura: provider unreachable")

    monkeypatch.setattr(oura, "sync_range", sync)
    monkeypatch.setattr(oura, "MAX_TRANSIENT_ATTEMPTS", 3)
    oura.process_pending(settings)
    oura.process_pending(settings)
    assert event_row(settings, outage)["processed_at"] is None
    oura.process_pending(settings)
    row = event_row(settings, outage)
    assert (row["attempts"], row["processed_at"] is not None) == (3, True)


def test_an_oura_code_failure_is_set_aside_at_the_code_limit(tmp_path: Path, monkeypatch):
    settings, outage = _oura_outage_event(tmp_path, monkeypatch)

    def sync(settings_, uid, slot, start, end):
        raise ValueError("boom with secret")

    monkeypatch.setattr(oura, "sync_range", sync)
    for _ in range(oura.MAX_EVENT_ATTEMPTS):
        oura.process_pending(settings)
    row = event_row(settings, outage)
    assert (row["attempts"], row["last_error"], row["processed_at"] is not None) == (
        oura.MAX_EVENT_ATTEMPTS, "ValueError", True)


def test_an_oura_account_needing_reauthorization_is_held_without_counting(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    integrations.save_connection(settings, user_id, "oura", access_token="access-live", refresh_token="refresh-live",
                                 expires_at=future(), external_user_id="oura-revoked", scopes="daily")
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET status='reauthorize' WHERE provider='oura'")
    event = insert_event(settings, "oura", json.dumps({"event_type": "delete", "data_type": "daily_sleep",
                                                       "object_id": "gone", "user_id": "oura-revoked"}), None)
    calls: list = []
    monkeypatch.setattr(oura, "sync_range", lambda *args: calls.append(args))
    monkeypatch.setattr(oura, "sync_heartrate", lambda *args: None)
    monkeypatch.setattr(oura, "ensure_subscriptions", lambda settings_: None)
    assert oura.process_pending(settings) == 0
    assert calls == []
    assert (event_row(settings, event)["attempts"], event_row(settings, event)["processed_at"]) == (0, None)


def _two_personal_accounts(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    other = create_user(settings, "second@example.test", "Second", PASSWORD)
    for uid, guid in ((user_id, "guid-a"), (other, "guid-b")):
        integrations.save_connection(settings, uid, garmin_personal.PROVIDER_KEY, access_token="jwt",
                                     refresh_token="key", expires_at=future(), external_user_id=guid, scopes="")
    monkeypatch.setattr(garmin_personal, "enabled", lambda settings_: True)
    return settings, user_id, other


def test_a_failing_personal_account_does_not_stop_the_scheduler_pass(tmp_path: Path, monkeypatch):
    settings, user_id, other = _two_personal_accounts(tmp_path, monkeypatch)
    calls: list[str] = []

    def connect_run(settings_, uid):
        if uid == user_id:
            raise RuntimeError("boom with secret")
        calls.append(uid)

    monkeypatch.setattr(garmin_personal, "_connect_run", connect_run)
    assert garmin_personal.sync_due(settings) == 1
    assert calls == [other]


def test_a_scheduled_personal_sync_skips_an_account_whose_sync_is_in_flight(tmp_path: Path, monkeypatch):
    settings, user_id, other = _two_personal_accounts(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(garmin_personal, "_connect_run", lambda settings_, uid: calls.append(uid))
    assert garmin.claim(f"garmin-personal-{other}")
    try:
        assert garmin_personal.sync_due(settings) == 1
    finally:
        garmin.release(f"garmin-personal-{other}")
    assert calls == [user_id]
