from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from .config import Settings
from .db import connect, transaction, utc_now


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1

ROLES = ("user", "admin")
MINIMUM_PASSWORD_LENGTH = 10

#: Failed sign-ins tolerated from one address before it is asked to wait, and
#: the window both the count and the lockout are measured in.
LOGIN_ATTEMPT_LIMIT = 10
#: Failed sign-ins tolerated against one account, from all addresses together, per window.  Higher than the per-address limit so a stranger who knows an email address has to work to lock its owner out, and low enough that guessing a ten-character password stays hopeless.
LOGIN_ACCOUNT_LIMIT = 20
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
#: Wrong current passwords tolerated on the change-password form per window: whoever holds an unattended session must not be able to guess the password it belongs to.
PASSWORD_CHANGE_LIMIT = 10


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )


class AlreadySetUp(Exception):
    """The first-run form lost: an account appeared before this one was written."""


def create_user(
    settings: Settings, email: str, display_name: str, password: str, role: str = "user",
    *, first_only: bool = False,
) -> str:
    """Create an account; the first one on the database becomes administrator.

    ``first_only`` is the first-run page's guard.  The count is read inside
    the same immediate transaction as the insert, so of two simultaneous
    setup submissions exactly one finds the table empty; the other raises
    ``AlreadySetUp`` instead of becoming a second administrator.
    """
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters")
    user_id = str(uuid.uuid4())
    salt = secrets.token_bytes(16)
    digest = password_digest(password, salt)
    safe_role = role if role in ROLES else "user"
    # `immediate` because the row count decides what is written next: a
    # deferred transaction takes its read lock first and cannot be retried.
    with transaction(settings, immediate=True) as connection:
        first_account = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        if first_only and not first_account:
            raise AlreadySetUp
        connection.execute(
            """INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at, role)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                email.strip().casefold(),
                display_name.strip(),
                salt,
                digest,
                utc_now(),
                # Whoever creates the very first account owns the installation.
                # Without this a fresh database has no administrator, and the
                # rule that keeps the last one in place would have nothing to
                # keep: the instance could only be repaired with a SQL client.
                "admin" if first_account else safe_role,
            ),
        )
    return user_id


def set_password(settings: Settings, user_id: str, password: str, keep_token: str | None = None) -> None:
    """Replace one account's password and end its other sessions.

    A new salt as well as a new hash, so two accounts that pick the same
    password still store different bytes.  Every session except the one making
    the change is revoked: a password is changed because it may be known to
    somebody else, and leaving their session alive answers the wrong half of
    the problem.
    """
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = password_digest(password, salt)
    keep_hash = hashlib.sha256(keep_token.encode()).hexdigest() if keep_token else ""
    with transaction(settings, immediate=True) as connection:
        connection.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt, digest, user_id),
        )
        connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (user_id, keep_hash)
        )


def authenticate(settings: Settings, email: str, password: str):
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE AND disabled_at IS NULL",
            (email.strip(),),
        ).fetchone()
    if row is None:
        password_digest(password, secrets.token_bytes(16))
        return None
    actual = password_digest(password, row["password_salt"])
    return row if hmac.compare_digest(actual, row["password_hash"]) else None


def create_session(
    settings: Settings,
    user_id: str,
    token_id: str | None = None,
    days: int | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    """Open a browser session, optionally on behalf of an access token.

    ``token_id`` is what makes a guest link read-only for as long as it lasts:
    the session carries the credential that minted it, so every later request
    can still tell an invited visitor from the account holder.  ``days`` lets
    that session end when the invitation does rather than outliving it.
    """
    token = secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=days if days is not None else settings.session_days)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at, token_id, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (token_hash, user_id, csrf_token, now.isoformat(), expires_at.isoformat(), token_id,
             (user_agent or "")[:300] or None),
        )
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
    return token, csrf_token


def session_user(settings: Settings, token: str | None):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    with connect(settings) as connection:
        # The access token is joined rather than trusted from the session row:
        # an expired or deleted credential must take its sessions with it, and
        # `k.kind IS NULL` for an ordinary password sign-in.
        return connection.execute(
            """SELECT u.*, s.csrf_token, s.expires_at,
                      k.kind AS token_kind, k.expires_at AS token_expires_at,
                      k.id AS token_id, k.label AS token_label
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               LEFT JOIN access_tokens k ON k.id = s.token_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled_at IS NULL
                 AND (s.token_id IS NULL
                      OR (k.id IS NOT NULL AND (k.expires_at IS NULL OR k.expires_at > ?)))""",
            (token_hash, now, now),
        ).fetchone()


def revoke_session(settings: Settings, token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect(settings) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def session_handle(token_hash: str) -> str:
    """A public name for one session row.  Derived, so the page never carries
    the stored hash, and stable, so a sign-out button names the row it shows."""
    return hashlib.sha256(("session:" + token_hash).encode()).hexdigest()[:24]


def list_sessions(settings: Settings, user_id: str, current_token: str | None = None) -> list[dict]:
    """This account's live sessions, newest first; ``current`` marks the one
    making the request so the page never offers it as "some other device"."""
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    with connect(settings) as connection:
        rows = connection.execute(
            """SELECT s.token_hash, s.created_at, s.expires_at, s.user_agent, s.token_id,
                      k.label AS token_label, k.kind AS token_kind
                 FROM sessions s LEFT JOIN access_tokens k ON k.id = s.token_id
                WHERE s.user_id = ? AND s.expires_at > ?
                ORDER BY s.created_at DESC""",
            (user_id, datetime.now(UTC).isoformat()),
        ).fetchall()
    return [
        {
            "id": session_handle(row["token_hash"]),
            "current": bool(current_hash) and hmac.compare_digest(row["token_hash"], current_hash),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "user_agent": row["user_agent"] or "",
            "token_label": row["token_label"] or "",
            "token_kind": row["token_kind"] or "",
        }
        for row in rows
    ]


def revoke_session_by_handle(settings: Settings, user_id: str, handle: str, current_token: str | None) -> bool:
    """End one of this account's sessions.  Never the caller's own: that is
    what the ordinary sign-out button is for, and a stale page must not be
    able to sign a person out of the tab they are using."""
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    with connect(settings) as connection:
        for row in connection.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (user_id,)).fetchall():
            if row["token_hash"] != current_hash and hmac.compare_digest(session_handle(row["token_hash"]), handle):
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (row["token_hash"],))
                return True
    return False


def revoke_other_sessions(settings: Settings, user_id: str, current_token: str | None) -> int:
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    with connect(settings) as connection:
        return connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (user_id, current_hash)
        ).rowcount


def csrf_matches(expected: str, submitted: str | None) -> bool:
    return bool(submitted) and hmac.compare_digest(expected, submitted)


# --- access tokens ---------------------------------------------------------

#: What a bearer credential is allowed to reach.  ``agent`` acts as the owner
#: over the whole application, ``api`` is the same caller confined to ``/api/``,
#: and ``guest`` is a read-only visitor holding a link.
TOKEN_KINDS = ("agent", "api", "guest")

#: Printed in front of every secret.  It costs four characters and buys two
#: things: a person who finds one in a log knows what it opens, and a secret
#: scanner has something to match on.
TOKEN_PREFIXES = {"agent": "anamna_agent_", "api": "anamna_api_", "guest": "anamna_guest_"}

#: The stored label of the row ensure_seeded_token keeps alive.  The page shows
#: a translated name for it (``token.seeded_name``), flagged by ``seeded``.
SEEDED_TOKEN_LABEL = "ANAMNA_AGENT_TOKEN"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def create_access_token(
    settings: Settings,
    owner_user_id: str,
    kind: str,
    label: str,
    expires_at: str | None = None,
    created_by_user_id: str | None = None,
    secret: str | None = None,
) -> tuple[str, str]:
    """Mint one credential and return ``(id, plaintext)``.

    The plaintext is returned exactly once and never stored, so a lost token is
    replaced rather than recovered.  ``secret`` exists for the seeded token an
    operator pins through the environment; everything else lets this choose.
    """
    if kind not in TOKEN_KINDS:
        raise ValueError(f"Unknown token kind: {kind}")
    token = secret or (TOKEN_PREFIXES[kind] + secrets.token_urlsafe(32))
    token_id = str(uuid.uuid4())
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO access_tokens(id, owner_user_id, kind, label, token_hash, hint,
                                         created_by_user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                token_id,
                owner_user_id,
                kind,
                label.strip() or kind,
                token_digest(token),
                token[-4:],
                created_by_user_id,
                utc_now(),
                expires_at,
            ),
        )
    return token_id, token


def access_token_user(settings: Settings, token: str | None):
    """The account a bearer credential opens, or None.

    Expiry is checked in SQL beside the lookup rather than after it: a token
    whose window has closed must not be distinguishable from one that never
    existed, and two separate checks are how one of them gets forgotten.
    """
    if not token or not token.strip():
        return None
    with connect(settings) as connection:
        return connection.execute(
            """SELECT u.*, k.id AS token_id, k.kind AS token_kind, k.label AS token_label,
                      k.expires_at AS token_expires_at, k.last_used_at AS token_used_at
               FROM access_tokens k JOIN users u ON u.id = k.owner_user_id
               WHERE k.token_hash = ? AND u.disabled_at IS NULL
                 AND (k.expires_at IS NULL OR k.expires_at > ?)""",
            (token_digest(token), datetime.now(UTC).isoformat()),
        ).fetchone()


def touch_access_token(settings: Settings, token_id: str) -> None:
    """Record that the credential was used, so a stale one can be spotted."""
    with connect(settings) as connection:
        connection.execute(
            "UPDATE access_tokens SET last_used_at = ? WHERE id = ?", (utc_now(), token_id)
        )


def list_access_tokens(settings: Settings, owner_user_id: str | None = None):
    """Every live credential, newest first; one owner's when asked for."""
    clause = "WHERE k.owner_user_id = ?" if owner_user_id else ""
    with connect(settings) as connection:
        return connection.execute(
            f"""SELECT k.*, u.email AS owner_email, u.display_name AS owner_name
                FROM access_tokens k JOIN users u ON u.id = k.owner_user_id
                {clause} ORDER BY k.created_at DESC""",
            (owner_user_id,) if owner_user_id else (),
        ).fetchall()


_OWNER_CLAUSE = " AND owner_user_id = ?"


def revoke_access_token(settings: Settings, token_id: str, owner_user_id: str | None = None) -> bool:
    """Delete a credential and every session it opened.

    Deleted rather than flagged: a revoked row that still answers a lookup is
    one forgotten ``WHERE`` away from being live again, and ``audit_events``
    already keeps the record that it existed.  The sessions go with it through
    the foreign key, so a guest holding an open tab is signed out too.
    """
    clause = _OWNER_CLAUSE if owner_user_id else ""
    values = (token_id, owner_user_id) if owner_user_id else (token_id,)
    with connect(settings) as connection:
        return connection.execute(
            f"DELETE FROM access_tokens WHERE id = ?{clause}", values
        ).rowcount > 0


def update_access_token(
    settings: Settings,
    token_id: str,
    label: str,
    expires_at: str | None,
    owner_user_id: str | None = None,
) -> bool:
    """Rename a credential or move its expiry.  The secret never changes — a
    token that needs a new secret is a new token."""
    clause = _OWNER_CLAUSE if owner_user_id else ""
    values = (label.strip(), expires_at, token_id) + ((owner_user_id,) if owner_user_id else ())
    with connect(settings) as connection:
        return connection.execute(
            f"UPDATE access_tokens SET label = ?, expires_at = ? WHERE id = ?{clause}", values
        ).rowcount > 0


def access_token_row(settings: Settings, token_id: str, owner_user_id: str | None = None):
    """One credential's stored row (never its secret, which is not stored), or
    None; ``owner_user_id`` scopes the lookup the same way the update does."""
    clause = _OWNER_CLAUSE if owner_user_id else ""
    values = (token_id, owner_user_id) if owner_user_id else (token_id,)
    with connect(settings) as connection:
        return connection.execute(
            f"SELECT id, kind, expires_at, pin_hash FROM access_tokens WHERE id = ?{clause}", values
        ).fetchone()


def ensure_seeded_token(settings: Settings, secret: str | None) -> str | None:
    """Keep the operator's pinned agent token present, and return its id.

    An automated caller needs a credential that survives a container being
    recreated, and a value committed to the repository would be a backdoor in
    every clone — so the secret comes from the environment and the database
    only ever holds its hash.  It belongs to the first administrator, which is
    the account that owns the installation (see ``create_user``).
    """
    if not secret or not secret.strip():
        return None
    secret = secret.strip()
    with transaction(settings, immediate=True) as connection:
        row = connection.execute(
            "SELECT id, seeded FROM access_tokens WHERE token_hash = ?", (token_digest(secret),)
        ).fetchone()
        if row is None:
            admin = connection.execute(
                "SELECT id FROM users WHERE role = 'admin' AND disabled_at IS NULL"
                " ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if admin is None:
                return None
            token_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO access_tokens(id, owner_user_id, kind, label, token_hash, hint,
                                             created_by_user_id, created_at, expires_at, seeded)
                   VALUES (?, ?, 'agent', ?, ?, ?, NULL, ?, NULL, 1)""",
                (token_id, admin["id"], SEEDED_TOKEN_LABEL, token_digest(secret), secret[-4:], utc_now()),
            )
        else:
            token_id = row["id"]
            # A row created by hand with the same secret is still the one the
            # server keeps alive from now on, so it carries the flag.
            if not row["seeded"]:
                connection.execute("UPDATE access_tokens SET seeded = 1 WHERE id = ?", (token_id,))
        # The secret changed: the row the previous value created opens nothing
        # the operator still holds, and leaving it would keep a second
        # never-expiring owner credential alive under the same name.  Only
        # seeded rows go; a credential somebody minted is theirs to revoke.
        for old in connection.execute(
            "SELECT id, owner_user_id, hint FROM access_tokens WHERE seeded = 1 AND id <> ?", (token_id,)
        ).fetchall():
            connection.execute(
                """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type,
                                            entity_id, details_json, created_at)
                   VALUES (?, NULL, 'seeded_token_retired', 'access_token', ?, ?, ?)""",
                (old["owner_user_id"], old["id"], json.dumps({"hint": old["hint"], "replaced_by": token_id}), utc_now()),
            )
            connection.execute("DELETE FROM access_tokens WHERE id = ?", (old["id"],))
    return token_id


# --- doctor PINs ------------------------------------------------------------

#: How long a freshly shown code is accepted.  Long enough to read it aloud,
#: walk to the clinic computer and type it; short enough that a code glimpsed
#: over a shoulder is useless by the time anybody tries it elsewhere.
DOCTOR_PIN_REDEEM_WINDOW = timedelta(minutes=15)
#: How long the doctor's read-only session lasts, counted from the moment the
#: code was created rather than from redemption, so the patient is told one
#: fixed end time.
DOCTOR_PIN_ACCESS = timedelta(hours=24)
#: Failed codes tolerated per client and across the whole server inside
#: LOGIN_ATTEMPT_WINDOW.  The global cap is the real bound: it limits every
#: code's whole 15-minute life to 60 guesses out of 10^6, wherever they come
#: from.  The per-client one keeps a single fat-fingered clinic from spending it,
#: and is high enough that nine mistyped codes still leave the tenth one to try.
DOCTOR_PIN_CLIENT_LIMIT = 10
DOCTOR_PIN_GLOBAL_LIMIT = 60
DOCTOR_PIN_GLOBAL_KEY = "doctor-pin:*"
#: Stored label of a PIN-opened guest row; the page shows ``doctor.token_name``.
DOCTOR_PIN_LABEL = "Doctor PIN"


def doctor_pin_digest(settings: Settings, pin: str) -> str:
    return hmac.new(settings.secret_key.encode(), pin.encode(), hashlib.sha256).hexdigest()


def create_doctor_pin(settings: Settings, owner_user_id: str) -> tuple[str, str, datetime, datetime]:
    """Mint a guest row reachable by a six-digit code.

    Returns ``(token_id, pin, redeem_by, expires_at)``.  The code is drawn
    again while it matches another code that is still redeemable, so two
    patients in one waiting room can never be handed the same digits.
    """
    now = datetime.now(UTC)
    redeem_by = now + DOCTOR_PIN_REDEEM_WINDOW
    expires_at = now + DOCTOR_PIN_ACCESS
    token_id = str(uuid.uuid4())
    with transaction(settings, immediate=True) as connection:
        while True:
            pin = f"{secrets.randbelow(10**6):06d}"
            digest = doctor_pin_digest(settings, pin)
            if connection.execute(
                """SELECT 1 FROM access_tokens WHERE pin_hash = ?
                     AND pin_redeemed_at IS NULL AND pin_redeem_by > ?""",
                (digest, now.isoformat()),
            ).fetchone() is None:
                break
        connection.execute(
            """INSERT INTO access_tokens(id, owner_user_id, kind, label, token_hash, hint,
                                         created_by_user_id, created_at, expires_at,
                                         pin_hash, pin_redeem_by)
               VALUES (?, ?, 'guest', ?, ?, '', ?, ?, ?, ?, ?)""",
            (
                token_id, owner_user_id, DOCTOR_PIN_LABEL,
                # A secret nobody is shown: the row needs a unique hash, and
                # the code is the only door to it.
                token_digest(secrets.token_urlsafe(32)),
                owner_user_id,
                now.isoformat(timespec="seconds"),
                expires_at.isoformat(timespec="seconds"),
                digest,
                redeem_by.isoformat(timespec="seconds"),
            ),
        )
    return token_id, pin, redeem_by, expires_at


def redeem_doctor_pin(settings: Settings, pin: str):
    """Spend a code and return its guest row, or None.

    One ``UPDATE … RETURNING``, so two people typing the same code at the same
    instant cannot both get in.  Wrong, expired, already used and malformed
    all answer None: the caller must not be able to tell them apart.
    """
    pin = "".join(ch for ch in pin if not ch.isspace() and ch != "-")
    if len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        return None
    now = datetime.now(UTC).isoformat()
    with connect(settings) as connection:
        rows = connection.execute(
            """UPDATE access_tokens SET pin_redeemed_at = ?, last_used_at = ?
                WHERE pin_hash = ? AND pin_redeemed_at IS NULL AND pin_redeem_by > ?
                  AND expires_at > ?
                  AND owner_user_id IN (SELECT id FROM users WHERE disabled_at IS NULL)
            RETURNING id AS token_id, owner_user_id AS id, expires_at AS token_expires_at""",
            (now, utc_now(), doctor_pin_digest(settings, pin), now, now),
        ).fetchall()  # drained, not fetchone(): RETURNING writes only once stepped to the end
    return rows[0] if rows else None


def list_doctor_pins(settings: Settings, owner_user_id: str):
    """This owner's PIN accesses that can still do something: a code still
    waiting to be typed, or a session the code already opened."""
    now = datetime.now(UTC).isoformat()
    with connect(settings) as connection:
        return connection.execute(
            """SELECT id, created_at, expires_at, pin_redeem_by, pin_redeemed_at
                 FROM access_tokens
                WHERE owner_user_id = ? AND pin_hash IS NOT NULL AND expires_at > ?
                  AND (pin_redeemed_at IS NOT NULL OR pin_redeem_by > ?)
                ORDER BY created_at DESC""",
            (owner_user_id, now, now),
        ).fetchall()


def open_registration(settings: Settings) -> bool:
    """Whether a stranger may create an account without being invited.

    Closed unless an administrator opens it.  A server reachable from the
    internet with a sign-up form on it collects accounts whether or not anyone
    meant it to, and the person who wants one is off by a single toggle.

    An empty database is not an exception any more.  Letting its first
    visitor in made whoever found a fresh, internet-reachable install first
    its administrator; that account is now created on the first-run page,
    behind a one-time setup code (see ``has_users`` and ``setup_code_matches``),
    or with ``anamna init`` on the server itself.
    """
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'open_registration'"
        ).fetchone()
    return bool(row) and row["value"] == "1"


def has_users(settings: Settings) -> bool:
    """False only on a database nobody has set up yet: the first-run state."""
    with connect(settings) as connection:
        return connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


#: Failed setup codes tolerated from all addresses together per window.  Behind
#: a proxy every visitor can share one address, and an operator-chosen code may
#: be short, so the per-address meter alone would not bound the guessing.
SETUP_CODE_GLOBAL_LIMIT = 30
SETUP_CODE_GLOBAL_KEY = "setup-code:*"


def new_setup_code() -> str:
    """64 random bits in four groups, short enough to type from a log."""
    return "-".join(secrets.token_hex(2) for _ in range(4))


def setup_code_matches(expected: str, given: str) -> bool:
    """Constant-time, so the comparison does not reveal how much was right."""
    return bool(expected) and hmac.compare_digest(
        expected.encode("utf-8"), given.strip().encode("utf-8")
    )


def set_open_registration(settings: Settings, enabled: bool) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO app_settings(key, value, updated_at) VALUES ('open_registration', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            ("1" if enabled else "0", utc_now()),
        )


# ponytail: in-process counter, so it resets on restart and is per-worker.
# Move the table into SQLite if this ever runs behind more than one worker.
_attempts: dict[str, list[datetime]] = {}
#: The limit each key was last checked against, so `retry_minutes` and
#: `blocked` know when a key stops being blocked.
_limits: dict[str, int] = {}
#: Keys without a live stamp are dropped from `_limits` once it grows past this.
_LIMITS_FLOOR = 4096


def _live_stamps(client: str) -> list[datetime]:
    """The stamps of this key still inside the window, oldest first; prunes the rest."""
    cutoff = datetime.now(UTC) - LOGIN_ATTEMPT_WINDOW
    recent = sorted(stamp for stamp in _attempts.get(client, ()) if stamp > cutoff)
    if recent:
        _attempts[client] = recent
    else:
        _attempts.pop(client, None)
    return recent


def throttled(client: str, limit: int = LOGIN_ATTEMPT_LIMIT) -> bool:
    """True when this address has knocked too often to be answered yet.

    Guards the two endpoints that run scrypt for an unauthenticated caller,
    sign-in and sign-up.  Each attempt is deliberately expensive for the server
    as well as the attacker, so leaving them unmetered makes the form both a
    credential-stuffing target and a way to saturate the box from a handful of
    connections.
    """
    _limits[client] = limit
    if len(_limits) > _LIMITS_FLOOR:
        for key in [key for key in _limits if key != client and key not in _attempts]:
            del _limits[key]
    return len(_live_stamps(client)) >= limit


def retry_minutes(client: str) -> int:
    """Whole minutes until this key stops being blocked, rounded up; 0 when it is free.

    A key is blocked while it holds at least `limit` stamps inside the window,
    so it frees itself when the stamp `limit` places from the newest one leaves.
    """
    recent = _live_stamps(client)
    limit = _limits.get(client, LOGIN_ATTEMPT_LIMIT)
    if len(recent) < limit:
        return 0
    free_at = recent[len(recent) - limit] + LOGIN_ATTEMPT_WINDOW
    seconds = (free_at - datetime.now(UTC)).total_seconds()
    return max(1, math.ceil(seconds / 60))


def blocked() -> list[dict]:
    """Every key that is paused right now, with the minutes until it frees itself."""
    paused = []
    for key in sorted(_attempts):
        minutes = retry_minutes(key)
        if minutes:
            paused.append({"key": key, "minutes": minutes})
    return paused


def record_attempt(client: str) -> None:
    """Count one attempt against this address.

    Sign-in records only failures — a person with the right password should
    never be locked out of their own record.  Sign-up records every submission
    that passes form validation, successful or not, because an address creating
    ten accounts in the window is the abuse case rather than the honest one.
    """
    _attempts.setdefault(client, []).append(datetime.now(UTC))
    if len(_attempts) > 4096:  # a floor under memory growth from spoofed addresses
        cutoff = datetime.now(UTC) - LOGIN_ATTEMPT_WINDOW
        for key, stamps in _attempts.copy().items():
            if not any(stamp > cutoff for stamp in stamps):
                del _attempts[key]
                _limits.pop(key, None)


def clear_attempts(client: str) -> None:
    _attempts.pop(client, None)
    _limits.pop(client, None)


def clear_attempts_matching(prefix: str) -> int:
    """Clear every key that starts with ``prefix``; returns how many were cleared."""
    keys = {key for key in (*_attempts, *_limits) if key.startswith(prefix)}
    for key in keys:
        _attempts.pop(key, None)
        _limits.pop(key, None)
    return len(keys)


#: Set on every successful sign-in.  It proves that this browser has signed in
#: to this account before, so the browser's failed guesses are counted on a
#: meter of their own: a stranger who knows the address cannot lock the owner
#: out of the browser the owner actually uses.  It names a browser, not a session.
DEVICE_COOKIE = "anamna_device"
_DEVICE_NONCE = re.compile(r"[A-Za-z0-9_-]{10,64}")


def _device_mac(settings: Settings, email: str, nonce: str) -> str:
    message = f"device:{email.strip().casefold()}:{nonce}".encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def device_cookie_value(settings: Settings, email: str) -> str:
    """A new device token for this account: a random nonce and its MAC."""
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_device_mac(settings, email, nonce)}"


def device_cookie_nonce(settings: Settings, email: str, value: str | None) -> str | None:
    """The nonce of a device cookie this account minted, or None for anything else."""
    nonce, separator, mac = (value or "").partition(".")
    if not separator or not _DEVICE_NONCE.fullmatch(nonce):
        return None
    expected = _device_mac(settings, email, nonce)
    if not hmac.compare_digest(expected.encode("ascii"), mac.encode("utf-8")):
        return None
    return nonce
