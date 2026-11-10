"""Audit regressions: non-ASCII secrets and signatures, an oversized poll update,
the labsync run heartbeat and the record-change hook."""
from __future__ import annotations

import base64
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from anamna import labsync
from anamna import openwearables_webhooks as hooks
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.security import create_user
from anamna.telegram import TelegramService
from anamna.web.app import create_app
from test_web_panels import PASSWORD, settings_for

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()


class FakeAPI:
    def __init__(self):
        self.updates = []

    def call(self, method, payload=None, **kwargs):
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return result
        return True


@pytest.fixture
def telegram_ledger(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "ledger.sqlite3", tmp_path / "sources", "telegram-audit")
    settings.source_dir.mkdir()
    migrate(settings)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET enabled=1,bot_username='LedgerTestBot' WHERE id=1")
    monkeypatch.setenv("ANAMNA_BACKGROUND_WORKERS", "0")
    monkeypatch.setenv("ANAMNA_TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvxyz")
    return settings


def incoming(uid, text="/menu", chat=101):
    return {"update_id": uid, "message": {"message_id": uid, "from": {"id": chat, "language_code": "en"}, "chat": {"id": chat, "type": "private"}, "text": text}}


def test_webhook_non_ascii_secret_header_is_refused_not_a_server_error(telegram_ledger, monkeypatch):
    settings = telegram_ledger
    monkeypatch.setenv("ANAMNA_TELEGRAM_WEBHOOK_SECRET", "synthetic-webhook-secret-" + "x" * 24)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET mode='webhook'")
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    # Raw UTF-8 bytes on the wire: Starlette decodes them as latin-1, so the handler sees non-ASCII text.
    response = client.post("/api/telegram/webhook", headers={b"X-Telegram-Bot-Api-Secret-Token": "é".encode("utf-8")}, json=incoming(123))
    assert response.status_code == 403
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0] == 0


def test_poll_skips_an_oversized_update_and_advances_past_it(telegram_ledger):
    settings = telegram_ledger
    api = FakeAPI()
    service = TelegramService(settings, api_factory=lambda token: api)
    api.updates = [incoming(10, "x" * 270000), incoming(11)]
    assert service._poll(service.config()) == 2
    assert service.config()["poll_offset"] == 12
    with connect(settings) as db:
        assert [row[0] for row in db.execute("SELECT update_id FROM telegram_updates ORDER BY update_id")] == [11]


def test_signature_with_non_ascii_value_is_refused_not_a_crash():
    body = b'{"type":"heart_rate.created"}'
    headers = {"svix-id": "msg_one", "svix-timestamp": str(int(time.time())), "svix-signature": "v1,é"}
    with pytest.raises(hooks.WebhookError) as caught:
        hooks.verify_signature(body, headers, [SECRET])
    assert caught.value.code == "invalid_signature" and caught.value.status == 401


def test_progress_heartbeat_keeps_a_long_run_from_looking_abandoned(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "lab-heartbeat@example.test", "Lab", PASSWORD)
    an_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="seconds")
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO lab_accounts(user_id, provider, sync_state, sync_started_at, updated_at) VALUES (?, 'esculab', 'running', ?, ?)",
            (user_id, an_hour_ago, utc_now()),
        )
    labsync._progress(settings, user_id, "esculab", {"orders": 1}, {"order_id": "9001"})
    with connect(settings) as connection:
        started = connection.execute(
            "SELECT sync_started_at FROM lab_accounts WHERE user_id=? AND provider='esculab'", (user_id,)).fetchone()[0]
    assert abs((datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds()) < 5
    assert not labsync._claim_run(settings, user_id, "esculab")


def test_record_change_listeners_are_notified_and_a_failing_one_is_contained():
    seen = []

    def broken(owner):
        raise RuntimeError("listener broke")

    def record(owner):
        seen.append(owner)

    labsync.on_record_change(broken)
    labsync.on_record_change(record)
    try:
        labsync._notify_record_changed("u1")
        assert seen == ["u1"]
    finally:
        for callback in (broken, record):
            if callback in labsync._record_changed:
                labsync._record_changed.remove(callback)
