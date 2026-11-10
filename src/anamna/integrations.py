"""Wearable provider linking (Garmin, Oura) — the OAuth dance and webhook receipt.

Contract, registration URLs and provider endpoint references:
docs/provider-integrations.md.  This module owns connecting an account
(begin → provider → callback → stored tokens), disconnecting it, keeping the
tokens fresh, and taking delivery of webhook payloads.  It does *not* turn
payloads into observations: events are kept raw in ``provider_events`` and
oura.py / garmin.py process them, re-runnably, off the request thread.

Configuration follows the Paperless pattern: client credentials are app-level,
read from ``app_settings`` with an environment fallback that seeds an
unconfigured instance — once a value has been stored it wins even when empty.
A provider with no client id and secret simply does not exist in the UI.

Verified against provider documentation on 2026-08-07:

* Garmin (Starter/Enterprise tiers, re-verified 2026-11-05): OAuth2 + PKCE
  (S256) per developerportal.garmin.com/sites/default/files/OAuth2PKCE.pdf;
  access tokens live 24 h, refresh tokens ~90 days and rotate on every use.
  The Health API pushes JSON (or pings) to endpoints configured in the portal,
  unsigned but carrying a ``garmin-client-id`` header, and expects HTTP 200
  within 30 s, redelivering on anything else. The Personal tier is not OAuth
  at all — see garmin_personal.py.
* Oura: plain OAuth2 authorization-code (cloud.ouraring.com/docs/authentication);
  refresh tokens are single-use.  Webhooks (api.ouraring.com/v2/docs) verify the
  callback once with ``GET ?verification_token=&challenge=`` expecting
  ``{"challenge": …}`` back, then POST events signed with
  ``x-oura-signature`` = HMAC-SHA256(``x-oura-timestamp`` + raw body,
  key = client secret, uppercase hex).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import USER_AGENT, Settings, per_request
from .db import connect, transaction, utc_now

logger = logging.getLogger("anamna.integrations")

REQUEST_TIMEOUT = 15

#: An authorize page abandoned longer than this restarts the flow.
STATE_TTL_SECONDS = 600

#: A webhook body larger than this is refused unread. Garmin's production
#: review requires accepting at least 10 MB (100 MB for activity details), and
#: Cloudflare in front of the sandbox caps request bodies at 100 MB anyway.
MAX_EVENT_BYTES = 100_000_000

#: Largest response body read into memory.  Matches MAX_EVENT_BYTES, the largest
#: body a provider may push: Garmin ping callbacks fetch activity detail files of
#: that size through this helper.
MAX_RESPONSE_BYTES = MAX_EVENT_BYTES


class IntegrationError(Exception):
    """The provider refused, answered nonsense, or was unreachable.

    ``status`` carries the HTTP code when one was received — callers branch on
    it as an integer, never by substring-matching the message, which embeds up
    to 300 chars of response body that can contain anything.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class StaleStateError(IntegrationError):
    """The callback's ``state`` is unknown, expired, or belongs to someone else."""


@dataclass(frozen=True)
class Provider:
    key: str
    display_name: str  # brand name, identical in every locale
    authorize_url: str
    token_url: str
    scopes: str  # space-separated; "" when the portal grants them app-wide
    pkce: bool


PROVIDERS: dict[str, Provider] = {
    # Garmin Starter/Enterprise (business) credentials. Processing lives in
    # garmin.py. The token host is the one Garmin's production integrators use
    # (open-wearables); the PKCE PDF also names connectapi.garmin.com.
    "garmin": Provider(
        key="garmin",
        display_name="Garmin",
        authorize_url="https://connect.garmin.com/oauth2Confirm",
        token_url="https://diauth.garmin.com/di-oauth2-service/oauth/token",
        scopes="",
        pkce=True,
    ),
    "oura": Provider(
        key="oura",
        display_name="Oura",
        authorize_url="https://cloud.ouraring.com/oauth/authorize",
        token_url="https://api.ouraring.com/oauth/token",
        # Everything clinical the ring measures; deliberately not `email` —
        # the account identity here is ours, not Oura's.  `heart_health`
        # (cardiovascular age, VO₂ max) and `ring_configuration` are absent
        # from Oura's documentation but named verbatim by the API's own 401s;
        # measured against a live account on 2026-08-07.
        scopes="daily heartrate workout session spo2 tag personal heart_health ring_configuration",
        pkce=False,
    ),
}

