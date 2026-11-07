"""Synthetic Telegram API harness: no credentials or network are needed."""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.security import create_user
from anamna.telegram import TelegramService
from anamna.telegram_transport import TelegramError, TelegramAPI, MAX_FILE_BYTES


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.files = {}
        self.error = None
        self.updates = []

    def call(self, method, payload=None, **kwargs):
        self.calls.append((method, payload, kwargs))
        if self.error:
            error, self.error = self.error, None
            raise error
        if method == "getMe":
            return {"is_bot": True, "username": "LedgerTestBot"}
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return result
        if method == "getWebhookInfo":
            return {"url": "https://health.example.com/api/telegram/webhook", "pending_update_count": 0}
        return True

    def download(self, file_id):
        return self.files[file_id]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "ledger.sqlite3", tmp_path / "sources", "telegram-fixture")
    settings.source_dir.mkdir()
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", "telegram-test-password")
    other = create_user(settings, "partner@example.com", "Olena", "telegram-test-password")
    with connect(settings) as db:
        for uid in (owner, other):
            db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES(?,?,?,?)", (uid, uid, "Synthetic patient", utc_now()))
        db.execute("UPDATE telegram_config SET enabled=1,bot_username='LedgerTestBot' WHERE id=1")
    api = FakeAPI()
    service = TelegramService(settings, api_factory=lambda token: api)
    monkeypatch.setattr("anamna.ingest.intake.start_worker", lambda settings: None)
    # Batches are acknowledged once files stop arriving; the harness does not wait.
    monkeypatch.setattr("anamna.telegram.BATCH_QUIET", 0)
    monkeypatch.setenv("ANAMNA_TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvxyz")
    return settings, owner, other, api, service


def incoming(uid, text="/menu", chat=101, **extra):
    return {"update_id": uid, "message": {"message_id": uid, "from": {"id": chat, "language_code": "en"}, "chat": {"id": chat, "type": "private"}, "text": text, **extra}}


def callback(uid, data, chat=101):
    return {"update_id": uid, "callback_query": {"id": str(uid), "from": {"id": chat}, "data": data, "message": {"message_id": 1, "chat": {"id": chat, "type": "private"}}}}


def link(service, owner, uid=1, chat=101):
    url = service.create_link(owner)
    token = parse_qs(urlsplit(url).query)["start"][0]
    service.receive(incoming(uid, "/start " + token, chat))
    service.process_one()
    return token


def outputs(settings):
    with connect(settings) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM telegram_outbox ORDER BY created_at,id")]


def document(settings, owner, ident="doc-1", title="Synthetic <report>"):
    path = settings.source_dir / (ident + ".pdf")
    data = b"%PDF-1.4 synthetic fixture"
    path.write_bytes(data)
    with connect(settings) as db:
        db.execute("""INSERT INTO documents(id,owner_user_id,patient_id,original_filename,source_path,mime_type,byte_size,sha256,page_count,title,clinical_type,extraction_strategy,report_date,imported_at)
            VALUES(?,?,?,?,?,'application/pdf',?,?,1,?,'laboratory','native_text','2026-09-01',?)""", (ident, owner, owner, ident + ".pdf", str(path), len(data), hashlib.sha256(data).hexdigest(), title, utc_now()))
    return data


def test_link_hash_expiry_single_use_replay_and_disconnect(ledger):
    settings, owner, other, api, service = ledger
    first = parse_qs(urlsplit(service.create_link(owner)).query)["start"][0]
    second = parse_qs(urlsplit(service.create_link(owner)).query)["start"][0]
    with connect(settings) as db:
        stored = db.execute("SELECT token_hash FROM telegram_link_tokens").fetchall()
    assert len(stored) == 1 and stored[0][0] == hashlib.sha256(second.encode()).hexdigest()
    assert first not in str(stored) and second not in str(stored)
    service.receive(incoming(1, "/start " + first))
    service.process_one()
    assert not service.profile(owner)["linked"]
    update = incoming(2, "/start " + second)
    assert service.receive(update)
    assert not service.receive(update)
    service.process_one()
    assert service.profile(owner)["linked"]
    service.receive(incoming(3, "/start " + second, chat=202))
    service.process_one()
    assert not service.profile(other)["linked"]
    service.unlink(owner)
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_link_tokens").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE owner_user_id=?", (owner,)).fetchone()[0] == 0
        assert all(row[0] == "{}" for row in db.execute("SELECT payload FROM telegram_updates"))


def test_expired_token_and_group_never_links_or_discloses(ledger):
    settings, owner, _, _, service = ledger
    token = parse_qs(urlsplit(service.create_link(owner)).query)["start"][0]
    with connect(settings) as db:
        db.execute("UPDATE telegram_link_tokens SET expires_at=0")
    service.receive(incoming(1, "/start " + token))
    service.process_one()
    assert not service.profile(owner)["linked"]
    group = incoming(2, "/start " + token)
    group["message"]["chat"]["type"] = "supergroup"
    service.receive(group)
    service.process_one()
    assert len(outputs(settings)) == 1


def test_menus_search_html_and_ownership_original_is_explicit(ledger):
    settings, owner, other, api, service = ledger
    link(service, owner)
    document(settings, owner)
    document(settings, other, "foreign-doc", "PRIVATE FOREIGN")
    service.receive(callback(2, "docs:0"))
    service.process_one()
    text = outputs(settings)[-1]["text"]
    assert "Synthetic &lt;report&gt;" in text and "PRIVATE FOREIGN" not in text
    service.receive(callback(3, "d:doc-1"))
    service.process_one()
    assert all(method != "sendDocument" for method, _, _ in api.calls)
    service.receive(callback(4, "o:foreign-doc"))
    service.process_one()
    assert "no longer available" in outputs(settings)[-1]["text"]
    service.receive(callback(5, "o:doc-1"))
    service.process_one()
    while service.deliver_one():
        pass
    assert sum(method == "sendDocument" for method, _, _ in api.calls) == 1
    service.receive(incoming(6, "/search"))
    service.process_one()
    service.receive(incoming(7, "Synthetic"))
    service.process_one()
    assert "Synthetic &lt;report&gt;" in outputs(settings)[-1]["text"]
    service.receive(callback(8, "d:../foreign-doc"))
    service.process_one()
    assert "no longer available" in outputs(settings)[-1]["text"]


