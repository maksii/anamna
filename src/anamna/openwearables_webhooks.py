"""Svix receipts, subscription management and durable account-scoped catch-up.

No provider is pulled in the request handler. An acknowledgement means the
verified bytes, account targets and reconciliation jobs committed together.
See docs/openwearables-webhooks.md for the verified upstream contracts.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, urlsplit

from . import openwearables as ow
from . import openwearables_archive as archive
from .config import Settings, env, log_run
from .db import connect, transaction, utc_now
from .i18n import format_date_localized

logger = logging.getLogger(__name__)
_SUBSCRIPTION_SQL = "SELECT * FROM openwearables_subscriptions WHERE id=?"
_STATE_ROW_SQL = "SELECT id,metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key=?"
_ENDPOINTS_PATH = "/webhooks/endpoints/"
MAX_BODY_BYTES = 1024 * 1024
TIMESTAMP_TOLERANCE = 300
COALESCE_SECONDS = 15
LEASE_SECONDS = 180
RETRY_LIMIT = 8
WINDOW_DAYS = 7
#: Twice-daily scheduled catch-up: today and the three days before it. Upstream
#: rarely edits older data; the monthly history check reconciles what it does.
CATCHUP_DAYS = 3
#: The monthly history check restarts this far before the previous one ended.
HISTORY_OVERLAP_DAYS = 7
#: Background checks shown before "Show all" loads the rest on request.
JOBS_SHOWN = 10
RAW_SPLIT_MAX_DEPTH = 64
KNOWN_SESSION_EVENTS = {"workout.created", "sleep.created", "menstrual_cycle.created", "activity.created"}
KNOWN_LIFECYCLE_EVENTS = {"connection.created", "connection.revoked", "sync.started", "sync.completed", "sync.failed"}


class WebhookError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def management_api(settings: Settings, path: str, params: dict | None = None, *, method: str = "GET", data: dict | None = None):
    """Older deployments require a developer JWT specifically for management.

    Data pulls always use the API key. Current upstream supports that key for
    management too; an explicitly configured developer token is only sent to
    the webhook management paths on the configured server.
    """
    if not path.startswith("/webhooks/"):
        raise WebhookError("invalid_management_path")
    token = env("OPENWEARABLES_WEBHOOK_TOKEN", "").strip()
    if not token:
        return ow._api(settings, path, params, method=method, data=data)
    from urllib.parse import urlencode
    config = ow.ow_settings(settings)
    if not config["url"]:
        raise WebhookError("not_configured")
    with connect(settings) as db:
        binding = db.execute("SELECT value FROM app_settings WHERE key='openwearables_webhook_token_server'").fetchone()
    if binding and binding[0] != config["url"]:
        raise WebhookError("server_changed")
    url = config["url"] + "/api/v1" + path
    if params:
        url += "?" + urlencode(params, doseq=True)
    options = {"headers": {"Authorization": "Bearer " + token}}
    if method != "GET":
        options["method"] = method
    if data is not None:
        options["data"] = data
    return ow._request(url, **options)


def _secret_bytes(secret: str) -> bytes:
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, TypeError) as exc:
        raise WebhookError("invalid_secret") from exc
    if len(key) < 16:
        raise WebhookError("invalid_secret")
    return key


def verify_signature(body: bytes, headers, secrets: list[str], *, now: float | None = None) -> str:
    """Verify exact raw bytes against every active key and Svix v1 signature."""
    if len(body) > MAX_BODY_BYTES:
        raise WebhookError("body_too_large", 413)
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    message_id = headers.get("svix-id", "")
    stamp = headers.get("svix-timestamp", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", message_id) or not re.fullmatch(r"\d{1,12}", stamp, re.ASCII):
        raise WebhookError("invalid_signature", 401)
    if abs((time.time() if now is None else now) - int(stamp)) > TIMESTAMP_TOLERANCE:
        raise WebhookError("expired_signature", 401)
    signed = message_id.encode() + b"." + stamp.encode() + b"." + body
    signatures = []
    for part in headers.get("svix-signature", "").split():
        version, sep, signature = part.partition(",")
        if sep and version == "v1":
            signatures.append(signature)
    valid = False
    for secret in secrets:
        if not secret:
            continue
        expected = base64.b64encode(hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()).decode()
        for signature in signatures:
            valid |= hmac.compare_digest(expected, signature)
    if not valid:
        raise WebhookError("invalid_signature", 401)
    return message_id


def _accounts(db, server: str, remote: str | None = None) -> list[dict]:
    rows = db.execute("""SELECT pc.user_id, pc.external_user_id, di.metadata_json, u.email
        FROM provider_connections pc JOIN users u ON u.id=pc.user_id
        JOIN device_imports di ON di.owner_user_id=pc.user_id AND di.adapter_key=?
        WHERE pc.provider=? AND pc.status='active'""", (ow.ADAPTER_KEY, ow.PROVIDER)).fetchall()
    accounts = []
    for row in rows:
        state = json.loads(row["metadata_json"])
        if state.get("remote_server_url", server) != server or (remote and row["external_user_id"] != remote):
            continue
        accounts.append(dict(row) | {"generation": str(state.get("link_generation", ""))})
    return accounts


def _enqueue(db, account: dict, server: str, start: str, end: str, reason: str, now: float) -> str:
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end:
        raise WebhookError("invalid_window")
    # A running job keeps its own window; arrivals during it get a subsequent
    # queued job, so completion cannot acknowledge data that arrived mid-fetch.
    pending = db.execute("""SELECT * FROM openwearables_sync_jobs WHERE owner_user_id=?
        AND server_url=? AND remote_user_id=? AND link_generation=? AND status='queued'
        AND (reason='backfill')=?
        ORDER BY created_at LIMIT 1""", (account["user_id"], server, account["external_user_id"], account["generation"], int(reason == "backfill"))).fetchone()
    if pending:
        db.execute("""UPDATE openwearables_sync_jobs SET start_day=min(start_day,?),
            next_day=min(next_day,?), end_day=max(end_day,?), updated_at=? WHERE id=?""",
            (start, start, end, utc_now(), pending["id"]))
        return str(pending["id"])
    job_id = uuid.uuid4().hex
    db.execute("""INSERT INTO openwearables_sync_jobs(id,owner_user_id,server_url,remote_user_id,
        link_generation,reason,start_day,end_day,next_day,available_at,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (job_id, account["user_id"], server, account["external_user_id"],
        account["generation"], reason, start, end, start, now + (COALESCE_SECONDS if reason == "webhook" else 0), utc_now(), utc_now()))
    return job_id