GARMIN_USER_ID_URL = "https://apis.garmin.com/wellness-api/rest/user/id"
GARMIN_DEREGISTER_URL = "https://apis.garmin.com/wellness-api/rest/user/registration"
OURA_REVOKE_URL = "https://api.ouraring.com/oauth/revoke"


# --- configuration -----------------------------------------------------------

SETTING_KEYS = (
    "garmin_client_id",
    "garmin_client_secret",
    "oura_client_id",
    "oura_client_secret",
    "oura_verification_token",
    "integrations_public_url",
    "garmin_personal_enabled",
)

#: Environment fallbacks that seed an unconfigured instance, exactly like
#: PAPERLESS_URL does for Paperless.
_ENV_KEYS = {
    "garmin_client_id": "ANAMNA_GARMIN_CLIENT_ID",
    "garmin_client_secret": "ANAMNA_GARMIN_CLIENT_SECRET",
    "oura_client_id": "ANAMNA_OURA_CLIENT_ID",
    "oura_client_secret": "ANAMNA_OURA_CLIENT_SECRET",
    "integrations_public_url": "ANAMNA_PUBLIC_URL",
    # Operator consent for Garmin Personal API keys ("1" to offer the card);
    # each person still brings their own key.
    "garmin_personal_enabled": "ANAMNA_GARMIN_PERSONAL",
}


@per_request
def integration_settings(settings: Settings) -> dict[str, str]:
    placeholders = ", ".join("?" for _ in SETTING_KEYS)
    with connect(settings) as connection:
        stored = dict(
            connection.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", SETTING_KEYS
            ).fetchall()
        )
    # A stored row wins even when empty — clearing a credential must not
    # silently reinstate the environment's value (same rule as Paperless).
    return {
        key: (stored[key] if key in stored else os.getenv(_ENV_KEYS.get(key, ""), "")).strip()
        for key in SETTING_KEYS
    }


def save_integration_settings(settings: Settings, values: dict[str, str]) -> None:
    with connect(settings) as connection:
        for key, value in values.items():
            connection.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, utc_now()),
            )


def client_config(settings: Settings, provider: Provider) -> tuple[str, str]:
    config = integration_settings(settings)
    return config[f"{provider.key}_client_id"], config[f"{provider.key}_client_secret"]


def configured(settings: Settings, provider: Provider) -> bool:
    client_id, client_secret = client_config(settings, provider)
    return bool(client_id and client_secret)


def configured_providers(settings: Settings) -> list[Provider]:
    return [provider for provider in PROVIDERS.values() if configured(settings, provider)]


def redirect_uri(settings: Settings, provider: Provider, fallback_base: str) -> str:
    """The exact string registered with the provider — see the contract doc.

    ``integrations_public_url`` exists because ``request.base_url`` behind the
    Cloudflare tunnel reports ``http://``, which fails the provider's exact
    match against the registered ``https://`` URI.
    """
    base = integration_settings(settings)["integrations_public_url"] or fallback_base
    return f"{base.rstrip('/')}/integrations/{provider.key}/callback"


def oura_verification_token(settings: Settings) -> str:
    return integration_settings(settings)["oura_verification_token"]


def ensure_oura_verification_token(settings: Settings) -> str:
    """The token our webhook subscription will carry; minted on first need.

    Called from the authenticated flow (completing an Oura connection), never
    from the unauthenticated webhook route — an anonymous GET must not be able
    to make this endpoint start answering challenges.
    """
    token = oura_verification_token(settings)
    if not token:
        token = secrets.token_urlsafe(24)
        save_integration_settings(settings, {"oura_verification_token": token})
    return token


