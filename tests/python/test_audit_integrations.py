"""Audit fixes for the three integration HTTP seams and the webhook and link guards.

Covered here: every HTTP helper refuses a response larger than its limit, only
Paperless's own refusals count towards the upload cap, an Oura webhook replayed
after its timestamp went stale is refused, and one remote wearable account can
never feed two local records.  HTTP is faked at each module's ``_opener``, the
one door its requests go through.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import time
import urllib.error
from pathlib import Path

import pytest

from anamna import integrations, openwearables, paperless, security
from anamna.db import connect, migrate, utc_now

from test_paperless import build, configure_paperless, connect_user
from test_web_panels import settings_for


class _Reply:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body[:size] if size >= 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _Opener:
    """Answers every request with ``body``, or raises ``error`` instead."""

    def __init__(self, *, body: bytes = b"", error: BaseException | None = None):
        self._body = body
        self._error = error

    def open(self, request, timeout=None):
        if self._error is not None:
            raise self._error
        return _Reply(self._body)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://paperless.test/api/documents/post_document/", code, "reason", {}, io.BytesIO(b'{"detail": "x"}')
    )


# --- response size ------------------------------------------------------------


def test_paperless_refuses_a_response_over_the_limit(monkeypatch):
    monkeypatch.setattr(paperless, "MAX_RESPONSE_BYTES", 10)
    monkeypatch.setattr(paperless, "_opener", _Opener(body=b"x" * 11))
    with pytest.raises(paperless.PaperlessError, match="response too large"):
        paperless._request("http://paperless.test", "tok", "/api/documents/")


def test_openwearables_refuses_a_response_over_the_limit(monkeypatch):
    monkeypatch.setattr(openwearables, "MAX_RESPONSE_BYTES", 10)
    monkeypatch.setattr(openwearables, "_opener", _Opener(body=b"x" * 11))
    with pytest.raises(openwearables.OpenWearablesError, match="response too large"):
        openwearables._request("https://ow.test/api/v1/users")


def test_integrations_refuses_a_response_over_the_limit(monkeypatch):
    monkeypatch.setattr(integrations, "MAX_RESPONSE_BYTES", 10)
    monkeypatch.setattr(integrations, "_opener", _Opener(body=b"x" * 11))
    with pytest.raises(integrations.IntegrationError, match="response too large"):
        integrations._request("https://oura.test/v2/usercollection/sleep")


def test_the_response_cap_matches_the_largest_pushed_body():
    assert integrations.MAX_RESPONSE_BYTES == integrations.MAX_EVENT_BYTES


def test_a_response_at_the_limit_is_still_read(monkeypatch):
    monkeypatch.setattr(openwearables, "MAX_RESPONSE_BYTES", 10)
    monkeypatch.setattr(openwearables, "_opener", _Opener(body=b"[1, 2, 3]"))
    assert openwearables._request("https://ow.test/api/v1/users") == [1, 2, 3]


# --- Paperless: only its own refusals count towards the cap --------------------


def test_paperless_error_carries_the_http_status():
    assert paperless.PaperlessError("HTTP 400: duplicate").status == 400
    assert paperless.PaperlessError("HTTP 503: busy", status=503).status == 503
    assert paperless.PaperlessError("down").status is None


@pytest.mark.parametrize(
    ("error", "attempts"),
    [
        (urllib.error.URLError("refused"), 0),
        (TimeoutError("timed out"), 0),
        (_http_error(503), 0),
        (_http_error(408), 0),
        (_http_error(429), 0),
        (_http_error(400), 1),
    ],
    ids=["refused", "timeout", "503", "408", "429", "400"],
)
def test_only_paperless_refusals_count_towards_the_upload_cap(tmp_path: Path, monkeypatch, error, attempts):
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    monkeypatch.setattr(paperless, "_opener", _Opener(error=error))
    assert paperless.push_document(settings, "doc-1") is False
    with connect(settings) as connection:
        stored = connection.execute("SELECT paperless_attempts FROM documents WHERE id='doc-1'").fetchone()[0]
    assert stored == attempts


# --- Oura webhook replay ------------------------------------------------------


def test_stale_timestamp_judges_only_unix_epoch_values():
    now = int(time.time())
    assert integrations._stale_timestamp(str(now)) is False
    assert integrations._stale_timestamp(str(now - 3600)) is True
    assert integrations._stale_timestamp(str(now * 1000)) is False
    assert integrations._stale_timestamp("2026-01-01T00:00:00Z") is False
    assert integrations._stale_timestamp("") is False


def _oura_signature(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + body, hashlib.sha256).hexdigest().upper()


def test_a_replayed_oura_delivery_with_a_valid_signature_is_refused():
    body = b'{"event_type": "update", "data_type": "sleep"}'
    old = str(int(time.time()) - 3600)
    assert integrations.verify_oura_signature("secret", old, body, _oura_signature("secret", old, body)) is False
    now = str(int(time.time()))
    assert integrations.verify_oura_signature("secret", now, body, _oura_signature("secret", now, body)) is True


# --- one remote wearable account, one local record ----------------------------


def test_a_remote_account_cannot_feed_two_local_records(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_a = security.create_user(settings, "ow-a@example.test", "Alpha", "another-long-password")
    user_b = security.create_user(settings, "ow-b@example.test", "Beta", "another-long-password")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO provider_connections(user_id, provider, external_user_id, connected_at, updated_at)
               VALUES (?, ?, 'r1', ?, ?)""",
            (user_a, openwearables.PROVIDER, utc_now(), utc_now()),
        )
    assert openwearables.linked_elsewhere(settings, user_b, "r1") is True
    assert openwearables.linked_elsewhere(settings, user_a, "r1") is False
    assert openwearables.linked_elsewhere(settings, user_b, "r2") is False