def enqueue_sync(settings: Settings, user_ids: list[str] | None = None, *, backfill: bool = False,
                 start: str | None = None, end: str | None = None, reason: str = "manual") -> list[str]:
    """Queue one, selected or all linked accounts; never treats remote IDs as owners."""
    if not ow.configured(settings):
        return []
    today = datetime.now(UTC).date()
    start = start or (ow.EPOCH_DAY if backfill else (today - timedelta(days=ow.RECENT_WINDOW_DAYS)).isoformat())
    end = end or today.isoformat()
    server = ow.ow_settings(settings)["url"]
    with transaction(settings, immediate=True) as db:
        accounts = _accounts(db, server)
        if user_ids is not None:
            wanted = set(user_ids)
            accounts = [a for a in accounts if a["user_id"] in wanted]
        return [_enqueue(db, a, server, start, end, "backfill" if backfill else reason, time.time()) for a in accounts]


def _event_window(data: dict) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    days = []
    for field in ("start_time", "end_time", "timestamp", "recorded_at", "date"):
        value = data.get(field)
        if value:
            try:
                days.append(date.fromisoformat(str(value)[:10]))
            except ValueError:
                raise WebhookError("invalid_event_date")
    if not days:
        return (today - timedelta(days=ow.RECENT_WINDOW_DAYS)).isoformat(), today.isoformat()
    # A timezone-offset session can contribute on an adjacent local date.
    return (min(days) - timedelta(days=1)).isoformat(), min(today, max(days) + timedelta(days=1)).isoformat()