# --- stored connections ------------------------------------------------------


def connection_row(settings: Settings, user_id: str, provider_key: str):
    with connect(settings) as connection:
        return connection.execute(
            "SELECT * FROM provider_connections WHERE user_id=? AND provider=?",
            (user_id, provider_key),
        ).fetchone()


def save_connection(
    settings: Settings,
    user_id: str,
    provider_key: str,
    *,
    access_token: str,
    refresh_token: str,
    expires_at: str | None,
    external_user_id: str,
    scopes: str,
    expected_refresh_token: str | None = None,
) -> None:
    now = utc_now()
    with transaction(settings, immediate=True) as connection:
        if expected_refresh_token is not None and connection.execute(
            "SELECT 1 FROM provider_connections WHERE user_id=? AND provider=? AND refresh_token=?",
            (user_id, provider_key, expected_refresh_token),
        ).fetchone() is None:
            raise IntegrationError(f"{provider_key}: connection changed during token refresh")
        if provider_key == "oura":
            _reconcile_oura_account(connection, user_id, external_user_id)
        connection.execute(
            """INSERT INTO provider_connections(user_id, provider, access_token, refresh_token,
                       token_expires_at, external_user_id, scopes, connected_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET
                   access_token = excluded.access_token,
                   refresh_token = excluded.refresh_token,
                   token_expires_at = excluded.token_expires_at,
                   external_user_id = excluded.external_user_id,
                   scopes = excluded.scopes,
                   updated_at = excluded.updated_at,
                   status = 'active'""",
            (user_id, provider_key, access_token, refresh_token, expires_at,
             external_user_id, scopes, now, now),
        )


def _reconcile_oura_account(connection, user_id: str, external_user_id: str) -> None:
    """Keep remote identity with retained history across disconnect/reconnect.

    OAuth initially has no personal-info ID. Preserve the old identity through
    that gap, then purge only API-owned data if the confirmed account differs.
    """
    envelope = connection.execute(
        "SELECT id, metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key='oura_api'", (user_id,)
    ).fetchone()
    if envelope is None:
        return
    state = json.loads(envelope["metadata_json"])
    prior_connection = connection.execute(
        "SELECT external_user_id FROM provider_connections WHERE user_id=? AND provider='oura'", (user_id,)
    ).fetchone()
    previous = str(state.get("source_account_id") or (prior_connection[0] if prior_connection else "") or "")
    if external_user_id and previous and previous != external_user_id:
        for table in ("device_metric_days", "device_workouts", "device_events"):
            connection.execute(f"DELETE FROM {table} WHERE import_id=?", (envelope["id"],))
        state = {}
    identity = external_user_id or previous
    if identity:
        state["source_account_id"] = identity
        connection.execute(
            """UPDATE device_imports SET metadata_json=?,
                raw_record_count=(SELECT COUNT(*) FROM device_metric_days WHERE import_id=?) WHERE id=?""",
            (json.dumps(state, ensure_ascii=False), envelope["id"], envelope["id"]),
        )


def missing_scopes(provider: Provider, granted: str) -> list[str]:
    """Requested scopes the provider withheld — the UI's cue to prompt a
    reconnect, in the requested order.

    ``granted`` is the connection row's ``scopes`` column, which stores the
    token endpoint's ``scope`` echo verbatim (or the full requested set when
    nothing was echoed). Oura prefixes granted scopes ``extapi:`` — measured
    against a live account on 2026-08-07 — so tokens compare with any prefix
    stripped. Derived rather than persisted so a scope added to the requested
    list later shows as missing immediately.
    """
    have = {token.split(":", 1)[-1] for token in granted.split()}
    return [scope for scope in provider.scopes.split() if scope not in have]


# --- the OAuth dance ---------------------------------------------------------


