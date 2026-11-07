"""Opt-in, owner-scoped Telegram companion with a durable inbox and outbox.

One SQLite lease serializes poll, inbox and delivery work across web processes.
Update handling and queue publication commit together. Delivery is at-least-once:
Telegram has no idempotency key for sendMessage, so a crash after a successful
send but before recording the acknowledgement can repeat that message.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote, urlsplit

from .config import Settings, env, resolve_source_path
from .db import connect, transaction, utc_now
from .devices.queries import device_metric_catalog, device_metric_values
from .health import concept_display_name
from .ingest.text import search_key
from .i18n import VISITOR_LOCALE, activate_locale, reset_locale, format_date_localized, format_number_localized, translate_phrase
from .locales.telegram import message
from .telegram_transport import ERR_CONNECTION, MAX_FILE_BYTES, TelegramAPI, TelegramError

PAGE_SIZE = 6
#: An idle worker (webhook mode, nothing queued) sleeps this long; a webhook
#: update wakes it at once, so this only bounds how late a timed retry starts.
IDLE_WAIT = 30.0
#: While an upload is being read, its progress message is checked this often.
UPLOAD_WAIT = 2.0
#: How often an idle webhook-mode worker asks Telegram whether the webhook is
#: still registered here, and how soon it asks again after that check failed.
WEBHOOK_CHECK_SECONDS = 6 * 3600
WEBHOOK_RETRY_SECONDS = 600
logger = logging.getLogger("anamna.telegram")
SQL_CONFIG = "SELECT * FROM telegram_config WHERE id=1"
SQL_ENABLED = "SELECT enabled FROM telegram_config WHERE id=1"
ERR_CONFIG = "telegram.error_config"
ERR_FILE = "telegram.error_file"
ERR_UNAVAILABLE = "telegram.unavailable"
#: Callback data of the first page of the metric and document lists.
CB_METRICS = "metrics:0"
CB_DOCS = "docs:0"
#: What each slash command opens.
_COMMAND_ACTIONS = {"/start": "home", "/menu": "home", "/cancel": "home", "/metrics": CB_METRICS, "/documents": CB_DOCS, "/search": "search", "/upload": "upload", "/language": "language", "/help": "help"}


def status_of(cfg) -> str:
    """One word for the admin badge, from the two stamps rather than the
    switch: ``off`` · ``waiting`` (on, never reached Telegram) · ``error``
    (the newest event is a failure) · ``warning`` (working, but a delivery
    is still failing) · ``ok``."""
    if not cfg["enabled"]:
        return "off"
    error, error_at, success_at = cfg["last_error"], cfg.get("last_error_at"), cfg["last_success_at"]
    if error and (not success_at or not error_at or error_at >= success_at):
        return "error"
    if error:
        return "warning"
    return "ok" if success_at else "waiting"


def _epoch(stamp):
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return 0.0
_ID = r"[A-Za-z0-9_-]{1,48}"
_CALLBACK = re.compile(rf"(?:home|help|upload|search|language|lang:(?:en|uk)|(?:docs|metrics|find):[0-9]{{1,5}}|(?:d|o|m|v):{_ID})\Z")


def _is_own_chat(msg, chat, sender) -> bool:
    """A private chat with a person (not a bot, group or business connection) talking as themselves."""
    return (chat.get("type") == "private" and type(chat.get("id")) is int and type(sender.get("id")) is int
            and sender.get("id") == chat.get("id") and not sender.get("is_bot") and not msg.get("business_connection_id"))


def _audit(db, owner, action, entity="telegram", entity_id="account"):
    db.execute("""INSERT INTO audit_events(owner_user_id,actor_user_id,action,entity_type,entity_id,details_json,created_at)
                  VALUES(?,?,?,?,?,'{}',?)""", (owner, owner, action, entity, entity_id, utc_now()))


def _button(text, data=None, url=None):
    return {"text": str(text)[:80], **({"url": url} if url else {"callback_data": data})}


class TelegramService:
    def __init__(self, settings: Settings, *, api_factory=TelegramAPI):
        self.settings, self.api_factory = settings, api_factory
        self.worker_id = uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread = None
        self._api = None
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self.idle_wait = IDLE_WAIT
        self._next_check = 0.0

    def token(self):
        return env("TELEGRAM_BOT_TOKEN", "").strip()

    def webhook_secret(self):
        return env("TELEGRAM_WEBHOOK_SECRET", "").strip()

    @property
    def api(self):
        if self._api is None:
            self._api = self.api_factory(self.token())
        return self._api

    def config(self):
        with connect(self.settings) as db:
            row = dict(db.execute(SQL_CONFIG).fetchone())
            row["linked_count"] = db.execute("SELECT COUNT(*) FROM telegram_links").fetchone()[0]
            row["pending_count"] = db.execute("SELECT COUNT(*) FROM telegram_updates WHERE state='pending'").fetchone()[0]
            row["delivery_count"] = db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE state='pending'").fetchone()[0]
        row["token_present"] = bool(self.token())
        row["status"] = status_of(row)
        return row

    def profile(self, owner):
        # Two reads on one connection: the admin counts in config() are not
        # this card's business, and /profile already opens enough connections.
        with connect(self.settings) as db:
            cfg = dict(db.execute(SQL_CONFIG).fetchone())
            row = db.execute("SELECT linked_at,locale FROM telegram_links WHERE owner_user_id=?", (owner,)).fetchone()
        return {"available": bool(self.token() or cfg["enabled"] or row), "enabled": bool(cfg["enabled"]), "username": cfg["bot_username"], "linked": bool(row), "linked_at": row["linked_at"] if row else None, "status": status_of(cfg)}

    def create_link(self, owner):
        token = secrets.token_urlsafe(32)
        with transaction(self.settings, immediate=True) as db:
            cfg = db.execute(SQL_CONFIG).fetchone()
            if not cfg["enabled"] or not cfg["bot_username"]:
                raise TelegramError("telegram.off", permanent=True)
            if db.execute("SELECT 1 FROM telegram_links WHERE owner_user_id=?", (owner,)).fetchone():
                raise TelegramError("telegram.link_invalid", permanent=True)
            db.execute("DELETE FROM telegram_link_tokens WHERE owner_user_id=? OR expires_at<?", (owner, time.time()))
            db.execute("INSERT INTO telegram_link_tokens VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), owner, time.time() + 600, utc_now()))
            _audit(db, owner, "telegram_link_requested")
            return f"https://t.me/{cfg['bot_username']}?start={token}"

    def unlink(self, owner):
        with transaction(self.settings, immediate=True) as db:
            db.execute("DELETE FROM telegram_link_tokens WHERE owner_user_id=?", (owner,))
            db.execute("DELETE FROM telegram_links WHERE owner_user_id=?", (owner,))
            db.execute("DELETE FROM telegram_outbox WHERE owner_user_id=?", (owner,))
            db.execute("DELETE FROM telegram_uploads WHERE owner_user_id=?", (owner,))
            _audit(db, owner, "telegram_unlinked")

    @staticmethod
    def _checked_config(enabled: bool, mode: str, public_url: str, webhook_secret: str) -> str:
        if mode not in {"polling", "webhook"}:
            raise TelegramError(ERR_CONFIG, permanent=True)
        public_url = public_url.strip().rstrip("/")
        parsed = urlsplit(public_url)
        if public_url and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise TelegramError(ERR_CONFIG, permanent=True)
        if enabled and mode == "webhook" and (not public_url or not re.fullmatch(r"[\w-]{32,256}", webhook_secret, re.ASCII)):
            raise TelegramError(ERR_CONFIG, permanent=True)
        return public_url

    def _register_bot(self, enabled: bool, mode: str, public_url: str, username: str) -> str:
        """Tell Telegram about the new configuration; returns the bot's username."""
        self._api = None
        if enabled:
            identity = self.api.call("getMe")
            username = str(identity.get("username", ""))
            if not identity.get("is_bot") or not re.fullmatch(r"\w{5,32}", username, re.ASCII):
                raise TelegramError("telegram.error_credentials", permanent=True)
            self._set_commands()
            self.api.call("setChatMenuButton", {"menu_button": {"type": "commands"}})
            if mode == "webhook":
                self.api.call("setWebhook", {"url": public_url + "/api/telegram/webhook", "secret_token": self.webhook_secret(), "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False})
            else:
                self.api.call("deleteWebhook", {"drop_pending_updates": False})
        elif self.token():
            self.api.call("deleteWebhook", {"drop_pending_updates": False})
        return username

    def _set_commands(self) -> None:
        # An omitted language_code supplies the fallback for clients
        # using another language or none: Ukrainian, the audience's.
        for locale in ("", "en", "uk"):
            command_menu = {
                "scope": {"type": "all_private_chats"},
                "commands": [{"command": command, "description": message(key, locale or VISITOR_LOCALE)} for command, key in (("start", "home"), ("menu", "home"), ("metrics", "metrics"), ("documents", "documents"), ("search", "search"), ("upload", "upload"), ("language", "language"), ("help", "help"), ("cancel", "cancel"))],
            }
            if locale:
                command_menu["language_code"] = locale
            self.api.call("setMyCommands", command_menu)

    def _store_config(self, enabled: bool, mode: str, public_url: str, username: str, current, actor: str) -> None:
        with transaction(self.settings, immediate=True) as db:
            # Switching to a different bot must never retain another bot's mappings.
            if current["bot_username"] and username != current["bot_username"]:
                db.execute("DELETE FROM telegram_links")
                db.execute("DELETE FROM telegram_link_tokens")
                db.execute("DELETE FROM telegram_outbox")
                db.execute("DELETE FROM telegram_updates")
                db.execute("UPDATE telegram_config SET poll_offset=0 WHERE id=1")
            db.execute("UPDATE telegram_config SET enabled=?,mode=?,public_url=?,bot_username=?,last_error=NULL,last_error_at=NULL,lease_owner=NULL,lease_until=0 WHERE id=1", (int(enabled), mode, public_url, username))
            _audit(db, actor, "telegram_configured")

    def configure(self, *, enabled: bool, mode: str, public_url: str, actor: str):
        public_url = self._checked_config(enabled, mode, public_url, self.webhook_secret())
        # Serialize the remote mode switch with the poller. Disabling locally
        # happens before external calls, so credential/network errors fail closed.
        if not enabled:
            with transaction(self.settings, immediate=True) as db:
                db.execute("UPDATE telegram_config SET enabled=0 WHERE id=1")
        self.stop()
        if self._thread and self._thread.is_alive():
            raise TelegramError("telegram.error_busy")
        with transaction(self.settings, immediate=True) as db:
            current = db.execute(SQL_CONFIG).fetchone()
            if current["lease_owner"] and current["lease_owner"] != self.worker_id and current["lease_until"] > time.time():
                raise TelegramError("telegram.error_busy")
            db.execute("UPDATE telegram_config SET enabled=0,lease_owner=?,lease_until=? WHERE id=1", (self.worker_id, time.time() + 600))
        try:
            username = self._register_bot(enabled, mode, public_url, current["bot_username"])
            self._store_config(enabled, mode, public_url, username, current, actor)
        except TelegramError as error:
            with transaction(self.settings, immediate=True) as db:
                db.execute("UPDATE telegram_config SET last_error=?,last_error_at=?,lease_owner=NULL,lease_until=0 WHERE id=1", (error.key, utc_now()))
            raise
        finally:
            self.start()

    def receive(self, update: dict, *, webhook_secret: str | None = None):
        cfg = self.config()
        if not cfg["enabled"]:
            raise TelegramError("telegram.off", permanent=True)
        if webhook_secret is not None:
            secret = self.webhook_secret()
            if cfg["mode"] != "webhook" or not secret or not hmac.compare_digest(secret, webhook_secret):
                raise TelegramError("telegram.error_credentials", permanent=True)
        uid = update.get("update_id")
        raw = json.dumps(update, ensure_ascii=False)
        if type(uid) is not int or uid < 0 or len(raw.encode()) > 262144:
            raise ValueError("invalid Telegram update")
        with transaction(self.settings, immediate=True) as db:
            inserted = db.execute("INSERT OR IGNORE INTO telegram_updates(update_id,payload,received_at) VALUES(?,?,?)", (uid, raw, time.time())).rowcount
        if inserted:
            self.wake()
        return bool(inserted)

    def _queue(self, db, update_id, owner, chat, text, buttons=None, *, suffix="reply", method="sendMessage", extra=None, edit_message_id=None):
        # An unusually long extracted value can expand HTML entities fourfold.
        # Fall back to bounded plain text rather than cutting an entity/tag.
        plain = len(text.encode("utf-16-le")) > 7800
        if plain:
            text = unescape(re.sub(r"<[^>]+>", "", text)).encode("utf-16-le")[:7800].decode("utf-16-le", errors="ignore")
        payload = {"chat_id": chat, "text": text, "parse_mode": "HTML", "protect_content": True, "link_preview_options": {"is_disabled": True}}
        if plain:
            payload.pop("parse_mode", None)
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        if extra is not None:
            payload = extra
        elif edit_message_id is not None:
            method = "editMessageText"
            payload["message_id"] = edit_message_id
            payload.pop("protect_content", None)
        db.execute("INSERT OR IGNORE INTO telegram_outbox(id,owner_user_id,chat_id,method,payload,created_at) VALUES(?,?,?,?,?,?)", (f"{update_id}:{suffix}", owner, chat, method, json.dumps(payload, ensure_ascii=False), time.time()))

    def _home(self, locale):
        return [[_button(message("metrics", locale), CB_METRICS), _button(message("documents", locale), CB_DOCS)], [_button(message("search", locale), "search"), _button(message("upload", locale), "upload")], [_button(message("language", locale), "language"), _button(message("help", locale), "help")]]

    def _nav(self, locale, back="home"):
        return [[_button(message("back", locale), back), _button(message("home", locale), "home")]]

    def _url(self, db, path):
        base = db.execute("SELECT public_url FROM telegram_config WHERE id=1").fetchone()[0]
        return base + path if base else None

    def _document(self, db, owner, document_id, locale):
        row = db.execute("SELECT * FROM documents WHERE owner_user_id=? AND id=?", (owner, document_id)).fetchone()
        if not row:
            return message("unavailable", locale), self._nav(locale)
        text = f"<b>{escape(row['title'][:200])}</b>\n{escape(row['original_filename'][:180])}\n{message('date', locale)}: {escape(format_date_localized(row['report_date']))}\n{escape(row['mime_type'])} · {format_number_localized(row['byte_size'] / 1024, 1)} KB\n\n{message('original_hint', locale)}"
        buttons = [[_button(message("original", locale), "o:" + document_id)]]
        url = self._url(db, "/documents/" + quote(document_id))
        if url:
            buttons.append([_button(message("open_record", locale), url=url)])
        return text, buttons + self._nav(locale, CB_DOCS)

    def _metric(self, db, owner, row_id, locale, device=False):
        if device:
            return self._device_metric(db, owner, row_id, locale)
        held = db.execute("SELECT * FROM observations WHERE owner_user_id=? AND id=? AND verification_status<>'rejected'", (owner, row_id)).fetchone()
        if not held:
            return message("unavailable", locale), self._nav(locale)
        rows = db.execute("""SELECT o.*,c.canonical_name,d.title document_title,d.report_date source_date FROM observations o LEFT JOIN concepts c ON c.id=o.concept_id
            JOIN documents d ON d.id=o.document_id AND d.owner_user_id=o.owner_user_id WHERE o.owner_user_id=? AND o.verification_status<>'rejected'
            AND (o.concept_id=? OR (o.concept_id IS NULL AND o.raw_name=?)) AND COALESCE(NULLIF(o.unit_canonical,''),o.unit_raw,'')=?
            ORDER BY COALESCE(o.observed_at,d.report_date,o.created_at) DESC LIMIT 6""", (owner, held["concept_id"], held["raw_name"], held["unit_canonical"] or held["unit_raw"] or "")).fetchall()
        if not rows:
            return message("unavailable", locale), self._nav(locale)
        text = "<b>" + escape(concept_display_name(rows[0]["canonical_name"] or rows[0]["raw_name"])[:160]) + "</b>"
        buttons = []
        for row in rows:
            text += self._metric_line(row, locale)
            if len(buttons) < 3 and row["document_id"] not in [item[0]["callback_data"][2:] for item in buttons]:
                buttons.append([_button(row["document_title"], "d:" + row["document_id"])])
        return text, buttons + self._nav(locale, CB_METRICS)

    @staticmethod
    def _metric_line(row, locale) -> str:
        value = format_number_localized(row["value_numeric"]) if row["value_numeric"] is not None else row["value_text"]
        line = f"\n\n{escape(format_date_localized(row['observed_at'] or row['source_date']))}: <b>{escape(str(row['comparator'] or ''))}{escape(str(value)[:150])} {escape(str(row['unit_canonical'] or row['unit_raw'] or ''))}</b>\n{message('verified' if row['verification_status'] == 'verified' else 'provisional', locale)}\n{message('source', locale)}: {escape(row['document_title'][:120])}"
        if row["vendor_reference_text"]:
            line += "\n" + message("reference", locale) + ": " + escape(row["vendor_reference_text"][:120])
        return line

    def _device_metric(self, db, owner, row_id, locale):
        held = db.execute("SELECT metric_key FROM device_metric_days WHERE owner_user_id=? AND id=?", (owner, row_id)).fetchone()
        rows = device_metric_values(db, owner, held[0])[:6] if held else []
        if not rows:
            return message("unavailable", locale), self._nav(locale)
        text = "<b>" + escape(translate_phrase(rows[0]["metric_name"])[:160]) + "</b>\n" + message("device", locale)
        for row in rows:
            text += f"\n\n{escape(format_date_localized(row['day']))}: <b>{format_number_localized(row['value'])} {escape(str(row['unit'] or '')[:40])}</b>\n{message('source', locale)}: {escape(str(row['source_name'])[:120])}"
        buttons = []
        url = self._url(db, "/devices/metrics/" + quote(held[0]))
        if url:
            buttons.append([_button(message("open_record", locale), url=url)])
        return text, buttons + self._nav(locale, CB_METRICS)

    @staticmethod
    def _metric_items(db, owner, query):
        items = []
        rows = db.execute("""SELECT o.*,c.canonical_name FROM observations o LEFT JOIN concepts c ON c.id=o.concept_id
            WHERE o.owner_user_id=? AND o.verification_status<>'rejected' ORDER BY o.observed_at DESC,o.created_at DESC""", (owner,)).fetchall()
        seen = set()
        for row in rows:
            name = concept_display_name(row["canonical_name"] or row["raw_name"])
            value = format_number_localized(row["value_numeric"]) if row["value_numeric"] is not None else str(row["value_text"] or "")
            key = (row["concept_id"] or row["raw_name"], row["unit_canonical"] or row["unit_raw"])
            if key in seen or query and query.casefold() not in (name + " " + row["raw_name"] + " " + value).casefold():
                continue
            seen.add(key)
            items.append((name, "m:" + row["id"], value + " " + str(key[1] or "")))
        return items + TelegramService._device_items(db, owner, query)

    @staticmethod
    def _device_items(db, owner, query):
        items = []
        for card in device_metric_catalog(db, owner, query=query):
            key = str(card["id"]).removeprefix("device:")
            held = db.execute("SELECT id FROM device_metric_days WHERE owner_user_id=? AND metric_key=? LIMIT 1", (owner, key)).fetchone()
            if held:
                items.append((str(card["name"]), "v:" + str(held[0]), format_number_localized(card["latest_numeric"]) + " " + str(card["unit"] or "")))
        return items

    @staticmethod
    def _document_items(db, owner, query):
        items = []
        for row in db.execute("""SELECT d.id,d.title,d.original_filename,d.report_date,s.content FROM documents d
            LEFT JOIN search_index s ON s.document_id=d.id AND s.owner_user_id=d.owner_user_id
            WHERE d.owner_user_id=? ORDER BY d.report_date DESC,d.imported_at DESC""", (owner,)):
            if not query or search_key(query) in search_key(row["title"] + " " + row["original_filename"] + " " + (row["content"] or "")):
                items.append((row["title"], "d:" + row["id"], format_date_localized(row["report_date"])))
        return items

    def _listing(self, db, owner, kind, page, locale, query=""):
        items = []
        if kind in {"metrics", "find"}:
            items += self._metric_items(db, owner, query)
        if kind in {"docs", "find"}:
            items += self._document_items(db, owner, query)
        chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        title = message({"docs": "documents", "find": "search"}.get(kind, "metrics"), locale)
        text = "<b>" + title + "</b>" + ("\n" + escape(query) if query else "")
        buttons = []
        for name, callback, detail in chunk:
            text += "\n\n" + escape(name[:120]) + "\n" + escape(detail[:120])
            buttons.append([_button(name, callback)])
        if not chunk:
            text += "\n" + message("empty", locale)
        pagination = []
        if page:
            pagination.append(_button(message("previous", locale), f"{kind}:{page - 1}"))
        if len(items) > (page + 1) * PAGE_SIZE:
            pagination.append(_button(message("next", locale), f"{kind}:{page + 1}"))
        return text, buttons + ([pagination] if pagination else []) + self._nav(locale)

    @staticmethod
    def _upload_info(file):
        filename = str(file.get("file_name") or "photo.jpg").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".zip"}:
            raise TelegramError("telegram.error_type", permanent=True)
        if int(file.get("file_size", 0)) > MAX_FILE_BYTES:
            raise TelegramError("telegram.error_size", permanent=True)
        return filename, suffix

    def _upload(self, db, update_id, owner, chat, file, data, written_paths):
        filename, suffix = self._upload_info(file)
        patient = db.execute("SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (owner,)).fetchone()
        if not patient:
            raise TelegramError(ERR_UNAVAILABLE, permanent=True)
        if not data or len(data) > MAX_FILE_BYTES:
            raise TelegramError("telegram.error_size", permanent=True)
        # Validate claimed type before publishing bytes into the trusted intake queue.
        signatures = {".pdf": (b"%PDF-",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG\r\n\x1a\n",), ".tif": (b"II*\0", b"MM\0*"), ".tiff": (b"II*\0", b"MM\0*"), ".zip": (b"PK\x03\x04", b"PK\x05\x06")}
        if not data.startswith(signatures[suffix]):
            raise TelegramError("telegram.error_type", permanent=True)
        received_at = db.execute("SELECT received_at FROM telegram_updates WHERE update_id=?", (update_id,)).fetchone()[0]
        identity = hashlib.sha256(f"{owner}:{update_id}:{received_at}".encode()).hexdigest()[:20]
        batch = "telegram-" + identity
        held = db.execute("SELECT id FROM documents WHERE owner_user_id=? AND sha256=? ORDER BY imported_at LIMIT 1", (owner, hashlib.sha256(data).hexdigest())).fetchone()
        # Keep an intelligible original filename without trusting it as a path.
        # The inbox receipt identity also prevents a replacement bot's reused
        # update IDs from overwriting an older bot's original source document.
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")[:160]
        if not safe_name or safe_name.startswith(".") or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", Path(safe_name).stem, re.IGNORECASE):
            safe_name = "scan" + suffix
        if not safe_name.lower().endswith(suffix):
            safe_name = Path(safe_name).stem[:140] + suffix
        target = self.settings.source_dir / "uploads" / utc_now()[:7] / batch / safe_name
        state, detail = ("skipped", "intake.done_duplicate") if held else ("queued", "intake.step_waiting")
        if not held:
            target.parent.mkdir(parents=True, exist_ok=True)
            written_paths.append(target)
            target.write_bytes(data)
        db.execute("""INSERT INTO upload_jobs(id,owner_user_id,patient_id,batch_id,kind,filename,source_path,byte_size,state,detail_key,document_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (batch, owner, patient[0], batch, "archive" if suffix == ".zip" else "document", filename[:240], str(target) if not held else None, len(data), state, detail, held[0] if held else None, utc_now()))
        db.execute("INSERT INTO telegram_uploads(update_id,owner_user_id,chat_id,batch_id) VALUES(?,?,?,?)", (update_id, owner, chat, batch))
        _audit(db, owner, "telegram_upload_queued", "upload_job", batch)

    def _claim_update(self):
        """The next inbox update, marked as being processed; None when there is none."""
        with transaction(self.settings, immediate=True) as db:
            if not db.execute(SQL_ENABLED).fetchone()[0]:
                return None
            row = db.execute("SELECT * FROM telegram_updates WHERE state IN ('pending','processing') AND available_at<=? ORDER BY update_id LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE telegram_updates SET state='processing',available_at=? WHERE update_id=?", (time.time() + 180, row["update_id"]))
        return row

    def _prefetch(self, row):
        """Everything that needs the network, before the write transaction:
        ``(update, snapshot of the sender's link, downloaded file, error)``."""
        update, downloaded, snapshot, error = None, None, None, None
        try:
            update = json.loads(row["payload"])
            msg = update.get("message", {})
            file = msg.get("document") or (msg.get("photo") or [None])[-1]
            chat, sender = msg.get("chat", {}), msg.get("from", {})
            if file and chat.get("type") == "private" and type(sender.get("id")) is int and sender.get("id") == chat.get("id") and not sender.get("is_bot") and not msg.get("business_connection_id"):
                with connect(self.settings) as db:
                    held = db.execute("""SELECT l.* FROM telegram_links l JOIN users u ON u.id=l.owner_user_id
                        WHERE l.chat_id=? AND l.telegram_user_id=? AND u.disabled_at IS NULL""", (chat["id"], sender["id"])).fetchone()
                    snapshot = dict(held) if held else None
                if snapshot:
                    self._upload_info(file)
                    # Telegram network I/O deliberately holds no SQLite transaction.
                    downloaded = self.api.download(str(file["file_id"]))
        except TelegramError as exc:
            error = exc
        except (ValueError, TypeError, KeyError, AttributeError):
            error = TelegramError(ERR_FILE, permanent=True)
        return update, snapshot, downloaded, error

    def _handle_update(self, db, update_id, update, downloaded, written_paths):
        """Handle one update; the error it ended in, or None."""
        try:
            self._handle(db, update_id, update, downloaded, written_paths)
        except TelegramError as exc:
            return exc
        except (ValueError, TypeError, KeyError, AttributeError):
            return TelegramError(ERR_FILE, permanent=True)
        return None

    @staticmethod
    def _retry_update(db, row, error) -> bool:
        """Put a failed update back for a later attempt; False when it is final."""
        if error.permanent or row["attempts"] >= 8:
            return False
        db.execute("UPDATE telegram_updates SET state='pending',attempts=attempts+1,available_at=?,error_key=? WHERE update_id=?", (time.time() + (error.retry_after or min(300, 2 ** min(row["attempts"], 8))), error.key, row["update_id"]))
        return True

    def process_one(self):
        row = self._claim_update()
        if row is None:
            return False
        update_id = row["update_id"]
        update, snapshot, downloaded, error = self._prefetch(row)
        written_paths = []
        try:
            with transaction(self.settings, immediate=True) as db:
                if not db.execute(SQL_ENABLED).fetchone()[0]:
                    db.execute("UPDATE telegram_updates SET state='pending',available_at=0 WHERE update_id=?", (update_id,))
                    return True
                if snapshot and not db.execute("""SELECT 1 FROM telegram_links l JOIN users u ON u.id=l.owner_user_id
                    WHERE l.owner_user_id=? AND l.chat_id=? AND l.linked_at=? AND u.disabled_at IS NULL""", (snapshot["owner_user_id"], snapshot["chat_id"], snapshot["linked_at"])).fetchone():
                    db.execute("UPDATE telegram_updates SET state='done',payload='{}' WHERE update_id=?", (update_id,))
                    return True
                if error is None:
                    error = self._handle_update(db, update_id, update, downloaded, written_paths)
                if error:
                    if self._retry_update(db, row, error):
                        return True
                    if snapshot:
                        self._queue(db, update_id, snapshot["owner_user_id"], snapshot["chat_id"], message(error.key.removeprefix("telegram."), snapshot["locale"]), self._nav(snapshot["locale"]))
                db.execute("UPDATE telegram_updates SET state='done',payload='{}',error_key=? WHERE update_id=?", (error.key if error else None, update_id))
        except Exception:
            # These exact paths were created for this receipt, beneath source_dir.
            # Rollback must not leave a source file without its intake/audit row.
            for path in written_paths:
                path.unlink(missing_ok=True)
            raise
        from .ingest.intake import start_worker
        start_worker(self.settings)
        return True

    def _redeem_link(self, db, update_id, text, sender, chat_id, locale, link):
        """``/start <token>``: the link made, or None after telling the sender it is invalid."""
        token = text.partition(" ")[2].strip()
        held = db.execute("SELECT t.* FROM telegram_link_tokens t JOIN users u ON u.id=t.owner_user_id WHERE token_hash=? AND expires_at>? AND u.disabled_at IS NULL", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone() if re.fullmatch(r"[\w-]{40,64}", token, re.ASCII) else None
        if held and not link and not db.execute("SELECT 1 FROM telegram_links WHERE owner_user_id=? OR telegram_user_id=? OR chat_id=?", (held["owner_user_id"], sender["id"], chat_id)).fetchone():
            db.execute("INSERT INTO telegram_links(owner_user_id,telegram_user_id,chat_id,locale,linked_at) VALUES(?,?,?,?,?)", (held["owner_user_id"], sender["id"], chat_id, locale, utc_now()))
            db.execute("DELETE FROM telegram_link_tokens WHERE owner_user_id=?", (held["owner_user_id"],))
            _audit(db, held["owner_user_id"], "telegram_linked")
            return db.execute("SELECT * FROM telegram_links WHERE owner_user_id=?", (held["owner_user_id"],)).fetchone()
        self._queue(db, update_id, None, chat_id, message("link_invalid", locale))
        return None

    def _callback_action(self, db, update_id, owner, chat_id, callback, locale):
        """The button pressed, or None when it was refused."""
        self._queue(db, update_id, owner, chat_id, "", suffix="ack", method="answerCallbackQuery", extra={"callback_query_id": str(callback.get("id", ""))[:256]})
        action = str(callback.get("data", ""))
        if len(action.encode()) > 64 or not _CALLBACK.fullmatch(action):
            self._queue(db, update_id, owner, chat_id, message("unavailable", locale), self._nav(locale))
            return None
        return action

    def _message_action(self, db, update_id, owner, chat_id, msg, link, locale, downloaded, written_paths):
        """The action a typed message asks for, or None when it was an upload (already queued)."""
        text = str(msg.get("text", ""))
        command = text.split(" ", 1)[0].split("@", 1)[0]
        action = _COMMAND_ACTIONS.get(command, "home")
        file = msg.get("document") or (msg.get("photo") or [None])[-1]
        if file:
            self._upload(db, update_id, owner, chat_id, file, downloaded, written_paths if written_paths is not None else [])
            self._queue(db, update_id, owner, chat_id, message("queued", locale), self._nav(locale))
            return None
        if not text.startswith("/") and link["state"] == "search":
            if not 2 <= len(text.strip()) <= 100:
                return "search"
            db.execute("UPDATE telegram_links SET search_query=?,state='' WHERE owner_user_id=?", (text.strip(), owner))
            return "find:0"
        return action

    def _language_card(self, db, owner, action, locale):
        if action.startswith("lang:"):
            locale = action.split(":")[1]
            db.execute("UPDATE telegram_links SET locale=? WHERE owner_user_id=?", (locale, owner))
        return message("language", locale), [[_button("English", "lang:en"), _button("Українська", "lang:uk")]] + self._nav(locale)

    def _original(self, db, update_id, owner, chat_id, document_id, locale):
        """Queue the original file; the card to show instead when it is gone."""
        document = db.execute("SELECT id FROM documents WHERE owner_user_id=? AND id=?", (owner, document_id)).fetchone()
        if not document:
            return message("unavailable", locale), self._nav(locale)
        self._queue(db, update_id, owner, chat_id, "", method="sendDocument", extra={"chat_id": chat_id, "document_id": document["id"], "protect_content": True})
        _audit(db, owner, "telegram_original_requested", "document", document["id"])
        return None

    def _card_for(self, db, update_id, owner, chat_id, action, locale):
        """The card an action opens as ``(text, buttons)``; None when a file was queued instead."""
        if action == "home":
            db.execute("UPDATE telegram_links SET state='' WHERE owner_user_id=?", (owner,))
            return message("welcome", locale), self._home(locale)
        if action in {"search", "upload"}:
            db.execute("UPDATE telegram_links SET state=? WHERE owner_user_id=?", (action, owner))
            return message(action + "_prompt", locale), self._nav(locale)
        if action == "help":
            return message("lead", locale) + "\n\n" + message("privacy", locale) + "\n\n" + message("upload_prompt", locale) + "\n/menu · /search · /metrics · /documents · /language · /cancel", self._nav(locale)
        if action == "language" or action.startswith("lang:"):
            return self._language_card(db, owner, action, locale)
        if action.startswith(("docs:", "metrics:", "find:")):
            kind, page = action.split(":")
            query = db.execute("SELECT search_query FROM telegram_links WHERE owner_user_id=?", (owner,)).fetchone()[0] if kind == "find" else ""
            return self._listing(db, owner, kind, int(page), locale, query)
        if action.startswith("d:"):
            return self._document(db, owner, action[2:], locale)
        if action.startswith(("m:", "v:")):
            return self._metric(db, owner, action[2:], locale, action.startswith("v:"))
        if action.startswith("o:"):
            return self._original(db, update_id, owner, chat_id, action[2:], locale)
        return message("welcome", locale), self._home(locale)

    def _handle(self, db, update_id, update, downloaded=None, written_paths=None):
        callback = update.get("callback_query")
        msg = callback.get("message", {}) if callback else update.get("message", {})
        sender = callback.get("from", {}) if callback else msg.get("from", {})
        chat = msg.get("chat", {})
        # Never use guest/business/group/inline messages to identify an owner.
        if not _is_own_chat(msg, chat, sender):
            return
        chat_id = chat["id"]
        locale = "en" if str(sender.get("language_code", "")).startswith("en") else VISITOR_LOCALE
        text = str(msg.get("text", ""))
        link = db.execute("SELECT l.* FROM telegram_links l JOIN users u ON u.id=l.owner_user_id WHERE telegram_user_id=? AND chat_id=? AND u.disabled_at IS NULL", (sender["id"], chat_id)).fetchone()
        if not callback and text.startswith("/start "):
            link = self._redeem_link(db, update_id, text, sender, chat_id, locale, link)
            if link is None:
                return
            msg = {**msg, "text": "/menu"}
        if not link:
            self._queue(db, update_id, None, chat_id, message("link_required", locale))
            return
        owner, locale = link["owner_user_id"], link["locale"]
        context = activate_locale(locale)
        try:
            if callback:
                action = self._callback_action(db, update_id, owner, chat_id, callback, locale)
            else:
                action = self._message_action(db, update_id, owner, chat_id, msg, link, locale, downloaded, written_paths)
            card = self._card_for(db, update_id, owner, chat_id, action, locale) if action else None
            if card is not None:
                self._queue(db, update_id, owner, chat_id, card[0], card[1], edit_message_id=msg.get("message_id") if callback else None)
        finally:
            reset_locale(context)

    @staticmethod
    def _upload_notices(db):
        """Telegram uploads whose progress message is due, as (upload, jobs, state),
        plus whether any upload is still in flight.  Read-only."""
        notices, in_flight = [], False
        for upload in db.execute("SELECT u.*,l.locale FROM telegram_uploads u JOIN telegram_links l ON l.owner_user_id=u.owner_user_id AND l.chat_id=u.chat_id WHERE notified_state<>'done'").fetchall():
            jobs = db.execute("SELECT state,document_id FROM upload_jobs WHERE owner_user_id=? AND batch_id=?", (upload["owner_user_id"], upload["batch_id"])).fetchall()
            if not jobs:
                continue
            in_flight = True
            state = "processing" if any(job["state"] in {"queued", "running"} for job in jobs) else "done"
            if state == upload["notified_state"] or state == "processing" and all(job["state"] == "queued" for job in jobs):
                continue
            notices.append((upload, jobs, state))
        return notices, in_flight

    @staticmethod
    def _notice_key(state, jobs):
        if state == "processing":
            return "processing"
        return "upload_failed" if any(job["state"] == "failed" for job in jobs) else "upload_done"

    def notify_uploads(self):
        with transaction(self.settings, immediate=True) as db:
            for upload, jobs, state in self._upload_notices(db)[0]:
                locale = upload["locale"]
                key = self._notice_key(state, jobs)
                ids = list(dict.fromkeys(job["document_id"] for job in jobs if job["document_id"]))
                buttons = []
                for document_id in ids[:6]:
                    doc = db.execute("SELECT title FROM documents WHERE id=? AND owner_user_id=?", (document_id, upload["owner_user_id"])).fetchone()
                    if doc:
                        buttons.append([_button(doc[0], "d:" + document_id)])
                url = self._url(db, "/upload")
                if url:
                    buttons.append([_button(message("queue", locale), url=url)])
                self._queue(db, upload["update_id"], upload["owner_user_id"], upload["chat_id"], message(key, locale), buttons + self._nav(locale), suffix=state)
                db.execute("UPDATE telegram_uploads SET notified_state=? WHERE update_id=?", (state, upload["update_id"]))

    @staticmethod
    def _delivery_error(db):
        row = db.execute("""SELECT error_key FROM telegram_outbox
            WHERE error_key IS NOT NULL AND state IN ('pending','sending','failed')
            ORDER BY CASE WHEN state='failed' THEN 1 ELSE 0 END, available_at DESC LIMIT 1""").fetchone()
        return row[0] if row else None

    def _record_success(self, db):
        # Proof of connectivity.  An unresolved delivery failure stays on
        # record (with the time it was first written); anything else clears.
        remaining = self._delivery_error(db)
        db.execute("""UPDATE telegram_config SET last_success_at=?,last_error=?,
            last_error_at=CASE WHEN ? IS NULL THEN NULL ELSE last_error_at END WHERE id=1""",
            (utc_now(), remaining, remaining))

    def _claim_delivery(self):
        """Claim durably, then release the write lock before contacting Telegram."""
        with transaction(self.settings, immediate=True) as db:
            if not db.execute(SQL_ENABLED).fetchone()[0]:
                return None
            row = db.execute("SELECT * FROM telegram_outbox WHERE state IN ('pending','sending') AND available_at<=? ORDER BY created_at,id LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE telegram_outbox SET state='sending',available_at=? WHERE id=?", (time.time() + 180, row["id"]))
        return row

    def _send(self, row, payload) -> bool:
        """Send one queued message.  True when nothing was sent because it was
        cancelled or the bot is off; errors are raised."""
        document = None
        # This read is immediately before the send. Revocation can cancel
        # queued work, but cannot recall an already in-flight HTTP request.
        with connect(self.settings) as db:
            enabled = db.execute(SQL_ENABLED).fetchone()[0]
            authorized = not row["owner_user_id"] or db.execute("SELECT 1 FROM telegram_links l JOIN users u ON u.id=l.owner_user_id WHERE l.owner_user_id=? AND l.chat_id=? AND u.disabled_at IS NULL", (row["owner_user_id"], row["chat_id"])).fetchone()
            retained = db.execute("SELECT 1 FROM telegram_outbox WHERE id=?", (row["id"],)).fetchone()
            if row["method"] == "sendDocument":
                source = db.execute("SELECT source_path FROM documents WHERE owner_user_id=? AND id=?", (row["owner_user_id"], payload.pop("document_id"))).fetchone()
                if not source:
                    raise TelegramError(ERR_UNAVAILABLE, permanent=True)
                document = resolve_source_path(self.settings, source[0])
        if not authorized or not retained:
            with transaction(self.settings, immediate=True) as db:
                db.execute("DELETE FROM telegram_outbox WHERE id=?", (row["id"],))
            return True
        if not enabled:
            with transaction(self.settings, immediate=True) as db:
                db.execute("UPDATE telegram_outbox SET state='pending',available_at=0 WHERE id=?", (row["id"],))
            return True
        if document and (not document.is_file() or not document.resolve().is_relative_to(self.settings.source_dir.resolve())):
            raise TelegramError(ERR_UNAVAILABLE, permanent=True)
        self.api.call(row["method"], payload, **({"document": document} if document else {}))
        return False

    def _mark_sent(self, db, row):
        db.execute("UPDATE telegram_outbox SET state='sent',payload='{}',error_key=NULL WHERE id=?", (row["id"],))
        # A later successful request proves this delivery route recovered.
        # Retain terminal failure history explicitly, so a subsequent poll
        # error with the same key cannot make it active again. Other chats,
        # API methods and deliveries still awaiting retry remain unresolved.
        db.execute("""UPDATE telegram_outbox SET state='failed_historical'
            WHERE state='failed' AND owner_user_id IS ? AND chat_id=?
                AND method=? AND created_at<=?""",
            (row["owner_user_id"], row["chat_id"], row["method"], row["created_at"]))
        self._record_success(db)

    def _mark_failed(self, db, row, payload, error):
        failed = error.permanent or row["attempts"] >= 9
        db.execute("UPDATE telegram_outbox SET state=?,attempts=attempts+1,available_at=?,error_key=?,payload=CASE WHEN ? THEN '{}' ELSE payload END WHERE id=?", ("failed" if failed else "pending", time.time() + (error.retry_after or min(300, 2 ** min(row["attempts"], 8))), error.key, int(failed), row["id"]))
        db.execute("UPDATE telegram_config SET last_error=?,last_error_at=? WHERE id=1", (error.key, utc_now()))
        if failed and row["method"] == "sendDocument":
            link = db.execute("SELECT locale FROM telegram_links WHERE owner_user_id=?", (row["owner_user_id"],)).fetchone()
            if link:
                self._queue(db, row["id"], row["owner_user_id"], row["chat_id"], message(error.key.removeprefix("telegram."), link[0]), self._nav(link[0]), suffix="error")
        elif failed and row["method"] == "editMessageText":
            payload.pop("message_id", None)
            payload["protect_content"] = True
            self._queue(db, row["id"], row["owner_user_id"], row["chat_id"], "", extra=payload, suffix="new-card")

    def deliver_one(self):
        row = self._claim_delivery()
        if row is None:
            return False
        error = None
        payload = json.loads(row["payload"])
        try:
            if self._send(row, payload):
                return True
        except TelegramError as exc:
            error = exc
        except (OSError, ValueError, KeyError):
            error = TelegramError(ERR_FILE, permanent=True)
        with transaction(self.settings, immediate=True) as db:
            if not db.execute("SELECT 1 FROM telegram_outbox WHERE id=?", (row["id"],)).fetchone():
                return True
            if error is None:
                self._mark_sent(db, row)
            else:
                self._mark_failed(db, row, payload, error)
        return True

    def _due(self, now=None):
        """What the worker has to do right now, decided without a write.

        Idle used to mean a write lock plus two lease UPDATEs every half
        second; reading first is what keeps an idle bot off the disk.  The
        result also says how long an idle worker may sleep before something
        becomes due on its own (a retry whose back-off ends, an upload whose
        progress is worth reporting).
        """
        now = time.time() if now is None else now
        with connect(self.settings) as db:
            cfg = db.execute(SQL_CONFIG).fetchone()
            if not cfg["enabled"] or cfg["lease_owner"] not in {None, self.worker_id} and cfg["lease_until"] > now:
                return {"due": False, "queued_upload": False, "notices": False, "wait": IDLE_WAIT}
            upcoming = db.execute("""SELECT MIN(available_at) FROM (
                SELECT available_at FROM telegram_updates WHERE state IN ('pending','processing')
                UNION ALL SELECT available_at FROM telegram_outbox WHERE state IN ('pending','sending'))""").fetchone()[0]
            notices, in_flight = self._upload_notices(db)
            queued_upload = bool(db.execute("""SELECT 1 FROM upload_jobs j JOIN telegram_uploads t
                ON t.batch_id=j.batch_id AND t.owner_user_id=j.owner_user_id WHERE j.state='queued' LIMIT 1""").fetchone())
        wait = IDLE_WAIT
        if upcoming is not None:
            wait = min(wait, max(0.0, upcoming - now))
        if in_flight:
            wait = min(wait, UPLOAD_WAIT)
        # Webhook mode has no poll to prove the route works, and an idle bot
        # delivers nothing: without an occasional check the status would show
        # whatever happened weeks ago.  One getWebhookInfo, never more often
        # than WEBHOOK_CHECK_SECONDS (or the shorter retry after a failure).
        check = cfg["mode"] == "webhook" and now >= self._next_check
        if cfg["mode"] == "webhook":
            wait = min(wait, max(0.0, self._next_check - now))
        if cfg["mode"] == "polling":
            wait = 0.0  # the 10-second long poll is the pacing; a failed poll retries promptly
        due = cfg["mode"] == "polling" or check or bool(notices) or (upcoming is not None and upcoming <= now)
        return {"due": due, "queued_upload": queued_upload, "notices": bool(notices), "check": check, "wait": wait}

    def _take_lease(self):
        """The config row once this worker holds the lease; None when it is off or another worker has it."""
        with transaction(self.settings, immediate=True) as db:
            cfg = db.execute(SQL_CONFIG).fetchone()
            if not cfg["enabled"] or cfg["lease_owner"] not in {None, self.worker_id} and cfg["lease_until"] > time.time():
                return None
            db.execute("UPDATE telegram_config SET lease_owner=?,lease_until=? WHERE id=1", (self.worker_id, time.time() + 180))
        return cfg

    def _check_webhook(self, cfg):
        """Ask Telegram whether the webhook is still registered here."""
        self._next_check = time.time() + WEBHOOK_RETRY_SECONDS
        info = self.api.call("getWebhookInfo")
        if not isinstance(info, dict):
            raise TelegramError(ERR_CONNECTION)
        if info.get("url") != cfg["public_url"] + "/api/telegram/webhook":
            raise TelegramError("telegram.error_conflict")
        with transaction(self.settings, immediate=True) as db:
            self._record_success(db)
        self._next_check = time.time() + WEBHOOK_CHECK_SECONDS

    def _poll(self, cfg) -> int:
        """One long poll; the number of updates stored."""
        updates = self.api.call("getUpdates", {"offset": cfg["poll_offset"], "timeout": 10, "limit": 20, "allowed_updates": ["message", "callback_query"]})
        if not isinstance(updates, list) or any(
            not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < 0
            for update in updates
        ):
            raise TelegramError(ERR_CONNECTION)
        for update in updates:
            try:
                self.receive(update)
            except (TypeError, ValueError, OverflowError):
                raise TelegramError(ERR_CONNECTION) from None
            with transaction(self.settings, immediate=True) as db:
                db.execute("UPDATE telegram_config SET poll_offset=MAX(poll_offset,?) WHERE id=1", (update["update_id"] + 1,))
        with transaction(self.settings, immediate=True) as db:
            # A successful empty poll is still proof of connectivity.
            # Active outbox failures remain visible independently of
            # whichever polling error was most recently reported.
            # An unchanged status is refreshed once a minute rather
            # than after every 10-second long poll.
            current = db.execute("SELECT last_error,last_success_at FROM telegram_config WHERE id=1").fetchone()
            remaining = self._delivery_error(db)
            fresh = current["last_success_at"] and time.time() - _epoch(current["last_success_at"]) < 60
            if updates or not fresh or current["last_error"] != remaining:
                db.execute("""UPDATE telegram_config SET last_success_at=?,last_error=?,
                    last_error_at=CASE WHEN ? IS NULL THEN NULL ELSE last_error_at END
                    WHERE id=1 AND enabled=1 AND mode='polling'""", (utc_now(), remaining, remaining))
        return len(updates)

    def _run_pass(self, plan, cfg, poll) -> None:
        started, counts = time.monotonic(), {"handled": 0, "sent": 0, "received": 0}
        if plan["check"]:
            self._check_webhook(cfg)
        counts["handled"] = int(bool(self.process_one()))
        if plan["notices"] or cfg["mode"] == "polling":
            self.notify_uploads()
        sent = self.deliver_one()
        counts["sent"] = int(bool(sent))
        if poll and cfg["mode"] == "polling" and not sent:
            counts["received"] = self._poll(cfg)
        if counts["handled"] or counts["sent"] or counts["received"]:
            logger.info("telegram run: handled=%d sent=%d received=%d in %.1fs",
                        counts["handled"], counts["sent"], counts["received"], time.monotonic() - started)

    def tick(self, *, poll=True):
        """One pass: True when it did work, False when there was none or
        another worker holds the lease.  Nothing due means nothing written:
        no lease is taken, so none is released."""
        with self._run_lock:
            plan = self._due()
            self.idle_wait = plan["wait"]
            if plan["queued_upload"]:
                from .ingest.intake import start_worker
                start_worker(self.settings)
            if not plan["due"]:
                return False
            cfg = self._take_lease()
            if cfg is None:
                return False
            worked = False
            try:
                self._run_pass(plan, cfg, poll)
                worked = True
            except TelegramError as error:
                logger.warning("telegram run failed: %s", error.key)
                with transaction(self.settings, immediate=True) as db:
                    db.execute("UPDATE telegram_config SET last_error=?,last_error_at=?,enabled=CASE WHEN ? THEN 0 ELSE enabled END WHERE id=1", (error.key, utc_now(), int(error.permanent)))
                self._stop.wait(min(error.retry_after or 5, 30))
            finally:
                with transaction(self.settings, immediate=True) as db:
                    db.execute("UPDATE telegram_config SET lease_owner=NULL,lease_until=0 WHERE lease_owner=?", (self.worker_id,))
            return worked

    def wake(self):
        """New work arrived (a webhook update): end an idle wait now."""
        self._wake.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        def run():
            while not self._stop.is_set():
                worked = False
                try:
                    worked = self.tick()
                except Exception as exc:
                    # Never log upstream URLs, medical content, update payloads or tokens.
                    # The error write can itself meet "database is locked" (the
                    # tick usually failed for exactly that reason); escaping
                    # here ended the thread and silenced the bot until restart.
                    logger.warning("telegram run failed: %s", type(exc).__name__)
                    try:
                        with transaction(self.settings, immediate=True) as db:
                            db.execute("UPDATE telegram_config SET last_error='telegram.error_internal',last_error_at=? WHERE id=1", (utc_now(),))
                    except Exception:
                        pass
                    self.idle_wait = 5
                if worked:
                    continue
                self._wake.wait(max(0.5, self.idle_wait))
                self._wake.clear()
        self._thread = threading.Thread(target=run, daemon=True, name="anamna-telegram")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=40)
        if not self._thread or not self._thread.is_alive():
            self._thread = None