def _sample_key(sample: dict) -> str:
    # Same sample arrives under both group and granular event names upstream.
    # Exclude its numeric value so corrections replace instead of accumulating.
    identity = {k: sample.get(k) for k in ("id", "timestamp", "type", "source", "is_daily_total")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _utc_stamp(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("timezone missing")
        return moment.astimezone(UTC).isoformat(timespec="microseconds")
    except (ValueError, TypeError) as exc:
        raise WebhookError("invalid_sample_timestamp") from exc


def _sample_rows(samples: list[dict]):
    """(sample_key, utc timestamp, series_type, received_at, payload_json)."""
    received = utc_now()
    return ((_sample_key(s), _utc_stamp(str(s.get("timestamp", ""))), str(s.get("type", "")), received,
             json.dumps(s, ensure_ascii=False, sort_keys=True)) for s in samples)


def _store_samples(db, owner: str, server: str, remote: str, samples: list[dict]) -> None:
    """Stage fetched samples in the private per-sync spool (not the archive)."""
    db.executemany("""INSERT INTO openwearables_raw_samples
        (owner_user_id,server_url,remote_user_id,sample_key,timestamp,series_type,received_at,payload_json)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(owner_user_id,server_url,remote_user_id,sample_key)
        DO UPDATE SET payload_json=excluded.payload_json,received_at=excluded.received_at""",
        ((owner, server, remote, *row) for row in _sample_rows(samples)))


def _reject_constant(value):
    raise ValueError(value)


def _parse_event(body: bytes) -> tuple[dict, str, str, list | None]:
    """Decode and validate a webhook body into ``(data, type, remote, samples)``."""
    try:
        event = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookError("invalid_json") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str) or not isinstance(event.get("data"), dict):
        raise WebhookError("invalid_event")
    data, event_type = event["data"], event["type"]
    remote = str(data.get("user_id") or "")
    if not remote or len(remote) > 200 or len(event_type) > 200:
        raise WebhookError("invalid_event")
    samples = data.get("samples")
    if samples is not None:
        _check_samples(data, samples)
    return data, event_type, remote, samples


def _check_samples(data: dict, samples: object) -> None:
    if not isinstance(samples, list) or any(not isinstance(s, dict) or not s.get("timestamp") or not s.get("type") for s in samples):
        raise WebhookError("invalid_samples")
    for sample in samples:
        _utc_stamp(str(sample["timestamp"]))
    if data.get("total_chunks") is not None:
        if not isinstance(data.get("chunk_index"), int) or not isinstance(data["total_chunks"], int) or not 0 <= data["chunk_index"] < data["total_chunks"]:
            raise WebhookError("invalid_chunks")


def _receipt_status(known: bool, accounts: list) -> str:
    if not accounts:
        return "unlinked"
    return "queued" if known else "unsupported"


def _record_lifecycle(db, account, event_type: str, data: dict) -> None:
    # Keep the exact lifecycle evidence without changing the
    # Anamna link or deleting already imported readings.
    state_row = db.execute(_STATE_ROW_SQL, (account["user_id"], ow.ADAPTER_KEY)).fetchone()
    state = json.loads(state_row["metadata_json"])
    state["last_remote_event"] = {"type": event_type, "provider": data.get("provider"), "status": data.get("status"), "reason": data.get("reason"), "received_at": utc_now()}
    db.execute("UPDATE device_imports SET metadata_json=? WHERE id=?", (json.dumps(state), state_row["id"]))


def _available_receiver(db, settings: Settings, receiver_id: str):
    current = db.execute(_SUBSCRIPTION_SQL, (receiver_id,)).fetchone()
    if not current or not current["enabled"] or current["server_url"] != ow.ow_settings(settings)["url"]:
        raise WebhookError("receiver_unavailable", 404)
    return current


def _duplicate_receipt(db, receiver_id: str, message_id: str, digest: str) -> dict | None:
    previous = db.execute("SELECT id,body_sha256,status FROM openwearables_receipts WHERE subscription_id=? AND message_id=?", (receiver_id, message_id)).fetchone()
    if not previous:
        return None
    if previous["body_sha256"] != digest:
        raise WebhookError("message_conflict", 409)
    return {"ok": True, "duplicate": True, "receipt_id": previous["id"]}


def _receipt_allowed(current, remote: str, event_type: str) -> bool:
    filters = json.loads(current["filter_types_json"])
    return (not current["remote_user_id"] or current["remote_user_id"] == remote) and (not filters or event_type in filters)


def _fan_out_receipt(db, accounts: list, current, receipt_id: int, event: tuple, known: bool,
                     start: str, end: str, now: float) -> None:
    data, event_type, remote, samples = event
    for account in accounts:
        job_id = _enqueue(db, account, current["server_url"], start, end, "webhook", now) if known else None
        db.execute("INSERT INTO openwearables_receipt_targets VALUES (?,?,?,?)", (receipt_id, account["user_id"], account["generation"], job_id))
        if samples is not None:
            archive.merge_samples(db, (account["user_id"], current["server_url"], remote), _sample_rows(samples))
        if event_type in KNOWN_LIFECYCLE_EVENTS:
            _record_lifecycle(db, account, event_type, data)


def _store_receipt(db, settings: Settings, receiver_id: str, message_id: str, body: bytes, event: tuple,
                   known: bool, now: float) -> dict:
    data, event_type, remote, _samples = event
    digest = hashlib.sha256(body).hexdigest()
    current = _available_receiver(db, settings, receiver_id)
    duplicate = _duplicate_receipt(db, receiver_id, message_id, digest)
    if duplicate:
        return duplicate
    accounts = _accounts(db, current["server_url"], remote)
    if not _receipt_allowed(current, remote, event_type):
        accounts = []
    status = _receipt_status(known, accounts)
    receipt_id = db.execute("""INSERT INTO openwearables_receipts
        (subscription_id,message_id,event_type,remote_user_id,body,body_sha256,status,received_at)
        VALUES (?,?,?,?,?,?,?,?)""", (receiver_id, message_id, event_type, remote,
        body if accounts else b"", digest, status, utc_now())).lastrowid
    start, end = _event_window(data) if accounts and known else ("", "")
    # Future-dated examples or bad provider clocks remain inspectable and
    # must not create an inverted job window that rejects every retry.
    if start and start > end:
        known = False
        db.execute("UPDATE openwearables_receipts SET status=? WHERE id=?", ("unsupported", receipt_id))
    _fan_out_receipt(db, accounts, current, receipt_id, event, known, start, end, now)
    return {"ok": True, "duplicate": False, "receipt_id": receipt_id}


def receive(settings: Settings, receiver_id: str, body: bytes, headers, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    config = ow.ow_settings(settings)
    with connect(settings) as db:
        sub = db.execute(_SUBSCRIPTION_SQL, (receiver_id,)).fetchone()
    if not sub or not sub["enabled"] or sub["server_url"] != config["url"] or config["enabled"] != "1":
        raise WebhookError("receiver_unavailable", 404)
    secrets = [sub["secret"]]
    if sub["previous_secret_until"] > now:
        secrets.append(sub["previous_secret"])
    message_id = verify_signature(body, headers, secrets, now=now)
    event = _parse_event(body)
    _data, event_type, _remote, samples = event
    known = samples is not None or event_type in KNOWN_SESSION_EVENTS | KNOWN_LIFECYCLE_EVENTS
    # Deletion event contracts may be added upstream. Keep the payload and run
    # a complete bounded window, never delete rows based only on its IDs.
    known = known or event_type.endswith((".deleted", ".updated"))
    with transaction(settings, immediate=True) as db:
        return _store_receipt(db, settings, receiver_id, message_id, body, event, known, now)


def _validated_subscription(settings: Settings, public_url: str, receiver_id: str, remote_user_id: str,
                            filter_types: list[str] | None) -> tuple[str, list[str], str]:
    """Check the admin's input; return ``(server, filters, receiver_id)``."""
    url = urlsplit(public_url.strip())
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise WebhookError("invalid_callback")
    server = ow.ow_settings(settings)["url"]
    if not ow.configured(settings):
        raise WebhookError("not_configured")
    if remote_user_id:
        try:
            uuid.UUID(remote_user_id)
        except ValueError as exc:
            raise WebhookError("invalid_user") from exc
    filters = sorted(set(filter_types or []))
    if any(not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", f) for f in filters) or len(filters) > 200:
        raise WebhookError("invalid_filters")
    receiver_id = receiver_id or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", receiver_id):
        raise WebhookError("invalid_receiver")
    return server, filters, receiver_id


def _existing_endpoint_id(settings: Settings, callback: str) -> str:
    # A network timeout after POST may have created it. Match our
    # unguessable receiver URL on retry before issuing another POST.
    endpoints = management_api(settings, _ENDPOINTS_PATH.rstrip("/"))
    if not isinstance(endpoints, list):
        raise ow.OpenWearablesError("invalid endpoint list")
    matching = [e for e in endpoints if e.get("url") == callback]
    return str(matching[0]["id"]) if matching else ""


def _rotated_secret(previous: str, secret: str, sub) -> tuple[str, float]:
    """Return ``(previous_secret, previous_secret_until)`` to keep after a rotation."""
    kept_until = sub["previous_secret_until"] if sub else 0
    if previous == secret:
        return (sub["previous_secret"] if sub else ""), kept_until
    if previous:
        return previous, time.time() + 86400
    return previous, kept_until


def _push_endpoint(settings: Settings, callback: str, sub, receiver_id: str, remote_user_id: str, filters: list[str]) -> None:
    endpoint_id = str(sub["endpoint_id"]) if sub else ""
    if not endpoint_id:
        endpoint_id = _existing_endpoint_id(settings, callback)
    body = {"url": callback, "description": "Anamna", "user_id": remote_user_id or None, "filter_types": filters}
    response = management_api(settings, _ENDPOINTS_PATH.rstrip("/") + ("/" + quote(endpoint_id, safe="") if endpoint_id else ""),
                       method="PATCH" if endpoint_id else "POST", data=body)
    endpoint_id = str(response["id"])
    with transaction(settings, immediate=True) as db:
        db.execute("UPDATE openwearables_subscriptions SET endpoint_id=? WHERE id=?", (endpoint_id, receiver_id))
    secret = management_api(settings, _ENDPOINTS_PATH + quote(endpoint_id, safe="") + "/secret")["key"]
    _secret_bytes(secret)
    with transaction(settings, immediate=True) as db:
        previous = db.execute("SELECT secret FROM openwearables_subscriptions WHERE id=?", (receiver_id,)).fetchone()[0]
        kept_secret, kept_until = _rotated_secret(previous, secret, sub)
        db.execute("""UPDATE openwearables_subscriptions SET secret=?, previous_secret=?, previous_secret_until=?,
            enabled=1,status='active',last_error='',updated_at=? WHERE id=?""",
            (secret, kept_secret, kept_until, utc_now(), receiver_id))


def save_subscription(settings: Settings, public_url: str, *, receiver_id: str = "",
                      remote_user_id: str = "", filter_types: list[str] | None = None) -> str:
    """Create/update a remote endpoint and recover a partially completed save.

    This function writes to OpenWearables; call only from an authorized admin
    action. Merely reading operational_status never calls a remote API.
    """
    server, filters, receiver_id = _validated_subscription(settings, public_url, receiver_id, remote_user_id, filter_types)
    callback = public_url.strip().rstrip("/") + "/webhooks/openwearables/" + receiver_id
    with transaction(settings, immediate=True) as db:
        sub = db.execute(_SUBSCRIPTION_SQL, (receiver_id,)).fetchone()
        if sub and sub["server_url"] != server:
            raise WebhookError("server_changed")
        db.execute("""INSERT INTO openwearables_subscriptions(id,server_url,callback_url,remote_user_id,filter_types_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET callback_url=excluded.callback_url,
            remote_user_id=excluded.remote_user_id,filter_types_json=excluded.filter_types_json,updated_at=excluded.updated_at""",
            (receiver_id, server, callback, remote_user_id, json.dumps(filters), utc_now(), utc_now()))
    try:
        _push_endpoint(settings, callback, sub, receiver_id, remote_user_id, filters)
        return receiver_id
    except Exception as exc:
        with transaction(settings, immediate=True) as db:
            db.execute("UPDATE openwearables_subscriptions SET status='error',last_error=?,updated_at=? WHERE id=?", (_error_code(exc), utc_now(), receiver_id))
        raise


def _subscription(settings: Settings, receiver_id: str):
    with connect(settings) as db:
        row = db.execute(_SUBSCRIPTION_SQL, (receiver_id,)).fetchone()
    if not row:
        raise WebhookError("receiver_unavailable", 404)
    return row


def delete_subscription(settings: Settings, receiver_id: str) -> None:
    sub = _subscription(settings, receiver_id)
    if sub["server_url"] != ow.ow_settings(settings)["url"]:
        raise WebhookError("server_changed")
    if sub["endpoint_id"]:
        try:
            management_api(settings, _ENDPOINTS_PATH + quote(sub["endpoint_id"], safe=""), method="DELETE")
        except ow.OpenWearablesError as exc:
            if exc.status != 404:
                raise
    with transaction(settings, immediate=True) as db:
        db.execute("UPDATE openwearables_subscriptions SET enabled=0,status='disabled',secret='',previous_secret='',updated_at=? WHERE id=?", (utc_now(), receiver_id))


def test_subscription(settings: Settings, receiver_id: str, event_type: str = "workout.created") -> dict:
    sub = _subscription(settings, receiver_id)
    if sub["server_url"] != ow.ow_settings(settings)["url"]:
        raise WebhookError("server_changed")
    return management_api(settings, _ENDPOINTS_PATH + quote(sub["endpoint_id"], safe="") + "/test", method="POST", data={"event_type": event_type})


def remote_evidence(settings: Settings, receiver_id: str) -> dict:
    sub = _subscription(settings, receiver_id)
    if sub["server_url"] != ow.ow_settings(settings)["url"]:
        raise WebhookError("server_changed")
    # Bound the diagnostic page, and do not expose returned medical payloads.
    data = management_api(settings, _ENDPOINTS_PATH + quote(sub["endpoint_id"], safe="") + "/attempts", {"limit": 20})
    return {"done": data.get("done"), "iterator": data.get("iterator"), "data": [
        {k: row.get(k) for k in ("id", "msgId", "status", "responseStatusCode", "timestamp")}
        for row in data.get("data", [])]}


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ow.OpenWearablesError):
        return f"http_{exc.status}" if exc.status else "remote_unavailable"
    if isinstance(exc, WebhookError):
        return exc.code
    return type(exc).__name__


def _enqueue_backfill(db, account, server: str, today: date, fresh: bool, now: float) -> None:
    # A monthly tick must not rewind unfinished history. In
    # particular, attention jobs need operator review rather than
    # a duplicate automatic run hiding the failed window.
    unfinished = db.execute("""SELECT 1 FROM openwearables_sync_jobs
        WHERE owner_user_id=? AND server_url=? AND remote_user_id=?
        AND link_generation=? AND reason='backfill'
        AND status IN ('queued','running','retry','attention') LIMIT 1""",
        (account["user_id"], server, account["external_user_id"], account["generation"])).fetchone()
    if not unfinished:
        # Incremental: from shortly before the previous complete
        # history check of this link. Full history only for a new
        # link, or when an administrator asks for it.
        previous = None if fresh else db.execute("""SELECT max(end_day) FROM openwearables_sync_jobs
            WHERE owner_user_id=? AND server_url=? AND remote_user_id=? AND link_generation=?
            AND reason='backfill' AND status='complete'""",
            (account["user_id"], server, account["external_user_id"], account["generation"])).fetchone()[0]
        start = (date.fromisoformat(previous) - timedelta(days=HISTORY_OVERLAP_DAYS)).isoformat() if previous else ow.EPOCH_DAY
        _enqueue(db, account, server, max(start, ow.EPOCH_DAY), today.isoformat(), "backfill", now)


def _schedule_account(db, account, server: str, today: date, now: float) -> bool:
    row = db.execute("SELECT * FROM openwearables_schedule WHERE owner_user_id=?", (account["user_id"],)).fetchone()
    fresh = row is None or row["link_generation"] != account["generation"]
    catchup = fresh or row["next_catchup_at"] <= now
    backfill = fresh or row["next_backfill_at"] <= now
    if not catchup and not backfill:
        return False
    if catchup:
        _enqueue(db, account, server, (today - timedelta(days=CATCHUP_DAYS)).isoformat(), today.isoformat(), "scheduled", now)
    if backfill:
        _enqueue_backfill(db, account, server, today, fresh, now)
    db.execute("""INSERT INTO openwearables_schedule VALUES (?,?,?,?) ON CONFLICT(owner_user_id)
        DO UPDATE SET link_generation=excluded.link_generation,next_catchup_at=excluded.next_catchup_at,next_backfill_at=excluded.next_backfill_at""",
        (account["user_id"], account["generation"], now + ow.REFRESH_SECONDS,
         now + 30 * 86400 if backfill else row["next_backfill_at"]))
    return True


def schedule_due(settings: Settings, *, now: float | None = None) -> int:
    """Page-independent catch-up twice daily and monthly history reconciliation."""
    if not ow.configured(settings):
        return 0
    now = time.time() if now is None else now
    today = datetime.now(UTC).date()
    server = ow.ow_settings(settings)["url"]
    count = 0
    with transaction(settings, immediate=True) as db:
        for account in _accounts(db, server):
            if _schedule_account(db, account, server, today, now):
                count += 1
    return count


def archive_records(settings: Settings, user_id: str, datatype: str, rows: list[dict], start: str, end: str,
                    expected: tuple) -> None:
    """Keep the complete response, including fields without a display mapping."""
    with transaction(settings, immediate=True) as db:
        ow._check_sync_account(db, settings, user_id, expected)
        db.execute("DELETE FROM openwearables_raw_records WHERE owner_user_id=? AND server_url=? AND remote_user_id=? AND datatype=? AND day BETWEEN ? AND ?",
                   (user_id, expected[1], expected[0], datatype, start, end))
        values = []
        for row in rows:
            content = json.dumps(row, ensure_ascii=False, sort_keys=True)
            key = str(row.get("id") or hashlib.sha256(content.encode()).hexdigest())
            day = str(row.get("date") or row.get("timestamp") or row.get("start_time") or row.get("recorded_at") or start)[:10]
            values.append((user_id, expected[1], expected[0], datatype, key, day, content, utc_now()))
        db.executemany("""INSERT INTO openwearables_raw_records VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(owner_user_id,server_url,remote_user_id,datatype,record_key)
            DO UPDATE SET day=excluded.day,payload_json=excluded.payload_json,received_at=excluded.received_at""", values)


def _raw_intervals(settings: Settings, user_id: str, expected: tuple, start: str, end: str):
    """Split only valid over-budget reads; overlap exact UTC microsecond cuts."""
    pending = [(start, end, 0)]
    while pending:
        left, right, depth = pending.pop()
        with connect(settings) as db:
            ow._check_sync_account(db, settings, user_id, expected)
        split = False
        indivisible = False
        try:
            rows = ow._exhaustive_rows(settings, f"/users/{quote(expected[0], safe='')}/timeseries",
                {"start_time": left, "end_time": right, "resolution": "raw"}, ow._PAGE_LIMIT,
                ow._advance_timestamps, max_rows=ow._PAGE_LIMIT * ow._MAX_PAGES)
        except ow.OpenWearablesPageLimitError as exc:
            split, indivisible = True, exc.indivisible_timestamp
        # Leave the exception scope before retrying, releasing its bounded
        # partial rows/traceback instead of retaining them down a recursion.
        if split:
            lower = datetime.fromisoformat(_utc_stamp(left))
            upper = datetime.fromisoformat(_utc_stamp(right))
            middle = lower + (upper - lower) // 2
            if indivisible or depth >= RAW_SPLIT_MAX_DEPTH or middle <= lower or middle >= upper:
                raise ow.OpenWearablesError("raw timeseries cannot split an over-budget timestamp boundary")
            cut = middle.isoformat(timespec="microseconds").replace("+00:00", "Z")
            pending.extend(((cut, right, depth + 1), (left, cut, depth + 1)))
            continue
        lower, upper = _utc_stamp(left), _utc_stamp(right)
        if any(not row.get("timestamp") or not row.get("type") or
               not lower <= _utc_stamp(str(row["timestamp"])) <= upper for row in rows):
            raise ow.OpenWearablesError("invalid or out-of-window raw timeseries samples")
        yield rows
        del rows


class _StagedSeries:
    """Repeatable, streaming JSON rows for the mapper's daily-total passes."""

    def __init__(self, db, series_type: str):
        self.db, self.series_type = db, series_type

    def __iter__(self):
        for row in self.db.execute("SELECT payload_json FROM openwearables_raw_samples WHERE series_type=? ORDER BY timestamp,sample_key", (self.series_type,)):
            yield json.loads(row[0])


def sync_raw_timeseries(settings: Settings, user_id: str, start: str, end: str, expected: tuple | None = None) -> int:
    """Stage complete raw intervals on private disk, then commit one window.

    Memory is bounded by one cursor interval plus daily aggregates. Overlap
    copies use the same stable identity as receipts; the later fetched copy
    replaces a correction before either raw storage or daily aggregation.
    """
    expected = expected or ow.account_identity(settings, user_id)
    with tempfile.TemporaryDirectory(prefix="anamna-ow-raw-") as folder:
        stage = sqlite3.connect(Path(folder) / "samples.sqlite3")
        try:
            stage.executescript("""PRAGMA cache_size=-2048;
                CREATE TABLE openwearables_raw_samples (
                    owner_user_id TEXT,server_url TEXT,remote_user_id TEXT,sample_key TEXT,
                    timestamp TEXT,series_type TEXT,payload_json TEXT,received_at TEXT,
                    PRIMARY KEY(owner_user_id,server_url,remote_user_id,sample_key));
                CREATE INDEX staged_series ON openwearables_raw_samples(series_type,timestamp,sample_key);""")
            for rows in _raw_intervals(settings, user_id, expected, start + "T00:00:00Z", end + "T23:59:59.999999Z"):
                _store_samples(stage, user_id, expected[1], expected[0], rows)
                stage.commit()
                del rows
            count = stage.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0]
            import_id = ow.ensure_envelope(settings, user_id)
            with transaction(settings, immediate=True) as db:
                ow._check_sync_account(db, settings, user_id, expected)
                # The window's days become exactly what was fetched, in the
                # compact archive; ordered so one day-series is held at a time.
                archive.replace_window(db, (user_id, expected[1], expected[0]), start, end, stage.execute(
                    """SELECT sample_key,timestamp,series_type,received_at,payload_json FROM openwearables_raw_samples
                    ORDER BY series_type,timestamp,sample_key"""))
                # Local days, rebuilt from the archived samples: the window's own
                # plus the previous window's late-UTC hours of its first day.
                failed_keys = ow.recompute_raw_days(settings, db, user_id, import_id, expected, start, end)
            if failed_keys:
                raise ow.OpenWearablesError("unsupported units: " + ",".join(sorted(failed_keys)))
            return count
        finally:
            stage.close()


def _claim_job(settings: Settings, now: float, token: str):
    """Lease the next job: ``(job, expected)``; ``(None, None)`` when there is
    none; ``(job, None)`` when its account changed and it was cancelled."""
    with transaction(settings, immediate=True) as db:
        job = db.execute("""SELECT * FROM openwearables_sync_jobs j WHERE
            ((status IN ('queued','retry') AND available_at<=?) OR (status='running' AND lease_until<=?))
            AND NOT EXISTS (SELECT 1 FROM openwearables_sync_jobs active WHERE active.owner_user_id=j.owner_user_id
              AND active.status='running' AND active.lease_until>?) ORDER BY available_at,created_at LIMIT 1""", (now, now, now)).fetchone()
        if not job:
            return None, None
        expected = (job["remote_user_id"], job["server_url"], job["link_generation"])
        try:
            ow._check_sync_account(db, settings, job["owner_user_id"], expected)
        except ow.OpenWearablesError:
            db.execute("UPDATE openwearables_sync_jobs SET status='cancelled',updated_at=? WHERE id=?", (utc_now(), job["id"]))
            return job, None
        db.execute("UPDATE openwearables_sync_jobs SET status='running',lease_token=?,lease_until=?,updated_at=? WHERE id=?", (token, now + LEASE_SECONDS, utc_now(), job["id"]))
    return job, expected


def _start_heartbeat(settings: Settings, job, token: str, stop: threading.Event) -> threading.Thread:
    def renew():
        while not stop.wait(30):
            # A busy database is a missed beat, not a dead heartbeat: the lease
            # is six beats long, and an uncaught "database is locked" here used
            # to end the thread and let a healthy job's lease expire.
            try:
                with transaction(settings, immediate=True) as db:
                    db.execute("UPDATE openwearables_sync_jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'", (time.time() + LEASE_SECONDS, job["id"], token))
            except sqlite3.OperationalError:
                continue

    heartbeat = threading.Thread(target=renew, daemon=True, name="ow-lease")
    heartbeat.start()
    return heartbeat


def _advance_job(settings: Settings, job, token: str, expected: tuple, end: str, counts: dict) -> tuple[bool, dict]:
    """Move the job past this window; returns ``(done, cumulative counts)``."""
    with transaction(settings, immediate=True) as db:
        ow._check_sync_account(db, settings, job["owner_user_id"], expected)
        next_day = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        done = next_day > job["end_day"]
        cumulative = json.loads(job["counts_json"])
        for datatype, count in counts.items():
            cumulative[datatype] = cumulative.get(datatype, 0) + count
        db.execute("""UPDATE openwearables_sync_jobs SET status=?,next_day=?,attempts=0,available_at=?,lease_until=0,
            counts_json=?,last_error='',updated_at=? WHERE id=? AND lease_token=? AND status='running'""",
            ("complete" if done else "queued", next_day, time.time() + 2, json.dumps(cumulative), utc_now(), job["id"], token))
        if done:
            db.execute("""UPDATE openwearables_receipts SET status='complete' WHERE status='queued'
                AND id IN (SELECT receipt_id FROM openwearables_receipt_targets WHERE job_id=?)
                AND NOT EXISTS (SELECT 1 FROM openwearables_receipt_targets t JOIN openwearables_sync_jobs j ON j.id=t.job_id
                    WHERE t.receipt_id=openwearables_receipts.id AND j.status<>'complete')""", (job["id"],))
    return done, cumulative


def _record_window_success(settings: Settings, job, expected: tuple, done: bool, cumulative: dict) -> None:
    # Protect status updates from a concurrent relink as well as row writes.
    with transaction(settings, immediate=True) as db:
        ow._check_sync_account(db, settings, job["owner_user_id"], expected[:3])
        row = db.execute(_STATE_ROW_SQL, (job["owner_user_id"], ow.ADAPTER_KEY)).fetchone()
        state = json.loads(row["metadata_json"])
        state.update(last_window_sync_at=utc_now(), failed_datatypes={})
        if done:
            state["last_sync_at"] = utc_now()
        if done and job["reason"] == "backfill":
            state["last_backfill_at"] = utc_now()
            state["backfill_counts"] = cumulative
        db.execute("""UPDATE device_imports SET metadata_json=?,imported_at=?,
            raw_record_count=(SELECT count(*) FROM device_metric_days WHERE import_id=device_imports.id)
            WHERE id=?""", (json.dumps(state), utc_now(), row["id"]))


def _record_window_failure(settings: Settings, job, token: str, expected: tuple, exc: Exception, failures: dict) -> None:
    attempts = job["attempts"] + 1
    code = ",".join(sorted(failures)) if failures else _error_code(exc)
    with transaction(settings, immediate=True) as db:
        db.execute("""UPDATE openwearables_sync_jobs SET status=?,attempts=?,available_at=?,lease_until=0,last_error=?,updated_at=?
            WHERE id=? AND lease_token=? AND status='running'""", ("attention" if attempts >= RETRY_LIMIT else "retry",
            attempts, time.time() + min(3600, 30 * 2 ** min(attempts, 7)), code, utc_now(), job["id"], token))
        try:
            ow._check_sync_account(db, settings, job["owner_user_id"], expected[:3])
        except ow.OpenWearablesError:
            return
        state_row = db.execute(_STATE_ROW_SQL, (job["owner_user_id"], ow.ADAPTER_KEY)).fetchone()
        state = json.loads(state_row["metadata_json"])
        state["failed_datatypes"] = dict.fromkeys(failures, "sync_failed") if failures else {"sync": code}
        db.execute("UPDATE device_imports SET metadata_json=? WHERE id=?", (json.dumps(state), state_row["id"]))


def process_one(settings: Settings, *, now: float | None = None) -> bool:
    """Claim one leased job; a process crash leaves it reclaimable after expiry."""
    if not ow.configured(settings):
        return False
    now = time.time() if now is None else now
    token = uuid.uuid4().hex
    job, expected = _claim_job(settings, now, token)
    if job is None:
        return False
    if expected is None:
        return True
    expected = (*expected, job["id"], token)
    stop = threading.Event()
    heartbeat = _start_heartbeat(settings, job, token, stop)
    start = job["next_day"]
    end = min(date.fromisoformat(start) + timedelta(days=WINDOW_DAYS - 1), date.fromisoformat(job["end_day"])).isoformat()
    failures: dict = {}
    try:
        counts, failures = ow._sync_window(settings, job["owner_user_id"], start, end, expected)
        try:
            counts["raw_timeseries"] = sync_raw_timeseries(settings, job["owner_user_id"], start, end, expected)
        except Exception as exc:
            failures["raw_timeseries"] = _error_code(exc)
        if failures:
            # Only dataset names and codes enter operational error fields.
            raise ow.OpenWearablesError(";".join(sorted(failures)))
        done, cumulative = _advance_job(settings, job, token, expected, end, counts)
        _record_window_success(settings, job, expected, done, cumulative)
    except Exception as exc:
        _record_window_failure(settings, job, token, expected, exc, failures)
    finally:
        stop.set()
        heartbeat.join(timeout=1)
    return True


def retry_jobs(settings: Settings, *, user_ids: list[str] | None = None) -> int:
    with transaction(settings, immediate=True) as db:
        query = "UPDATE openwearables_sync_jobs SET status='queued',attempts=0,available_at=0,last_error='' WHERE status IN ('retry','attention')"
        params = []
        if user_ids is not None:
            if not user_ids:
                return 0
            query += " AND owner_user_id IN (" + ",".join("?" for _ in user_ids) + ")"
            params = user_ids
        return db.execute(query, params).rowcount


def _when(value) -> str:
    """Localized date and UTC time of day, each unbreakable; the line may
    break only between them on a narrow phone column."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, UTC)
    else:
        moment = datetime.fromisoformat(str(value))
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    return format_date_localized(moment.date().isoformat()).replace(" ", "\u00a0") + f", {moment:%H:%M}\u00a0UTC"


def _job_view(row) -> dict:
    counts = json.loads(row["counts_json"] or "{}")
    start, end = (format_date_localized(row[k]) for k in ("start_day", "end_day"))
    return dict(row) | {
        "error_labels": ow.datatype_labels(filter(None, row["last_error"].split(","))),
        # One line on a phone: no break inside a date, nor after the dash
        # (a break opportunity no-break space alone does not remove; the word
        # joiner does).
        "period": (start if start == end else f"{start} -\u2060 {end}").replace(" ", "\u00a0"),
        "started": _when(row["created_at"]), "finished": _when(row["updated_at"]),
        "records": sum(v for k, v in counts.items() if k != "raw_timeseries"),
        "samples": counts.get("raw_timeseries", 0), "fetched": bool(counts),
    }


def job_rows(settings: Settings, *, offset: int = 0, limit: int = JOBS_SHOWN) -> list[dict]:
    """Background checks for the administrator's lazily loaded full list."""
    with connect(settings) as db:
        rows = db.execute("SELECT * FROM openwearables_sync_jobs ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                          (limit, offset)).fetchall()
    return [_job_view(r) for r in rows]


def operational_status(settings: Settings, user_id: str | None = None) -> dict:
    """Local, secret-free operational evidence; suitable for admin/profile context.

    Cheap on every render: bounded job and receipt lists and the maintained
    sample total — never a count over the raw archive.
    """
    server = ow.ow_settings(settings)["url"]
    owner_clause, owner_params = (" WHERE owner_user_id=?", (user_id,)) if user_id else ("", ())
    with connect(settings) as db:
        accounts = _accounts(db, server)
        if user_id:
            accounts = [a for a in accounts if a["user_id"] == user_id]
        jobs = db.execute("SELECT * FROM openwearables_sync_jobs" + owner_clause + " ORDER BY created_at DESC, id LIMIT ?",
                          (*owner_params, JOBS_SHOWN)).fetchall()
        job_total = db.execute("SELECT count(*) FROM openwearables_sync_jobs" + owner_clause, owner_params).fetchone()[0]
        last_check = db.execute("SELECT max(updated_at) FROM openwearables_sync_jobs WHERE status='complete'"
                                + (" AND owner_user_id=?" if user_id else ""), owner_params).fetchone()[0]
        next_check = db.execute("SELECT min(next_catchup_at) FROM openwearables_schedule" + owner_clause, owner_params).fetchone()[0]
        raw = archive.totals(db, user_id)
        subscriptions = db.execute("SELECT id,server_url,endpoint_id,callback_url,remote_user_id,filter_types_json,enabled,status,last_error,updated_at FROM openwearables_subscriptions ORDER BY created_at DESC").fetchall() if not user_id else []
        if user_id:
            receipts = db.execute("""SELECT r.id,r.event_type,r.status,r.received_at FROM openwearables_receipts r
                JOIN openwearables_receipt_targets t ON t.receipt_id=r.id WHERE t.owner_user_id=? ORDER BY r.id DESC LIMIT 30""", (user_id,)).fetchall()
        else:
            receipts = db.execute("SELECT id,event_type,status,received_at FROM openwearables_receipts ORDER BY id DESC LIMIT 30").fetchall()
    return {"subscriptions": [dict(r) | {"public_url": r["callback_url"].rsplit("/webhooks/openwearables/", 1)[0],
            "filter_types": ", ".join(json.loads(r["filter_types_json"]))} for r in subscriptions],
            "jobs": [_job_view(r) for r in jobs], "job_total": job_total,
            "last_check": _when(last_check), "next_check": _when(next_check) if next_check else "",
            "receipts": [dict(r) | {"received": _when(r["received_at"])} for r in receipts],
            "raw_sample_count": raw["samples"], "raw_compacting": raw["compacting"],
            "linked_accounts": [{"user_id": a["user_id"], "email": a["email"], "remote_user_id": a["external_user_id"]} for a in accounts]}


def start_worker(settings: Settings) -> tuple[threading.Event, threading.Thread, threading.Thread]:
    stop = threading.Event()
    # The one-off raw-archive compaction runs beside sync, never before
    # startup completes: it yields the write lock between short steps.
    compaction = threading.Thread(target=archive.run_conversion, args=(settings, stop), daemon=True,
                                  name="anamna-openwearables-archive")
    compaction.start()

    def run():
        while not stop.is_set():
            try:
                started = time.monotonic()
                scheduled = schedule_due(settings)
                worked = process_one(settings)
                # One line per run that did something; an idle 30-second
                # check is not news.
                if scheduled or worked:
                    log_run(logger, "openwearables", started, {"scheduled": scheduled, "processed": int(worked)})
            except Exception as exc:
                logger.warning("OpenWearables worker cycle failed: %s", _error_code(exc))
                worked = False
            stop.wait(2 if worked else 30)

    thread = threading.Thread(target=run, daemon=True, name="anamna-openwearables-worker")
    thread.start()
    return stop, thread, compaction


def stop_worker(handle: tuple) -> None:
    handle[0].set()
    for thread in handle[1:]:
        thread.join(timeout=2)