def begin_oauth(settings: Settings, user_id: str, provider: Provider, redirect: str) -> str:
    """Mint and persist the transient state; returns the URL to send the browser to."""
    client_id, _ = client_config(settings, provider)
    state = secrets.token_urlsafe(32)
    verifier = ""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "state": state,
    }
    if provider.scopes:
        params["scope"] = provider.scopes
    if provider.pkce:
        # 43–128 chars from the RFC 7636 alphabet; token_urlsafe(64) gives ~86.
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    with connect(settings) as connection:
        # One attempt in flight per person and provider; starting over
        # invalidates the abandoned authorize page rather than accumulating.
        connection.execute(
            "DELETE FROM oauth_states WHERE user_id=? AND provider=?", (user_id, provider.key)
        )
        connection.execute(
            "INSERT INTO oauth_states(state, user_id, provider, code_verifier, created_at) VALUES (?, ?, ?, ?, ?)",
            (state, user_id, provider.key, verifier, utc_now()),
        )
    return f"{provider.authorize_url}?{urllib.parse.urlencode(params)}"


def complete_oauth(
    settings: Settings, user_id: str, provider: Provider, *, code: str, state: str, redirect: str
) -> None:
    """Validate the callback, exchange the code, store the connection."""
    with connect(settings) as connection:
        # Consume in one atomic statement. A SELECT followed by DELETE lets
        # concurrent callbacks both exchange; an ownerless DELETE also lets
        # an invalid callback invalidate someone else's sign-in attempt.
        row = connection.execute(
            "DELETE FROM oauth_states WHERE state=? AND user_id=? AND provider=? RETURNING *",
            (state, user_id, provider.key),
        ).fetchone()
    if (
        not code
        or row is None
        or row["user_id"] != user_id
        or row["provider"] != provider.key
        or _age_seconds(row["created_at"]) > STATE_TTL_SECONDS
    ):
        raise StaleStateError(provider.key)

    client_id, client_secret = client_config(settings, provider)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if provider.pkce:
        data["code_verifier"] = row["code_verifier"]
    payload = _request(provider.token_url, data=data, method="POST")
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise IntegrationError(f"{provider.key}: token endpoint answered without an access_token")

    expires_at = None
    if payload.get("expires_in"):
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"])))
            .replace(microsecond=0)
            .isoformat()
        )
    save_connection(
        settings,
        user_id,
        provider.key,
        access_token=str(payload["access_token"]),
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_at=expires_at,
        external_user_id=_external_user_id(provider, str(payload["access_token"])),
        scopes=str(payload.get("scope") or provider.scopes),
    )
    if provider.key == "oura":
        # The subscription we create later needs it; minting it here keeps the
        # unauthenticated webhook route read-only.
        ensure_oura_verification_token(settings)


def _external_user_id(provider: Provider, access_token: str) -> str:
    """The provider's own id for this account — how webhook payloads name people.

    Best-effort: a connection that works today but could not be asked for its
    id is stored anyway, and processing falls back to matching by token.
    """
    if provider.key != "garmin":
        return ""  # Oura events carry user_id resolvable through the API later
    try:
        payload = _request(GARMIN_USER_ID_URL, headers={"Authorization": f"Bearer {access_token}"})
    except IntegrationError as exc:
        logger.warning("garmin: connected but user id lookup failed: %s", exc)
        return ""
    return str(payload.get("userId") or "") if isinstance(payload, dict) else ""


def disconnect(settings: Settings, user_id: str, provider: Provider) -> None:
    """Forget the tokens; tell the provider first, best-effort.

    The local delete must succeed even when the provider is unreachable —
    a person removing access is not to be blocked by the service they are
    removing it from.
    """
    row = connection_row(settings, user_id, provider.key)
    if row is None:
        return
    try:
        if provider.key == "garmin":
            _request(
                GARMIN_DEREGISTER_URL,
                headers={"Authorization": f"Bearer {row['access_token']}"},
                method="DELETE",
            )
        elif provider.key == "oura":
            _request(
                f"{OURA_REVOKE_URL}?{urllib.parse.urlencode({'access_token': row['access_token']})}",
                method="POST",
            )
    except IntegrationError as exc:
        logger.warning("%s: revoke on disconnect failed: %s", provider.key, exc)
    with transaction(settings, immediate=True) as connection:
        if provider.key == "oura":
            _reconcile_oura_account(connection, user_id, "")
        connection.execute(
            "DELETE FROM provider_connections WHERE user_id=? AND provider=?",
            (user_id, provider.key),
        )