def test_unlink_between_request_and_send_cancels_original(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    document(settings, owner)
    service.receive(callback(2, "o:doc-1"))
    service.process_one()
    service.unlink(owner)
    while service.deliver_one():
        pass
    assert not any(method == "sendDocument" for method, _, _ in api.calls)


def test_upload_dedup_replay_and_final_notifications(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["file"] = document(settings, owner)
    update = incoming(2, document={"file_id": "file", "file_name": "../../scan.pdf", "file_size": len(api.files["file"])})
    service.receive(update)
    service.process_one()
    assert not service.receive(update)
    with connect(settings) as db:
        row = db.execute("SELECT * FROM upload_jobs").fetchone()
        assert row["owner_user_id"] == owner and row["filename"] == "scan.pdf"
        assert row["state"] == "skipped" and row["document_id"] == "doc-1"
        assert row["source_path"] is None
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='telegram_upload_queued'").fetchone()[0] == 1
    service.notify_uploads()
    summary = outputs(settings)[-1]
    assert "Upload finished: 1 file" in summary["text"]
    assert "scan.pdf: already in your record as Synthetic &lt;report&gt;. Nothing was added." in summary["text"]
    assert summary["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "d:doc-1"
    before = len(outputs(settings))
    service.notify_uploads()
    assert len(outputs(settings)) == before


@pytest.mark.parametrize("filename,data,size,key", [("scan.docx", b"PKabc", 5, "Office"), ("scan.pdf", b"MZexe", 5, "Office"), ("scan.pdf", b"%PDF-x", MAX_FILE_BYTES + 1, "20 MB")])
def test_upload_limits_and_spoofed_file_type(ledger, filename, data, size, key):
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["file"] = data
    service.receive(incoming(2, document={"file_id": "file", "file_name": filename, "file_size": size}))
    service.process_one()
    with connect(settings) as db:
        job = db.execute("SELECT * FROM upload_jobs").fetchone()
        assert job["state"] == "failed" and job["source_path"] is None and job["filename"] == filename
    assert list(settings.source_dir.rglob("scan.*")) == []
    service.notify_uploads()
    summary = outputs(settings)[-1]["text"]
    assert key in summary and f"1. {filename}: not added." in summary


def test_upload_new_photo_enters_same_intake_queue(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["photo"] = b"\xff\xd8\xffsynthetic"
    service.receive(incoming(2, photo=[{"file_id": "photo", "file_size": 12}]))
    service.process_one()
    with connect(settings) as db:
        job = db.execute("SELECT * FROM upload_jobs").fetchone()
        assert job["state"] == "queued" and job["kind"] == "document"
        assert job["detail_key"] == "intake.step_waiting"
        assert job["owner_user_id"] == owner and job["patient_id"] == owner
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_rate_limit_outbox_restart_and_delivery_recheck(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.error = TelegramError("telegram.error_rate", retry_after=17)
    assert service.deliver_one()
    with connect(settings) as db:
        row = db.execute("SELECT * FROM telegram_outbox").fetchone()
        assert row["state"] == "pending" and row["attempts"] == 1
        assert row["available_at"] > time.time() + 15
        db.execute("UPDATE telegram_outbox SET available_at=0")
    restarted = TelegramService(settings, api_factory=lambda token: api)
    assert restarted.deliver_one()
    assert not restarted.deliver_one()


def test_polling_persisted_offset_and_worker_lease(ledger):
    settings, owner, _, api, service = ledger
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET lease_owner='other-worker',lease_until=?", (time.time() + 60,))
    assert not service.tick()
    assert api.calls == []
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET lease_until=0")
    api.updates = [incoming(123)]
    assert service.tick()
    assert service.config()["poll_offset"] == 124
    with connect(settings) as db:
        assert db.execute("SELECT update_id FROM telegram_updates").fetchone()[0] == 123


def test_transient_poll_failure_recovers_on_successful_empty_poll(ledger, monkeypatch):
    settings, _, _, api, service = ledger
    monkeypatch.setattr(service._stop, "wait", lambda seconds: False)
    previous_success = "2020-01-01T00:00:00+00:00"
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET last_success_at=?", (previous_success,))
    api.error = TelegramError("telegram.error_connection")
    assert not service.tick()
    assert service.config()["last_error"] == "telegram.error_connection"
    assert service.config()["last_success_at"] == previous_success
    assert service.tick()  # The fake API returns an empty update list.
    cfg = service.config()
    assert cfg["last_error"] is None
    assert cfg["last_success_at"] != previous_success
    assert cfg["enabled"] == 1 and cfg["poll_offset"] == 0
    assert [method for method, _, _ in api.calls] == ["getUpdates", "getUpdates"]


@pytest.mark.parametrize("permanent", [False, True])
def test_successful_empty_poll_preserves_unresolved_delivery_error(ledger, permanent):
    settings, owner, _, api, service = ledger
    link(service, owner)
    key = "telegram.error_connection" if permanent else "telegram.error_rate"
    api.error = TelegramError(key, permanent=permanent, retry_after=60)
    assert service.deliver_one()
    assert service.config()["last_error"] == key
    assert service.tick()
    cfg = service.config()
    assert cfg["last_success_at"] is not None
    assert cfg["last_error"] == key
    with connect(settings) as db:
        assert db.execute("SELECT state FROM telegram_outbox").fetchone()[0] == ("failed" if permanent else "pending")


def test_poll_recovery_restores_active_delivery_error_after_network_failure(ledger, monkeypatch):
    _, owner, _, api, service = ledger
    monkeypatch.setattr(service._stop, "wait", lambda seconds: False)
    link(service, owner)
    api.error = TelegramError("telegram.error_rate", retry_after=60)
    service.deliver_one()
    api.error = TelegramError("telegram.error_connection")
    assert not service.tick()
    assert service.config()["last_error"] == "telegram.error_connection"
    assert service.tick()
    assert service.config()["last_error"] == "telegram.error_rate"


def test_empty_poll_does_not_resurrect_terminal_error_cleared_by_later_send(ledger, monkeypatch):
    settings, owner, _, api, service = ledger
    monkeypatch.setattr(service._stop, "wait", lambda seconds: False)
    link(service, owner)
    api.error = TelegramError("telegram.error_connection", permanent=True)
    service.deliver_one()
    assert service.config()["last_error"] == "telegram.error_connection"
    service.receive(incoming(2, "/menu"))
    service.process_one()
    service.deliver_one()
    assert service.config()["last_error"] is None
    assert service.tick()
    assert service.config()["last_error"] is None
    # Repeating the same network error must not revive a historical delivery error.
    api.error = TelegramError("telegram.error_connection")
    assert not service.tick()
    assert service.config()["last_error"] == "telegram.error_connection"
    restarted = TelegramService(settings, api_factory=lambda token: api)
    assert restarted.tick()
    assert restarted.config()["last_error"] is None
    with connect(settings) as db:
        assert tuple(db.execute("SELECT state,error_key FROM telegram_outbox WHERE state!='sent'").fetchone()) == (
            "failed_historical", "telegram.error_connection")


@pytest.mark.parametrize("permanent", [False, True])
def test_successful_delivery_to_other_chat_keeps_unresolved_error(ledger, permanent):
    settings, owner, other, api, service = ledger
    link(service, owner)
    api.error = TelegramError("telegram.error_rate", permanent=permanent, retry_after=60)
    service.deliver_one()
    link(service, other, uid=2, chat=202)
    assert service.deliver_one()
    assert service.config()["last_error"] == "telegram.error_rate"
    assert service.tick()
    assert service.config()["last_error"] == "telegram.error_rate"
    with connect(settings) as db:
        assert db.execute("SELECT state FROM telegram_outbox WHERE chat_id=101").fetchone()[0] == ("failed" if permanent else "pending")


def test_successful_callback_acknowledgement_does_not_clear_failed_message(ledger):
    _, owner, _, api, service = ledger
    link(service, owner)
    api.error = TelegramError("telegram.error_connection", permanent=True)
    service.deliver_one()
    service.receive(callback(2, "home"))
    service.process_one()
    assert service.deliver_one()
    assert api.calls[-1][0] == "answerCallbackQuery"
    assert service.config()["last_error"] == "telegram.error_connection"


def test_document_route_recovery_retains_failed_request_evidence_until_unlink(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    service.deliver_one()
    document(settings, owner, "first")
    document(settings, owner, "second")
    service.receive(callback(2, "o:first"))
    service.process_one()
    service.deliver_one()  # Callback acknowledgement.
    api.error = TelegramError("telegram.error_connection", permanent=True)
    service.deliver_one()
    with connect(settings) as db:
        failed = dict(db.execute("SELECT * FROM telegram_outbox WHERE method='sendDocument'").fetchone())
    assert failed["state"] == "failed" and failed["attempts"] == 1
    service.deliver_one()  # The failure explanation does not prove file delivery recovered.
    assert service.config()["last_error"] == "telegram.error_connection"
    service.receive(callback(3, "o:second"))
    service.process_one()
    service.deliver_one()
    service.deliver_one()
    assert service.config()["last_error"] is None
    assert service.config()["delivery_count"] == 0
    assert not service.deliver_one()  # Historical failures are never retried.
    with connect(settings) as db:
        retained = dict(db.execute("SELECT * FROM telegram_outbox WHERE id=?", (failed["id"],)).fetchone())
        assert retained == {**failed, "state": "failed_historical"}
        assert db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE method='sendDocument' AND state='sent'").fetchone()[0] == 1
    service.unlink(owner)
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE owner_user_id=?", (owner,)).fetchone()[0] == 0


@pytest.mark.parametrize("response", [None, False, {}, [None], [{"update_id": "invalid"}], [{"update_id": -1}]])
def test_malformed_poll_response_does_not_report_success_or_advance_offset(ledger, monkeypatch, response):
    settings, _, _, api, service = ledger
    monkeypatch.setattr(service._stop, "wait", lambda seconds: False)
    monkeypatch.setattr(api, "call", lambda method, payload: response)
    assert not service.tick()
    cfg = service.config()
    assert cfg["last_error"] == "telegram.error_connection"
    assert cfg["last_success_at"] is None and cfg["poll_offset"] == 0
    assert cfg["enabled"] == 1
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0] == 0


def test_activation_and_mode_switch_are_explicit(ledger, monkeypatch):
    settings, owner, _, api, service = ledger
    monkeypatch.setattr(service, "start", lambda: None)
    monkeypatch.setenv("ANAMNA_TELEGRAM_WEBHOOK_SECRET", "S" * 40)
    service.configure(enabled=True, mode="webhook", public_url="https://health.example.com", actor=owner)
    assert service.config()["mode"] == "webhook"
    assert any(method == "setMyCommands" and payload.get("language_code") == "uk" for method, payload, _ in api.calls)
    assert any(method == "setWebhook" and payload["secret_token"] == "S" * 40 for method, payload, _ in api.calls)
    with pytest.raises(TelegramError):
        service.receive(incoming(1), webhook_secret="wrong")
    assert service.receive(incoming(1), webhook_secret="S" * 40)
    service.configure(enabled=True, mode="polling", public_url="", actor=owner)
    assert api.calls[-1][0] == "deleteWebhook"
    service.configure(enabled=False, mode="polling", public_url="", actor=owner)
    assert not service.config()["enabled"]


def test_activation_installs_ukrainian_fallback_and_both_locales_for_private_chats(ledger, monkeypatch):
    _, owner, _, api, service = ledger
    monkeypatch.setattr(service, "start", lambda: None)
    service.configure(enabled=True, mode="polling", public_url="", actor=owner)
    registrations = [payload for method, payload, _ in api.calls if method == "setMyCommands"]
    assert len(registrations) == 3
    by_language = {payload.get("language_code", ""): payload for payload in registrations}
    assert set(by_language) == {"", "en", "uk"}
    assert "language_code" not in by_language[""]
    assert by_language[""]["commands"] == by_language["uk"]["commands"], "the audience is Ukrainian"
    assert by_language["uk"]["commands"] != by_language["en"]["commands"]
    expected = {"start", "menu", "metrics", "documents", "search", "upload", "uploads", "account", "unlink", "language", "help", "cancel"}
    for payload in registrations:
        assert payload["scope"] == {"type": "all_private_chats"}
        assert len(payload["commands"]) == 12
        assert {item["command"] for item in payload["commands"]} == expected
        assert all(item["description"] for item in payload["commands"])
    assert not any(method.startswith("send") for method, _, _ in api.calls)


def test_ukrainian_language_and_cancel(ledger):
    settings, owner, _, _, service = ledger
    link(service, owner)
    service.receive(callback(2, "lang:uk"))
    service.process_one()
    service.receive(incoming(3, "/search"))
    service.process_one()
    assert "Надішліть" in outputs(settings)[-1]["text"]
    service.receive(incoming(4, "/cancel"))
    service.process_one()
    assert "Ваша Anamna" in outputs(settings)[-1]["text"]
    with connect(settings) as db:
        assert db.execute("SELECT state FROM telegram_links").fetchone()[0] == ""


def test_transport_rejects_path_traversal_without_network(monkeypatch):
    api = TelegramAPI("123456:abcdefghijklmnopqrstuvxyz")
    monkeypatch.setattr(api, "call", lambda *args, **kwargs: {"file_path": "../secret", "file_size": 10})
    with pytest.raises(TelegramError, match="telegram.error_file"):
        api.download("file")


def test_lab_trend_has_real_values_dates_review_and_document_provenance(ledger):
    settings, owner, other, _, service = ledger
    link(service, owner)
    document(settings, owner)
    document(settings, other, "foreign-doc", "Foreign source")
    with connect(settings) as db:
        for ident, uid, doc, value, day, status in (("result-1", owner, "doc-1", 4.4, "2026-09-01", "extracted"), ("result-2", owner, "doc-1", 3.1, "2026-08-01", "verified"), ("result-3", owner, "doc-1", 999, "2026-09-02", "rejected"), ("result-4", other, "foreign-doc", 777, "2026-09-03", "verified")):
            db.execute("""INSERT INTO observations(id,owner_user_id,patient_id,document_id,page_number,raw_name,value_type,value_numeric,unit_raw,observed_at,vendor_reference_text,verification_status,extraction_method,evidence_text,parser_version,created_at)
                VALUES(?,?,?,?,1,'LDL cholesterol','numeric',?,'mmol/L',?,'0–3.0',?,'native_text','Synthetic evidence','fixture',?)""", (ident, uid, uid, doc, value, day, status, utc_now()))
    service.receive(callback(2, "m:result-1"))
    service.process_one()
    body = outputs(settings)[-1]["text"]
    assert "4.4" in body and "3.1" in body
    assert "999" not in body and "777" not in body
    assert "Not yet verified" in body and "Verified by a person" in body
    assert "2026" in body and "Synthetic &lt;report&gt;" in body
    assert "Reference printed by the laboratory: 0–3.0" in body
    service.receive(callback(3, "m:result-4"))
    service.process_one()
    assert "no longer available" in outputs(settings)[-1]["text"]


def test_real_pdf_passes_existing_intake_and_final_document_link(ledger):
    import io
    from reportlab.pdfgen.canvas import Canvas
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    buffer = io.BytesIO()
    pdf = Canvas(buffer)
    for line, text in enumerate(("Synthetic laboratory report", "Date: 01.09.2026", "Glucose 5.1 mmol/L 3.9 - 6.1", "This document is a synthetic integration fixture.")):
        pdf.drawString(60, 740 - line * 24, text)
    pdf.save()
    api.files["pdf"] = buffer.getvalue()
    service.receive(incoming(2, document={"file_id": "pdf", "file_name": "synthetic-lab.pdf", "file_size": len(api.files["pdf"])}))
    service.process_one()
    drain_now(settings)
    with connect(settings) as db:
        job = db.execute("SELECT * FROM upload_jobs").fetchone()
        assert job["state"] == "done", dict(job)
        assert job["document_id"]
        document_id = job["document_id"]
        stored = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        assert stored["owner_user_id"] == owner
        assert db.execute("SELECT COUNT(*) FROM observations WHERE verification_status='verified'").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    service.notify_uploads()
    assert any(button["callback_data"] == "d:" + document_id for row in outputs(settings)[-1]["reply_markup"]["inline_keyboard"] for button in row if "callback_data" in button)


def test_malformed_update_does_not_block_next_menu(ledger):
    settings, owner, _, _, service = ledger
    link(service, owner)
    service.receive({"update_id": 2, "message": "invalid-envelope"})
    service.receive(incoming(3, "/menu"))
    assert service.process_one()
    assert service.process_one()
    assert "Your Anamna" in outputs(settings)[-1]["text"]


def test_download_releases_write_lock_and_unlink_prevents_publication(ledger, monkeypatch):
    settings, owner, _, api, service = ledger
    link(service, owner)
    def download(file_id):
        # This takes another BEGIN IMMEDIATE: holding a download inside the
        # inbox transaction would fail with SQLite's busy timeout here.
        service.unlink(owner)
        return b"%PDF-synthetic"
    monkeypatch.setattr(api, "download", download)
    service.receive(incoming(2, document={"file_id": "pdf", "file_name": "scan.pdf"}))
    service.process_one()
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0
        assert db.execute("SELECT state FROM telegram_updates WHERE update_id=2").fetchone()[0] == "done"
    assert list(settings.source_dir.rglob("*.pdf")) == []


def test_send_releases_write_lock_and_disabled_service_does_nothing(ledger, monkeypatch):
    from anamna.db import transaction
    settings, owner, _, api, service = ledger
    link(service, owner)
    def call(method, payload=None, **kwargs):
        with transaction(settings, immediate=True) as db:
            db.execute("UPDATE telegram_links SET state='write-during-send' WHERE owner_user_id=?", (owner,))
        return True
    monkeypatch.setattr(api, "call", call)
    assert service.deliver_one()
    with connect(settings) as db:
        assert db.execute("SELECT state FROM telegram_links").fetchone()[0] == "write-during-send"
        db.execute("UPDATE telegram_config SET enabled=0")
    assert not service.process_one()
    assert not service.deliver_one()


def test_upload_rollback_removes_its_new_source(ledger, monkeypatch):
    import anamna.telegram as module
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["file"] = b"%PDF-synthetic"
    service.receive(incoming(2, document={"file_id": "file", "file_name": "scan.pdf"}))
    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic publication failure")
    monkeypatch.setattr(module, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="publication failure"):
        service.process_one()
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0
    assert list(settings.source_dir.rglob("*.pdf")) == []


@pytest.fixture
def web_ledger(ledger, monkeypatch):
    from fastapi.testclient import TestClient
    from anamna.security import create_session
    from anamna.web.app import create_app
    settings, owner, other, api, _ = ledger
    monkeypatch.setenv("ANAMNA_BACKGROUND_WORKERS", "0")
    app = create_app(settings)
    service = app.state.telegram
    service.api_factory = lambda token: api
    token, csrf = create_session(settings, owner)
    client = TestClient(app)
    client.cookies.set("anamna_session", token)
    return settings, owner, other, api, service, app, client, csrf


def test_integrated_admin_both_locales_and_secrets_never_render(web_ledger, monkeypatch):
    settings, owner, other, api, service, app, client, csrf = web_ledger
    assert service._thread is None  # create_app/GET alone never starts a worker.
    for locale, title in (("en", "Telegram bot settings"), ("uk", "Налаштування Telegram-бота")):
        client.cookies.set("anamna_lang", locale)
        response = client.get("/admin/telegram")
        assert response.status_code == 200
        assert title in response.text and "telegram.admin" not in response.text
        assert service.token() not in response.text
        assert 'value="polling"' in response.text
    assert service._thread is None and api.calls == []
    rejected = client.post("/admin/telegram", data={"csrf_token": "incorrect", "action": "activate", "mode": "polling"}, follow_redirects=False)
    assert rejected.status_code == 403 and api.calls == []
    started = []
    monkeypatch.setattr(service, "start", lambda: started.append(True))
    response = client.post("/admin/telegram", data={"csrf_token": csrf, "action": "activate", "mode": "polling", "public_url": ""})
    assert response.status_code == 200 and started == [True]
    assert any(method == "getMe" for method, _, _ in api.calls)
    assert service.token() not in response.text


def test_integrated_profile_link_consent_csrf_and_unlink(web_ledger):
    settings, owner, _, _, service, _, client, csrf = web_ledger
    assert client.post("/profile/telegram/link", data={"csrf_token": csrf}).status_code == 400
    assert client.post("/profile/telegram/link", data={"csrf_token": "bad", "consent": "1"}).status_code == 403
    response = client.post("/profile/telegram/link", data={"csrf_token": csrf, "consent": "1"})
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.headers["referrer-policy"] == "no-referrer"
    import re
    token = re.search(r"https://t.me/LedgerTestBot\?start=([A-Za-z0-9_-]+)", response.text).group(1)
    service.receive(incoming(1, "/start " + token))
    service.process_one()
    assert service.profile(owner)["linked"]
    response = client.post("/profile/telegram/unlink", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303 and not service.profile(owner)["linked"]


def test_integrated_guest_api_and_other_user_boundaries(web_ledger):
    from datetime import UTC, datetime, timedelta
    from fastapi.testclient import TestClient
    from anamna.security import create_access_token, create_session
    settings, owner, other, _, _, app, _, _ = web_ledger
    client = TestClient(app)
    for kind in ("api", "guest"):
        _, secret = create_access_token(settings, owner, kind, "Synthetic Telegram boundary", expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
        assert client.get("/admin/telegram", headers={"Authorization": "Bearer " + secret}).status_code == 403
        assert client.post("/profile/telegram/link", headers={"Authorization": "Bearer " + secret}, data={"consent": "1"}).status_code == 403
    session, csrf = create_session(settings, other)
    client.cookies.set("anamna_session", session)
    assert client.get("/admin/telegram").status_code == 403
    assert client.post("/admin/telegram", data={"csrf_token": csrf, "action": "activate", "mode": "polling"}).status_code == 403


def test_integrated_webhook_anonymous_secret_bounds_and_replay(web_ledger, monkeypatch):
    from fastapi.testclient import TestClient
    settings, _, _, api, _, app, _, _ = web_ledger
    secret = "synthetic-webhook-secret-" + "x" * 24
    monkeypatch.setenv("ANAMNA_TELEGRAM_WEBHOOK_SECRET", secret)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET mode='webhook'")
    client = TestClient(app)
    assert client.post("/api/telegram/webhook", json=incoming(123)).status_code == 403
    assert client.post("/api/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, json=incoming(123)).status_code == 403
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
    assert client.post("/api/telegram/webhook", headers=headers, json=incoming(123)).status_code == 200
    assert client.post("/api/telegram/webhook", headers=headers, json=incoming(123)).status_code == 200
    assert client.post("/api/telegram/webhook", headers=headers, content=b"x" * 262145).status_code == 413
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0] == 1
    assert api.calls == []


def test_integrated_lifespan_controls_worker_start_and_stop(web_ledger, monkeypatch):
    from fastapi.testclient import TestClient
    from anamna.web import app as web
    _, _, _, _, service, app, _, _ = web_ledger
    calls = []
    monkeypatch.setenv("ANAMNA_BACKGROUND_WORKERS", "1")
    monkeypatch.setattr(web.ow_hooks, "start_worker", lambda settings: None)
    monkeypatch.setattr(service, "start", lambda: calls.append("start"))
    monkeypatch.setattr(service, "stop", lambda: calls.append("stop"))
    assert calls == []
    with TestClient(app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]


def test_long_escaped_cards_fall_back_to_valid_bounded_plain_text(ledger):
    from html import escape
    settings, owner, _, _, service = ledger
    link(service, owner)
    with connect(settings) as db:
        service._queue(db, "long", owner, 101, "<b>" + escape("<" * 4000) + "</b>")
    payload = outputs(settings)[-1]
    assert "parse_mode" not in payload
    assert payload["text"] == "<" * 3900


def test_original_transport_sends_boolean_as_json_form_value(tmp_path):
    import io
    from types import SimpleNamespace
    api = TelegramAPI("123456:abcdefghijklmnopqrstuvxyz")
    captured = []
    def open_request(request, timeout):
        captured.append(request.data)
        return io.BytesIO(b'{"ok":true,"result":true}')
    api._opener = SimpleNamespace(open=open_request)
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-synthetic")
    api.call("sendDocument", {"chat_id": 101, "protect_content": True}, document=source)
    assert b'name="protect_content"\r\n\r\ntrue\r\n' in captured[0]
    assert b"%PDF-synthetic" in captured[0]


def test_profile_availability_requires_configuration_activation_or_existing_link(ledger, monkeypatch):
    settings, owner, _, _, service = ledger
    assert service.profile(owner)["available"]
    monkeypatch.delenv("ANAMNA_TELEGRAM_BOT_TOKEN", raising=False)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET enabled=0")
    assert not service.profile(owner)["available"]
    monkeypatch.setenv("ANAMNA_TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvxyz")
    assert service.profile(owner)["available"]  # Configured but not activated.
    monkeypatch.delenv("ANAMNA_TELEGRAM_BOT_TOKEN", raising=False)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET enabled=1")
    assert service.profile(owner)["available"]
    link(service, owner)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET enabled=0")
    assert service.profile(owner)["available"]  # Disconnection must remain reachable.
    service.unlink(owner)
    assert not service.profile(owner)["available"]


def _data_version(connection):
    return connection.execute("PRAGMA data_version").fetchone()[0]


def test_idle_webhook_worker_never_writes_and_a_webhook_update_wakes_it(ledger):
    """PERF-10: an idle webhook-mode bot used to take the write lock and commit
    two lease UPDATEs every half second (~2.5 commits/s on the sandbox).  Idle
    now means reads only; a received update ends the idle wait at once."""
    import sqlite3
    settings, owner, _, api, service = ledger
    link(service, owner)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET mode='webhook',public_url='https://health.example.com'")
    while service.deliver_one():  # the link confirmation
        pass
    assert service.tick()  # the one webhook health check: getWebhookInfo, success recorded
    assert api.calls[-1][0] == "getWebhookInfo"
    assert service.config()["status"] == "ok"
    watcher = sqlite3.connect(settings.database_path)
    try:
        before = _data_version(watcher)
        for _ in range(25):
            assert not service.tick()
        assert _data_version(watcher) == before  # not one commit while idle
        assert service.config()["lease_owner"] is None
        assert 25 <= service.idle_wait <= 30
        # The thread, left idle, still commits nothing...
        calls = len(api.calls)
        service.start()
        try:
            time.sleep(1.5)
            assert _data_version(watcher) == before
            assert len(api.calls) == calls
            # ...and a received webhook update is answered without waiting out the 30 s.
            started = time.time()
            service.receive(incoming(50, "/menu"))
            while time.time() - started < 10 and not any(m == "sendMessage" for m, _, _ in api.calls[calls:]):
                time.sleep(0.05)
            assert any(m == "sendMessage" for m, _, _ in api.calls[calls:])
            assert time.time() - started < 10
        finally:
            service.stop()
        assert _data_version(watcher) != before
    finally:
        watcher.close()


def test_webhook_check_reports_a_webhook_registered_elsewhere(ledger, monkeypatch):
    settings, _, _, api, service = ledger
    monkeypatch.setattr(service._stop, "wait", lambda seconds: False)
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET mode='webhook',public_url='https://other.example.com'")
    assert not service.tick()
    cfg = service.config()
    assert cfg["last_error"] == "telegram.error_conflict" and cfg["last_error_at"]
    assert cfg["status"] == "error" and cfg["enabled"] == 1
    assert not service.tick()  # the failed check is retried later, not on every pass
    assert [method for method, _, _ in api.calls].count("getWebhookInfo") == 1


@pytest.mark.parametrize("row, expected", [
    ({"enabled": 0, "last_error": None, "last_error_at": None, "last_success_at": None}, "off"),
    ({"enabled": 1, "last_error": None, "last_error_at": None, "last_success_at": None}, "waiting"),
    ({"enabled": 1, "last_error": None, "last_error_at": None, "last_success_at": "2026-11-01T10:00:00+00:00"}, "ok"),
    # The sandbox on 2026-11-06: an error written before the column existed, last success in September.
    ({"enabled": 1, "last_error": "telegram.error_connection", "last_error_at": None, "last_success_at": "2026-09-08T19:45:28+00:00"}, "error"),
    ({"enabled": 1, "last_error": "telegram.error_connection", "last_error_at": "2026-11-02T10:00:00+00:00", "last_success_at": "2026-09-08T19:45:28+00:00"}, "error"),
    ({"enabled": 1, "last_error": "telegram.error_rate", "last_error_at": "2026-11-01T10:00:00+00:00", "last_success_at": "2026-11-02T10:00:00+00:00"}, "warning"),
])
def test_status_comes_from_the_error_and_success_stamps(row, expected):
    from anamna.telegram import status_of
    assert status_of(row) == expected


def test_admin_page_shows_both_stamps_and_a_failing_bot_is_not_active(web_ledger):
    settings, _, _, _, _, _, client, _ = web_ledger
    with connect(settings) as db:
        db.execute("""UPDATE telegram_config SET last_error='telegram.error_connection',
            last_error_at='2026-11-02T10:05:00+00:00', last_success_at='2026-09-08T19:45:28+00:00'""")
    for locale, state, success, error in (
        ("en", "Active · not working", "Last successful contact with Telegram", "Last error"),
        ("uk", "Активний · не працює", "Останній успішний зв’язок із Telegram", "Остання помилка"),
    ):
        client.cookies.set("anamna_lang", locale)
        page = client.get("/admin/telegram").text
        assert state in page and success in page and error in page
        assert "19:45 UTC" in page and "10:05 UTC" in page
        assert "telegram.state" not in page and "telegram.last" not in page


# --- several files at once: batches, duplicates, one acknowledgement --------


def real_pdf(*lines):
    import io
    from reportlab.pdfgen.canvas import Canvas
    buffer = io.BytesIO()
    pdf = Canvas(buffer)
    for row, text in enumerate(lines):
        pdf.drawString(60, 740 - row * 24, text)
    pdf.save()
    return buffer.getvalue()


def zipped(name, data):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, data)
    return buffer.getvalue()


LAB = ("Synthetic laboratory report", "Date: 01.09.2026", "Glucose 5.1 mmol/L 3.9 - 6.1", "This document is a synthetic integration fixture.")
OTHER = ("Synthetic laboratory report", "Date: 02.09.2026", "Glucose 5.4 mmol/L 3.9 - 6.1", "A second synthetic integration fixture.")


def album_part(uid, media_group="album-1", **attachment):
    return incoming(uid, media_group_id=media_group, **attachment)


def file_part(uid, file_id, name, size=None, **extra):
    return album_part(uid, document={"file_id": file_id, "file_name": name, "file_size": size if size is not None else 10}, **extra)


def run_inbox(service):
    while service.process_one():
        pass


def messages_after(settings, count):
    return outputs(settings)[count:]


def test_album_of_mixed_files_is_one_batch_one_acknowledgement_and_one_summary(ledger):
    """PDF + duplicate PDF in the same album + a zip + a file already in the
    record + Office + oversize: every file is accepted once, the chat gets one
    acknowledgement and one summary naming each file's outcome."""
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    while service.deliver_one():
        pass
    before = len(outputs(settings))
    api.files["held"] = document(settings, owner)
    api.files["lab"] = real_pdf(*LAB)
    api.files["zip"] = zipped("inner-report.pdf", real_pdf(*OTHER))
    parts = [
        file_part(10, "lab", "lab-a.pdf", len(api.files["lab"])),
        file_part(11, "lab", "lab-copy.pdf", len(api.files["lab"])),
        file_part(12, "zip", "bundle.zip", len(api.files["zip"])),
        file_part(13, "held", "again.pdf", len(api.files["held"])),
        file_part(14, "nope", "letter.docx", 100),
        file_part(15, "big", "huge.pdf", MAX_FILE_BYTES + 1),
    ]
    for part in parts:
        assert service.receive(part)
    run_inbox(service)
    assert messages_after(settings, before) == [], "a file gets no reply of its own"
    service.notify_uploads()
    ack = messages_after(settings, before)
    assert len(ack) == 1 and ack[0]["text"].startswith("Received 6 files.")
    assert ack[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Cancel this upload"
    service.notify_uploads()
    assert len(messages_after(settings, before)) == 1, "the acknowledgement is sent once"
    drain_now(settings)
    service.notify_uploads()
    service.notify_uploads()
    sent = messages_after(settings, before)
    assert len(sent) == 2, [item.get("text") for item in sent]
    summary = sent[1]["text"]
    with connect(settings) as db:
        batches = {row[0] for row in db.execute("SELECT batch_id FROM upload_jobs")}
        assert len(batches) == 1
        lab_title = db.execute("SELECT title FROM documents WHERE original_filename='lab-a.pdf'").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM documents WHERE sha256=?", (hashlib.sha256(api.files["lab"]).hexdigest(),)).fetchone()[0] == 1
        copy = db.execute("SELECT * FROM upload_jobs WHERE filename='lab-copy.pdf'").fetchone()
        assert copy["state"] == "skipped" and copy["detail_key"] == "intake.done_duplicate"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert "<b>Upload finished: 6 files</b>" in summary
    assert "Added: 2. Already in your record: 2. Not added: 2." in summary
    # This synthetic page names no laboratory, so no value is read from it.
    assert f"lab-a.pdf: added as {lab_title}, but no values could be read automatically." in summary
    assert f"lab-copy.pdf: already in your record as {lab_title}. Nothing was added." in summary
    assert "inner-report.pdf: added as" in summary and "bundle.zip" not in summary
    assert "again.pdf: already in your record as Synthetic &lt;report&gt;." in summary
    assert "letter.docx: not added. Use PDF, JPEG, PNG, TIFF or ZIP." in summary
    assert "huge.pdf: not added. The file is empty or exceeds 20 MB." in summary
    assert "Values stay provisional" in summary
    labels = [button["text"] for row in sent[1]["reply_markup"]["inline_keyboard"] for button in row]
    assert "Undo this upload" in labels and lab_title in labels
    # The copy in the album left no bytes behind: only the record's own files remain.
    assert sorted(path.name for path in (settings.source_dir / "uploads").rglob("*.pdf")) == ["inner-report.pdf", "lab-a.pdf"]


def test_summary_in_ukrainian_uses_its_plural_forms(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    service.receive(callback(2, "lang:uk"))
    run_inbox(service)
    api.files["held"] = document(settings, owner)
    for uid in (3, 4):
        service.receive(file_part(uid, "held", f"copy-{uid}.pdf", len(api.files["held"])))
    service.receive(file_part(5, "x", "note.docx"))
    run_inbox(service)
    service.notify_uploads()
    summary = outputs(settings)[-1]["text"]
    assert "<b>Завантаження завершено: 3 файли</b>" in summary
    assert "Додано: 0. Уже були в картці: 2. Не додано: 1." in summary
    assert "copy-3.pdf: уже є у вашій картці як Synthetic &lt;report&gt;. Нічого не додано." in summary
    assert "note.docx: не додано. Підтримуються PDF, JPEG, PNG, TIFF і ZIP." in summary
    with connect(settings) as db:
        db.execute("UPDATE telegram_uploads SET notified_state='done'")
    for uid in range(6, 11):
        service.receive(file_part(uid, "x", f"note-{uid}.docx"))
    run_inbox(service)
    service.notify_uploads()
    assert "<b>Завантаження завершено: 5 файлів</b>" in outputs(settings)[-1]["text"]


def test_acknowledgement_waits_until_files_stop_arriving(ledger, monkeypatch):
    settings, owner, _, api, service = ledger
    link(service, owner)
    while service.deliver_one():
        pass
    before = len(outputs(settings))
    api.files["pdf"] = b"%PDF-1.4 still arriving"
    monkeypatch.setattr("anamna.telegram.BATCH_QUIET", 3600)
    service.receive(file_part(2, "pdf", "first.pdf"))
    run_inbox(service)
    service.notify_uploads()
    assert messages_after(settings, before) == [], "inside the quiet window nothing is said"
    monkeypatch.setattr("anamna.telegram.BATCH_QUIET", 0)
    service.receive(file_part(3, "pdf", "second.pdf"))
    service.notify_uploads()
    assert messages_after(settings, before) == [], "a file of this chat still in the inbox holds the acknowledgement"
    run_inbox(service)
    service.notify_uploads()
    assert [item["text"].split(".")[0] for item in messages_after(settings, before)] == ["Received 2 files"]
    # A file after the acknowledgement starts a batch of its own.
    service.receive(file_part(4, "pdf", "third.pdf"))
    run_inbox(service)
    service.notify_uploads()
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(DISTINCT batch_id) FROM upload_jobs").fetchone()[0] == 2
    assert messages_after(settings, before)[-1]["text"].startswith("Received 1 file.")


def test_concurrent_out_of_order_and_retried_updates_accept_each_file_once(ledger):
    import threading
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["photo"] = b"\xff\xd8\xffsynthetic photo"
    parts = [album_part(uid, photo=[{"file_id": "photo", "file_size": 5}, {"file_id": "photo", "file_size": 20}]) for uid in (24, 21, 23, 22, 20)]
    results, gate = [], threading.Barrier(10)

    def deliver(update):
        gate.wait()
        results.append(service.receive(update))

    # Every part twice, all at once: Telegram retrying while the first attempt is in flight.
    threads = [threading.Thread(target=deliver, args=(part,)) for part in parts + parts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False] * 5 + [True] * 5
    # A second worker (another process) shares the inbox; claims never overlap.
    other = TelegramService(settings, api_factory=lambda token: api)
    while service.process_one() | other.process_one():
        pass
    with connect(settings) as db:
        jobs = db.execute("SELECT * FROM upload_jobs ORDER BY created_at").fetchall()
        assert len(jobs) == 5 and len({job["batch_id"] for job in jobs}) == 1
        assert {job["filename"] for job in jobs} == {"photo.jpg"}
        assert len({job["source_path"] for job in jobs}) == 5, "same-named photos never overwrite each other"
        assert db.execute("SELECT COUNT(*) FROM telegram_uploads").fetchone()[0] == 5
    service.notify_uploads()
    assert outputs(settings)[-1]["text"].startswith("Received 5 files.")


def test_redelivery_after_a_restart_adds_nothing_and_says_nothing(ledger):
    """Telegram re-sends updates it saw no answer to, for instance across a
    container restart. The inbox key is persisted, so a fresh process treats
    the replay as already handled."""
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["pdf"] = b"%PDF-1.4 delivered twice"
    updates = [file_part(uid, "pdf", f"scan-{uid}.pdf") for uid in (2, 3)]
    for update in updates:
        service.receive(update)
    run_inbox(service)
    service.notify_uploads()
    sent = len(outputs(settings))
    restarted = TelegramService(settings, api_factory=lambda token: api)
    for update in updates:
        assert not restarted.receive(update)
    run_inbox(restarted)
    restarted.notify_uploads()
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 2
    assert len(outputs(settings)) == sent


def test_a_resent_file_is_reported_as_already_there_not_filed_twice(ledger):
    """The same scan sent again while its first copy still waits in the queue:
    the door cannot see it in the record yet, the queue can."""
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["lab"] = real_pdf(*LAB)
    service.receive(file_part(2, "lab", "first.pdf", media_group="a"))
    run_inbox(service)
    service.notify_uploads()  # acknowledged: the next message is a new batch
    service.receive(file_part(3, "lab", "resent.pdf", media_group="b"))
    run_inbox(service)
    drain_now(settings)
    service.notify_uploads()
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        resent = db.execute("SELECT * FROM upload_jobs WHERE filename='resent.pdf'").fetchone()
        assert resent["state"] == "skipped" and resent["document_id"]
    assert "resent.pdf: already in your record as" in outputs(settings)[-1]["text"]


def test_same_report_in_a_different_file_is_reported_as_a_suggested_copy(ledger):
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["a"] = real_pdf(*LAB)
    service.receive(file_part(2, "a", "portal.pdf", media_group="a"))
    run_inbox(service)
    drain_now(settings)
    service.notify_uploads()
    with connect(settings) as db:
        first = db.execute("SELECT id,title FROM documents").fetchone()
    # A re-export: different bytes, identical text.
    api.files["b"] = api.files["a"].replace(b"/Producer", b"/Creator (synthetic re-export) /Producer", 1)
    assert api.files["b"] != api.files["a"]
    service.receive(file_part(3, "b", "export.pdf", len(api.files["b"]), media_group="b"))
    run_inbox(service)
    drain_now(settings)
    service.notify_uploads()
    summary = outputs(settings)[-1]["text"]
    assert "export.pdf: added as" in summary
    assert f"It looks like a copy of {first['title']}; confirm that on its page in Anamna." in summary


def test_undo_removes_only_what_the_upload_created_after_confirmation(ledger):
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    api.files["held"] = document(settings, owner)
    api.files["lab"] = real_pdf(*LAB)
    service.receive(file_part(2, "lab", "new.pdf", len(api.files["lab"])))
    service.receive(file_part(3, "held", "old.pdf", len(api.files["held"])))
    run_inbox(service)
    drain_now(settings)
    service.notify_uploads()
    with connect(settings) as db:
        batch = db.execute("SELECT DISTINCT batch_id FROM upload_jobs").fetchone()[0]
        created = db.execute("SELECT id,source_path FROM documents WHERE id<>'doc-1'").fetchone()
    service.receive(callback(4, "u:" + batch))
    run_inbox(service)
    card = outputs(settings)[-1]
    assert "Remove this upload?" in card["text"] and "Documents it added that will be deleted: 1." in card["text"]
    assert card["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "uy:" + batch
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2, "asking deletes nothing"
    service.receive(callback(5, "uy:" + batch))
    run_inbox(service)
    assert "Upload removed. Documents deleted: 1. Waiting files cancelled: 0." in outputs(settings)[-1]["text"]
    with connect(settings) as db:
        assert [row[0] for row in db.execute("SELECT id FROM documents")] == ["doc-1"], "the document already in the record stays"
        assert db.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM review_tasks WHERE entity_id=?", (created["id"],)).fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='telegram_upload_undone'").fetchone()[0] == 1
    assert not list((settings.source_dir / "uploads").rglob("*.pdf"))
    assert (settings.source_dir / "doc-1.pdf").is_file()
    # Pressed again: nothing left to remove, and it says so.
    service.receive(callback(6, "uy:" + batch))
    run_inbox(service)
    assert "can no longer be undone here" in outputs(settings)[-1]["text"]


def test_cancel_while_waiting_and_undo_refusals(ledger):
    from anamna.ingest.intake import drain_now
    settings, owner, other, api, service = ledger
    link(service, owner)
    api.files["pdf"] = b"%PDF-1.4 waiting its turn"
    service.receive(file_part(2, "pdf", "waiting.pdf"))
    run_inbox(service)
    service.notify_uploads()
    with connect(settings) as db:
        batch = db.execute("SELECT batch_id FROM upload_jobs").fetchone()[0]
        db.execute("UPDATE upload_jobs SET state='running'")
    service.receive(callback(3, "uy:" + batch))
    run_inbox(service)
    assert "being read right now" in outputs(settings)[-1]["text"]
    with connect(settings) as db:
        db.execute("UPDATE upload_jobs SET state='queued'")
    service.receive(callback(4, "uy:" + batch))
    run_inbox(service)
    assert "Waiting files cancelled: 1." in outputs(settings)[-1]["text"]
    assert not list((settings.source_dir / "uploads").rglob("*.pdf"))
    # A batch of somebody else, or one that never existed, is not this chat's to touch.
    service.receive(callback(5, "uy:telegram-0000"))
    run_inbox(service)
    assert "can no longer be undone here" in outputs(settings)[-1]["text"]
    # A checked value means the record builds on the document: refused.
    api.files["lab"] = real_pdf(*LAB)
    service.receive(file_part(6, "lab", "checked.pdf", len(api.files["lab"])))
    run_inbox(service)
    drain_now(settings)
    service.notify_uploads()
    with connect(settings) as db:
        batch, created = db.execute("SELECT batch_id,document_id FROM upload_jobs").fetchone()
        db.execute("""INSERT INTO observations(id,owner_user_id,patient_id,document_id,page_number,raw_name,value_type,value_numeric,unit_raw,verification_status,extraction_method,evidence_text,parser_version,created_at)
            VALUES('checked-1',?,?,?,1,'Glucose','numeric',5.1,'mmol/L','verified','native_text','Synthetic evidence','fixture',?)""", (owner, owner, created, utc_now()))
    service.receive(callback(7, "uy:" + batch))
    run_inbox(service)
    assert "your record already builds on it" in outputs(settings)[-1]["text"]
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        old = time.time() - 25 * 3600
        db.execute("UPDATE observations SET verification_status='extracted'")
        db.execute("UPDATE telegram_updates SET received_at=?", (old,))
    service.receive(callback(8, "uy:" + batch))
    run_inbox(service)
    assert "older than 24 hours" in outputs(settings)[-1]["text"]


def test_recent_uploads_account_help_and_unlink_from_the_chat(ledger):
    from anamna.ingest.intake import drain_now
    settings, owner, _, api, service = ledger
    link(service, owner)
    service.receive(incoming(2, "/uploads"))
    run_inbox(service)
    assert "Nothing uploaded yet." in outputs(settings)[-1]["text"]
    api.files["lab"] = real_pdf(*LAB)
    api.files["pdf"] = b"%PDF-1.4 still waiting"
    service.receive(file_part(3, "lab", "read.pdf", len(api.files["lab"])))
    run_inbox(service)
    drain_now(settings)
    service.receive(file_part(4, "pdf", "queued.pdf"))
    service.receive(incoming(5, "/uploads"))
    run_inbox(service)
    recent = outputs(settings)[-1]["text"]
    assert "<b>Recent uploads</b>" in recent
    assert "queued.pdf: waiting in the queue" in recent
    assert "read.pdf: added as" in recent and "Needs your review." in recent
    service.receive(incoming(6, "/account"))
    run_inbox(service)
    account = outputs(settings)[-1]
    assert "connected to the Anamna account owner (owner@example.com)" in account["text"]
    assert account["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "unlink"
    for uid, locale, expected in ((7, "en", "/uploads shows recent uploads"), (8, "uk", "/uploads показує останні завантаження")):
        with connect(settings) as db:
            db.execute("UPDATE telegram_links SET locale=?", (locale,))
        service.receive(incoming(uid, "/help"))
        run_inbox(service)
        assert expected in outputs(settings)[-1]["text"]
    with connect(settings) as db:
        db.execute("UPDATE telegram_links SET locale='en'")
    service.receive(incoming(9, "/unlink"))
    run_inbox(service)
    assert "Disconnect this chat from Anamna?" in outputs(settings)[-1]["text"]
    assert service.profile(owner)["linked"], "asking disconnects nothing"
    service.receive(callback(10, "unlink:yes"))
    run_inbox(service)
    assert not service.profile(owner)["linked"]
    with connect(settings) as db:
        left = db.execute("SELECT id,owner_user_id,method,payload FROM telegram_outbox WHERE state='pending'").fetchall()
        assert {row["id"] for row in left} == {"10:ack", "10:reply"}
        assert all(row["owner_user_id"] is None for row in left)
        assert "disconnected from Anamna" in json.loads([row for row in left if row["id"] == "10:reply"][0]["payload"])["text"]
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='telegram_unlinked'").fetchone()[0] == 1
    service.receive(incoming(11, "/menu"))
    run_inbox(service)
    assert "Connect this Telegram account" in outputs(settings)[-1]["text"]


def test_unsupported_media_joins_the_batch_with_a_reason(ledger):
    settings, owner, _, api, service = ledger
    link(service, owner)
    service.receive(album_part(2, video={"file_id": "v", "file_size": 100}))
    service.receive(album_part(3, voice={"file_id": "w", "file_size": 100}))
    run_inbox(service)
    assert not any(method == "getFile" for method, _, _ in api.calls), "nothing refused is downloaded"
    service.notify_uploads()
    summary = outputs(settings)[-1]["text"]
    assert "1. video.mp4: not added." in summary and "2. voice.ogg: not added." in summary


def test_long_batches_list_twenty_files_and_count_the_rest(ledger):
    settings, owner, _, _, service = ledger
    link(service, owner)
    for uid in range(2, 27):
        service.receive(file_part(uid, "x", f"note-{uid}.docx"))
    run_inbox(service)
    service.notify_uploads()
    summary = outputs(settings)[-1]["text"]
    assert "20. note-21.docx" in summary and "21. note-22.docx" not in summary
    assert "And 5 more files: the upload queue in Anamna lists them." in summary


@pytest.mark.parametrize("locale,count,expected", [
    ("en", 1, "scan.pdf: added as Synthetic &lt;report&gt;, 1 value."),
    ("en", 12, "scan.pdf: added as Synthetic &lt;report&gt;, 12 values."),
    ("uk", 3, "scan.pdf: додано як Synthetic &lt;report&gt;, 3 значення."),
    ("uk", 12, "scan.pdf: додано як Synthetic &lt;report&gt;, 12 значень."),
])
def test_added_line_counts_values_in_both_languages(ledger, locale, count, expected):
    settings, owner, _, api, service = ledger
    link(service, owner)
    with connect(settings) as db:
        db.execute("UPDATE telegram_links SET locale=?", (locale,))
    api.files["held"] = document(settings, owner)
    service.receive(file_part(2, "held", "scan.pdf", len(api.files["held"])))
    run_inbox(service)
    with connect(settings) as db:
        db.execute("UPDATE upload_jobs SET state='done',detail_key='intake.done_imported',observation_count=?", (count,))
    service.notify_uploads()
    assert expected in outputs(settings)[-1]["text"]
