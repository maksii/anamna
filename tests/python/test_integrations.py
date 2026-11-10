"""Wearable provider linking (Garmin, Oura) — the skeleton's contract.

Under test: the feature is invisible until the operator stores client
credentials; Connect mints single-use state (plus PKCE for Garmin) and sends
the browser to the provider; the callback refuses a forged, expired or
replayed state and stores tokens on success; webhooks verify what can be
verified (Oura's challenge and HMAC signature, Garmin's client-id header,
shape and size) and
only ever insert the raw payload.  HTTP is stubbed at the ``_request`` seam,
exactly as the Paperless tests do.  URL contract: docs/provider-integrations.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from anamna import garmin, integrations, oura, security
from anamna.db import connect

from test_web_issue_reports import csrf_for
from test_web_panels import build

ENV_KEYS = (
    "PAPERLESS_URL",
    "ANAMNA_GARMIN_CLIENT_ID",
    "ANAMNA_GARMIN_CLIENT_SECRET",
    "ANAMNA_OURA_CLIENT_ID",
    "ANAMNA_OURA_CLIENT_SECRET",
    "ANAMNA_PUBLIC_URL",
    "ANAMNA_GARMIN_PERSONAL",
)


def isolate(monkeypatch) -> None:
    """No ambient configuration, no throttle state left by an earlier test."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    security._attempts.clear()


def configure(settings, *provider_keys: str) -> None:
    values: dict[str, str] = {}
    for key in provider_keys:
        values[f"{key}_client_id"] = f"{key}-client-id"
        values[f"{key}_client_secret"] = f"{key}-client-secret"
    integrations.save_integration_settings(settings, values)


def token_reply(**extra) -> dict:
    return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600, **extra}


def connection_rows(settings):
    with connect(settings) as db:
        return db.execute("SELECT * FROM provider_connections").fetchall()


def event_rows(settings):
    with connect(settings) as db:
        return db.execute("SELECT * FROM provider_events").fetchall()


# --- visibility --------------------------------------------------------------