# --- token upkeep (shared by oura.py and garmin.py) ---------------------------


class ReauthorizeError(IntegrationError):
    """The refresh token was refused — only reconnecting can fix this."""


#: Refresh an access token this close to its recorded expiry.
TOKEN_SLACK_SECONDS = 120

_refresh_locks: dict[tuple[str, str], threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _lock_for(provider_key: str, user_id: str) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault((provider_key, user_id), threading.Lock())


def expires_in(row) -> float:
    """Seconds until the stored access token lapses; unknown counts as never."""
    if not row["token_expires_at"]:
        return float("inf")
    try:
        moment = datetime.fromisoformat(str(row["token_expires_at"]))
    except ValueError:
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)  # every writer stores UTC
    return (moment - datetime.now(UTC)).total_seconds()


def _expiry(payload: dict, field: str = "expires_in") -> str | None:
    if not payload.get(field):
        return None
    return (datetime.now(UTC) + timedelta(seconds=int(payload[field]))).replace(microsecond=0).isoformat()


def require_connection(settings: Settings, user_id: str, provider_key: str):
    row = connection_row(settings, user_id, provider_key)
    if row is None:
        raise IntegrationError(f"{provider_key}: not connected")
    return row


def refresh_tokens(settings: Settings, user_id: str, provider: Provider) -> None:
    """Rotate the token pair. The new pair is stored before this returns, so a
    crash after the exchange cannot strand a used-up refresh token as ours.

    Oura refresh tokens are single-use and Garmin rotates its own on every
    refresh too, so both go through the same per-account lock and the same
    compare-and-swap on the refresh token being replaced.
    """
    with _lock_for(provider.key, user_id):
        row = require_connection(settings, user_id, provider.key)  # re-read: another thread may have won
        if expires_in(row) > TOKEN_SLACK_SECONDS:
            return
        client_id, client_secret = client_config(settings, provider)
        try:
            payload = _request(
                provider.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": str(row["refresh_token"]),
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                method="POST",
            )
        except IntegrationError as exc:
            # 400/401 mean the refresh token itself was refused (invalid_grant,
            # revoked, expired). Anything else — 429, 5xx, network — is
            # transient and must not cost the person their connection.
            if exc.status in (400, 401):
                with connect(settings) as db:
                    db.execute(
                        "UPDATE provider_connections SET status='reauthorize', updated_at=? WHERE user_id=? AND provider=? AND refresh_token=?",
                        (utc_now(), user_id, provider.key, row["refresh_token"]),
                    )
                raise ReauthorizeError(str(exc)) from exc
            raise
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise IntegrationError(f"{provider.key}: refresh answered without an access_token")
        save_connection(
            settings, user_id, provider.key,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload.get("refresh_token") or row["refresh_token"]),
            expires_at=_expiry(payload),
            external_user_id=str(row["external_user_id"]),
            scopes=str(row["scopes"]),
            expected_refresh_token=str(row["refresh_token"]),
        )


def authorized_request(settings: Settings, user_id: str, provider: Provider, url: str, *, method: str = "GET"):
    """One bearer-authenticated call, refreshing the token when stale or refused."""
    row = require_connection(settings, user_id, provider.key)
    if expires_in(row) <= TOKEN_SLACK_SECONDS:
        refresh_tokens(settings, user_id, provider)
        row = require_connection(settings, user_id, provider.key)
    try:
        return _request(url, headers={"Authorization": f"Bearer {row['access_token']}"}, method=method)
    except IntegrationError as exc:
        if exc.status != 401:
            raise
        # The recorded expiry lied (revoked, or clock skew): refresh and retry
        # once. Only the token that failed is expired — a concurrent request
        # may already have rotated it, and expiring the fresh one would burn a
        # single-use refresh token for nothing.
        with connect(settings) as db:
            db.execute(
                "UPDATE provider_connections SET token_expires_at=? WHERE user_id=? AND provider=? AND access_token=?",
                (datetime.now(UTC).replace(microsecond=0).isoformat(), user_id, provider.key, row["access_token"]),
            )
        refresh_tokens(settings, user_id, provider)
        row = require_connection(settings, user_id, provider.key)
        return _request(url, headers={"Authorization": f"Bearer {row['access_token']}"}, method=method)


def _age_seconds(created_at: str) -> float:
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(created_at)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


# --- webhook receipt ---------------------------------------------------------


def _stale_timestamp(value: str, tolerance_seconds: int = 600) -> bool:
    """True only for a Unix-epoch timestamp (seconds or milliseconds) further
    than the tolerance from now.  Any other format is not judged: rejecting a
    genuine delivery over a format this code has not seen is the worse error."""
    text = value.strip()
    if not text.isascii() or not text.isdigit():
        return False
    stamp = int(text)
    if stamp > 10**11:  # milliseconds
        stamp //= 1000
    return abs(time.time() - stamp) > tolerance_seconds


def verify_oura_signature(client_secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """``x-oura-signature`` — HMAC-SHA256 over timestamp + raw body, uppercase hex.

    A valid signature alone does not prove freshness: a captured delivery
    replays with its headers intact, so an old epoch timestamp is refused too.
    """
    if not client_secret or not signature:
        return False
    digest = hmac.new(
        client_secret.encode("utf-8"), timestamp.encode("utf-8") + body, hashlib.sha256
    ).hexdigest().upper()
    valid = hmac.compare_digest(digest, signature.upper())
    return valid and not _stale_timestamp(timestamp)


def acceptable_event(body: bytes) -> bool:
    """A JSON object — the only shape either provider ever sends.

    Garmin does not sign its pushes, so this plus the size cap is the entire
    gate on that endpoint; anything failing it is counted against the sender's
    address. Real validation (does this name a connected account?) belongs to
    processing, which trusts nothing in the payload anyway.
    """
    try:
        return isinstance(json.loads(body.decode("utf-8")), dict)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def record_event(settings: Settings, provider_key: str, body: bytes) -> None:
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO provider_events(provider, payload, received_at) VALUES (?, ?, ?)",
            (provider_key, body.decode("utf-8"), utc_now()),
        )


# --- HTTP --------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Same reasoning as paperless._NoRedirect: a 3xx from a token endpoint is
    # never legitimate, and following one would replay credentials elsewhere.
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _request(
    url: str,
    *,
    data: dict[str, str] | None = None,
    json_data: object | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    raw: bool = False,
):
    """One request, parsed JSON back (``None`` for an empty body); every failure
    becomes :class:`IntegrationError`.  The seam tests stub.  ``data`` sends a
    form body (token endpoints), ``json_data`` a JSON one (Oura subscriptions);
    ``raw`` returns the body as text (Garmin's Personal API token is a bare JWT)."""
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        content_type = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode("ascii")
        content_type = "application/x-www-form-urlencoded"
    else:
        body, content_type = None, ""
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "*/*" if raw else "application/json",
            "User-Agent": USER_AGENT,
            **({"Content-Type": content_type} if body else {}),
            **(headers or {}),
        },
    )
    try:
        with _opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            body_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body_bytes) > MAX_RESPONSE_BYTES:
                raise IntegrationError("integrations: response too large")
    except urllib.error.HTTPError as exc:
        detail = exc.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")[:300]
        # Callers log the message, and a provider's error page can echo a
        # document title, so the body is kept out of it and logged at DEBUG only.
        logger.debug("upstream error body: %s", detail)
        raise IntegrationError(f"HTTP {exc.code}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IntegrationError(str(exc)) from exc
    if raw:
        return body_bytes.decode("utf-8", "replace")
    if not body_bytes:
        return None
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrationError(f"unparseable reply: {body_bytes[:200]!r}") from exc