def test_invisible_until_the_operator_stores_credentials(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, user_id, client = build(tmp_path)
    page = client.get("/profile").text
    assert "/integrations/" not in page
    assert "profile-panel-connections" not in page  # no tab, no panel
    configure(settings, "oura")
    page = client.get("/profile").text
    assert "/integrations/oura/connect" in page
    assert "/integrations/garmin/connect" not in page  # garmin still unconfigured
    # An unconfigured provider's routes do not exist either.
    response = client.get("/integrations/garmin/connect", follow_redirects=False)
    assert response.status_code == 404


# --- the dance out -----------------------------------------------------------


def test_connect_sends_the_browser_to_the_provider(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, user_id, client = build(tmp_path)
    configure(settings, "garmin", "oura")

    response = client.get("/integrations/garmin/connect", follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    query = {key: values[0] for key, values in parse_qs(target.query).items()}
    assert f"{target.scheme}://{target.netloc}{target.path}" == integrations.PROVIDERS["garmin"].authorize_url
    assert query["client_id"] == "garmin-client-id"
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"]
    assert query["redirect_uri"] == "http://testserver/integrations/garmin/callback"
    with connect(settings) as db:
        row = db.execute("SELECT * FROM oauth_states WHERE state=?", (query["state"],)).fetchone()
    assert row["provider"] == "garmin" and row["user_id"] == user_id and row["code_verifier"]

    response = client.get("/integrations/oura/connect", follow_redirects=False)
    query = {key: values[0] for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()}
    assert query["scope"] == integrations.PROVIDERS["oura"].scopes
    assert "code_challenge" not in query  # plain authorization-code flow


def test_connect_is_a_navigation_because_form_action_would_block_it(tmp_path: Path, monkeypatch):
    """Chrome checks form-action against every redirect hop a form submission
    lands on, and a provider's OAuth entry bounces through its own SSO hosts
    (cloud.ouraring.com → moi.ouraring.com) — so Connect must be a link, and
    the CSP must stay strict. Found in a real browser, kept fixed here."""
    isolate(monkeypatch)
    settings, user_id, client = build(tmp_path)
    configure(settings, "oura")
    csp = client.get("/login").headers["content-security-policy"]
    assert "form-action 'self'; " in csp  # strict — no provider allowlist creep
    page = client.get("/profile?tab=connections").text
    assert 'href="/integrations/oura/connect"' in page
    assert 'action="/integrations/oura/connect"' not in page  # never a form again


def test_registered_public_url_beats_what_the_proxy_shows_us(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, user_id, client = build(tmp_path)
    configure(settings, "oura")
    integrations.save_integration_settings(
        settings, {"integrations_public_url": "https://health.example.test"}
    )
    response = client.get("/integrations/oura/connect", follow_redirects=False)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_uri"] == ["https://health.example.test/integrations/oura/callback"]


# --- the dance back ----------------------------------------------------------


def test_callback_refuses_a_state_it_never_minted(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, _, client = build(tmp_path)
    configure(settings, "oura")
    response = client.get(
        "/integrations/oura/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/profile?error=integrations.error_state"
    assert connection_rows(settings) == []


def test_callback_stores_the_connection_and_state_is_single_use(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    # The OAuth layer under test, not the sync it kicks off — test_oura.py owns that.
    monkeypatch.setattr(oura, "start_connect_tasks", lambda *args: None)
    settings, user_id, client = build(tmp_path)
    configure(settings, "oura")
    begin = client.get("/integrations/oura/connect", follow_redirects=False)
    state = parse_qs(urlsplit(begin.headers["location"]).query)["state"][0]

    calls: list = []

    def fake_request(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return token_reply(scope="daily heartrate")

    monkeypatch.setattr(integrations, "_request", fake_request)
    done = client.get(
        f"/integrations/oura/callback?code=code-1&state={state}", follow_redirects=False
    )
    assert done.headers["location"] == "/profile?saved=integration_connected"
    exchanged = calls[0]
    assert exchanged["url"] == integrations.PROVIDERS["oura"].token_url
    assert exchanged["data"]["code"] == "code-1"
    assert exchanged["data"]["redirect_uri"] == "http://testserver/integrations/oura/callback"
    (row,) = connection_rows(settings)
    assert row["user_id"] == user_id and row["provider"] == "oura"
    assert row["access_token"] == "access-1" and row["refresh_token"] == "refresh-1"
    assert row["token_expires_at"] and row["scopes"] == "daily heartrate"
    # Completing an Oura connection mints the webhook verification token.
    assert integrations.oura_verification_token(settings)
    # The connected account is now offered a disconnect, not a second connect.
    page = client.get("/profile").text
    assert "/integrations/oura/disconnect" in page
    # A replayed callback must not exchange twice.
    replay = client.get(
        f"/integrations/oura/callback?code=code-1&state={state}", follow_redirects=False
    )
    assert replay.headers["location"] == "/profile?error=integrations.error_state"
    assert len(calls) == 1


def test_granted_scopes_diff_names_what_the_provider_withheld(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    monkeypatch.setattr(oura, "start_connect_tasks", lambda *args: None)
    settings, user_id, client = build(tmp_path)
    configure(settings, "oura")
    begin = client.get("/integrations/oura/connect", follow_redirects=False)
    state = parse_qs(urlsplit(begin.headers["location"]).query)["state"][0]
    # The real shape measured 2026-08-07: Oura echoes granted scopes with an
    # extapi: prefix, and heart_health plus ring_configuration were withheld.
    granted = ("extapi:daily extapi:heartrate extapi:workout extapi:session "
               "extapi:spo2 extapi:tag extapi:personal")
    monkeypatch.setattr(integrations, "_request", lambda url, **kwargs: token_reply(scope=granted))
    client.get(f"/integrations/oura/callback?code=code-1&state={state}", follow_redirects=False)
    (row,) = connection_rows(settings)
    assert row["scopes"] == granted  # the echo persists verbatim on the row
    provider = integrations.PROVIDERS["oura"]
    assert integrations.missing_scopes(provider, row["scopes"]) == [
        "heart_health", "ring_configuration",
    ]
    # Everything granted — or no scope echoed, where the requested set is
    # stored instead — diffs to nothing missing.
    assert integrations.missing_scopes(provider, provider.scopes) == []


def test_pressing_deny_at_the_provider_connects_nothing(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, _, client = build(tmp_path)
    configure(settings, "garmin")
    response = client.get(
        "/integrations/garmin/callback?error=access_denied", follow_redirects=False
    )
    assert response.headers["location"] == "/profile?error=integrations.error_denied"
    assert connection_rows(settings) == []


def test_disconnect_deletes_locally_even_when_revoke_fails(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, user_id, client = build(tmp_path)
    configure(settings, "garmin")
    integrations.save_connection(
        settings, user_id, "garmin",
        access_token="access-1", refresh_token="refresh-1",
        expires_at=None, external_user_id="g-1", scopes="",
    )

    def refuse(url, **kwargs):
        raise integrations.IntegrationError("provider is down")

    monkeypatch.setattr(integrations, "_request", refuse)
    response = client.post(
        "/integrations/garmin/disconnect",
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/profile?saved=integration_disconnected"
    assert connection_rows(settings) == []


# --- webhooks ----------------------------------------------------------------


def test_oura_challenge_is_echoed_only_for_our_verification_token(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    settings, _, client = build(tmp_path)
    # No token stored yet: the endpoint answers nothing, whatever is sent.
    assert client.get(
        "/integrations/oura/webhook?verification_token=x&challenge=c1"
    ).status_code == 401
    integrations.save_integration_settings(settings, {"oura_verification_token": "vt-secret"})
    good = client.get("/integrations/oura/webhook?verification_token=vt-secret&challenge=c1")
    assert good.status_code == 200 and good.json() == {"challenge": "c1"}
    assert client.get(
        "/integrations/oura/webhook?verification_token=wrong&challenge=c1"
    ).status_code == 401


def test_oura_events_need_the_signature_garmin_events_need_the_shape(tmp_path: Path, monkeypatch):
    isolate(monkeypatch)
    # Receipt only; the processing thread is test_oura.py's subject.
    monkeypatch.setattr(oura, "start_processing", lambda *args: None)
    settings, _, client = build(tmp_path)
    configure(settings, "oura")
    body = json.dumps(
        {"event_type": "create", "data_type": "sleep", "object_id": "obj-1", "user_id": "u-1"}
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"oura-client-secret", timestamp.encode() + body, hashlib.sha256
    ).hexdigest().upper()
    accepted = client.post(
        "/integrations/oura/webhook",
        content=body,
        headers={"x-oura-timestamp": timestamp, "x-oura-signature": signature},
    )
    assert accepted.status_code == 200
    tampered = client.post(
        "/integrations/oura/webhook",
        content=body + b" ",
        headers={"x-oura-timestamp": timestamp, "x-oura-signature": signature},
    )
    assert tampered.status_code == 401
    unsigned = client.post("/integrations/oura/webhook", content=body)
    assert unsigned.status_code == 401

    monkeypatch.setattr(garmin, "start_processing", lambda *args: None)
    garmin_body = json.dumps({"dailies": [{"summaryId": "s-1"}]}).encode()
    # Unconfigured, the endpoint does not exist.
    assert client.post("/integrations/garmin/webhook", content=garmin_body).status_code == 404
    configure(settings, "oura", "garmin")
    ours = {"garmin-client-id": "garmin-client-id"}
    # Garmin does not sign; its client-id header is the gate.
    assert client.post("/integrations/garmin/webhook", content=garmin_body).status_code == 401
    assert client.post("/integrations/garmin/webhook", content=garmin_body,
                       headers={"garmin-client-id": "someone-else"}).status_code == 401
    assert client.post("/integrations/garmin/webhook", content=garmin_body, headers=ours).status_code == 200
    assert client.post("/integrations/garmin/webhook", content=b"not json", headers=ours).status_code == 400
    assert client.post("/integrations/garmin/webhook", content=b"[1, 2]", headers=ours).status_code == 400

    stored = event_rows(settings)
    assert [(row["provider"]) for row in stored] == ["oura", "garmin"]
    assert json.loads(stored[0]["payload"])["object_id"] == "obj-1"
    assert all(row["processed_at"] is None for row in stored)  # processing comes later
