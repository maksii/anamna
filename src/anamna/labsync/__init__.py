"""Lab connections: sync results from laboratory customer portals.

Providers (each a module with a ``Client``): :mod:`.eskulab` (esculab.com)
and :mod:`.synevo` (synevo.ua), whose customer websites run on unofficial,
undocumented APIs — the person supplies the credential their own signed-in
browser holds — and :mod:`.ekspert` (Expert Hospital), which has only a mobile
app: the person signs in once with phone and password (``SIGN_IN =
"password"``), and only the tokens the lab returns are stored — and the
clinics on :mod:`.doctoreleks` (St. Paraskeva, Veselka), signed in with phone
and a texted code (``SIGN_IN = "sms"``).  Each person
chooses which people on that lab account feed which record.

Two things come out of it, and neither ever marks anything verified:

1. **Import.**  A finished order's official PDF goes through the intake
   queue exactly like a manual upload, and is read by the same parser.  An
   order already in the record is *linked* — by the order number printed on
   it, or, for old reports that print none, by date and matching values —
   never imported twice.  A finished order the lab issued no PDF for is
   filed as the lab's own record of it (:data:`LAB_RECORD`), until a report
   takes its place.
2. **Cross-check.**  The lab's structured rows are a second, independent
   reading of the same results.  Each parsed value is compared with its row;
   the person sees which agree and may then — by pressing a button — mark
   exactly those as verified (docs/extraction-and-verification.md: automated
   gates are read-only).

Two layers of consent, as for Paperless: the operator enables each provider in
``app_settings`` (/admin/lab-connections); each person stores their own
credential.  With a provider off, nothing here renders or runs.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..config import Settings, log_run, per_request, resolve_source_path
from ..db import connect, transaction, utc_now
from ..health import applicable_band, applicable_reference_bounds
from ..ingest import intake
from ..ingest.classifier import joined_title
from ..ingest.extract import file_sha256
from ..ingest.parsers import (
    ParsedObservation,
    ReferenceLimits,
    method_note,
    reference_bounds,
    reference_limits,
    without_specimen_label,
)
from ..ingest.text import collapse_space
from ..derived import refresh_derived_observations
from ..ingest.pipeline import (
    NOT_DUPLICATE_NOTE,
    PARSER_VERSION,
    DuplicateRefused,
    ensure_vendor,
    index_search,
    insert_observation,
    interpretation,
    lab_order_collected_at,
    mark_document_duplicate,
    open_review_task,
    reason_part,
    resolve_parsed_concept,
    stored_unit,
)
from ..ingest.positions import store_positions
from ..reference import canonical_unit, convert_value
from . import doctoreleks, ekspert, eskulab, synevo
from .common import (
    LabSyncError,
    comparator,
    loose_name_key,
    name_key,
    word_key,
    parse_result,
    url_is_acceptable,
)

logger = logging.getLogger("anamna.labsync")

PROVIDERS = {eskulab.KEY: eskulab, synevo.KEY: synevo, ekspert.KEY: ekspert, **doctoreleks.CLINICS}

#: Pause between orders: an unofficial API is not somewhere to be in a hurry.
ORDER_DELAY_SECONDS = 1.0
#: How long the web sync waits for the intake worker to read one PDF.
JOB_WAIT_SECONDS = 900
#: A sync marked running longer than this is a dead thread, not a busy one.
STALE_RUN = timedelta(minutes=30)

#: Result types that are not one number or one word: section headings,
#: microbiology (JSON with comments), coprogram arrays, cytology text and
#: method notes.  Shown for information and never counted as a mismatch.
#: «file»: EskuLab's result is an attachment (a coprogram, a food-allergen
#: panel as its own PDF), so the row names a file, not a value.
INFO_RESULT_TYPES = frozenset({"none", "json", "flora", "cytology", "info", "file"})
#: A lab's free-text remark on the panel («Примітки (зак)»), not a measurement;
#: nor is the signature of whoever read a smear («Виконавець цитологічного
#: аналізу»), nor a smear's sampling-site heading («ТОЧКА 2» / «VAGINA»).
_NOTE_ROW_RE = re.compile(r"^\s*(примітк|коментар|comment|note|виконавець|точка\s*\d+\s*$)", re.I)
#: «ТОЧКА 2» / «VAGINA»: the site every following smear row was taken from.
_SITE_ROW_RE = re.compile(r"^\s*точка\s*\d+\s*$", re.I)
#: The smear's closing grade, printed as a conclusion: «Висновок» / «Ступінь
#: чистоти III».  The analyte is the purity grade; a bare «Висновок» would
#: merge with every other report's conclusion.
_GRADE_RESULT_RE = re.compile(r"^(?P<name>Ступінь\s+чистоти)\s+(?P<grade>[IVXІХ]+|\d)$", re.I)
CLASSES = ("match", "value_mismatch", "unit_mismatch", "name_mismatch", "missing", "extra", "info")

ERROR_OFF = "labsync.error_off"
ERROR_AUTH = "labsync.error_auth"
ERROR_EXPIRED = "labsync.error_expired"
ERROR_NO_CREDENTIALS = "labsync.error_no_credentials"
ERROR_PATIENT_UNKNOWN = "labsync.error_patient_unknown"
ERROR_RUNNING = "labsync.error_running"
ERROR_INGEST = "labsync.error_ingest"
ERROR_NO_PROFILE = "labsync.error_no_profile"
ERROR_LINK_TARGET = "labsync.error_link_target"

ERROR_KEYS = frozenset(
    {
        ERROR_OFF,
        "labsync.error_credentials",
        ERROR_AUTH,
        ERROR_EXPIRED,
        "labsync.error_unreachable",
        "labsync.error_reply",
        ERROR_NO_CREDENTIALS,
        "labsync.error_no_patient",
        ERROR_PATIENT_UNKNOWN,
        "labsync.error_confirm",
        ERROR_RUNNING,
        "labsync.error_pdf",
        ERROR_INGEST,
        "labsync.error_url",
        ERROR_NO_PROFILE,
        "labsync.unavailable_offline",
        "labsync.unavailable_nofile",
        "labsync.unavailable_esoz",
        "labsync.partial_imported",
        "labsync.partial_no_pdf",
        "labsync.ekspert_error_forbidden",
        "labsync.password_error_phone",
        "labsync.password_error_invalid",
        "labsync.password_error_code",
        "labsync.password_error_code_expired",
        "labsync.password_error_throttled",
        "labsync.sms_error_phone",
        "labsync.sms_error_person",
        "labsync.doctoreleks_error_unmapped",
    }
)


def signs_in(key_or_module) -> bool:
    """A lab reached only through its mobile app: the person signs in here
    (phone and password, or phone and a texted code) and tokens are kept."""
    module = PROVIDERS.get(key_or_module) if isinstance(key_or_module, str) else key_or_module
    return getattr(module, "SIGN_IN", "") in ("password", "sms")


def provider(key: str):
    if key not in PROVIDERS:
        raise LabSyncError(ERROR_OFF)
    return PROVIDERS[key]


# --- configuration -----------------------------------------------------------


@per_request
def _stored_settings(settings: Settings) -> dict[str, str]:
    """Every provider's switch and address in one read (PERF-13: a page used
    to open a connection per provider per question)."""
    with connect(settings) as connection:
        return dict(connection.execute("SELECT key, value FROM app_settings WHERE key LIKE 'labsync\\_%' ESCAPE '\\'"))


def _config(stored: dict[str, str], key: str) -> dict[str, str]:
    return {
        # Off until an administrator turns it on: it talks to a private API.
        "enabled": stored.get(f"labsync_{key}_enabled", "0"),
        "url": (stored.get(f"labsync_{key}_url") or provider(key).DEFAULT_URL).strip().rstrip("/"),
    }


def provider_settings(settings: Settings, key: str) -> dict[str, str]:
    provider(key)
    return _config(_stored_settings(settings), key)


def _is_active(config: dict[str, str]) -> bool:
    return config["enabled"] == "1" and url_is_acceptable(config["url"])


def active(settings: Settings, key: str) -> bool:
    return _is_active(provider_settings(settings, key))


def active_providers(settings: Settings) -> list[str]:
    stored = _stored_settings(settings)
    return [key for key in PROVIDERS if _is_active(_config(stored, key))]


def save_provider_settings(settings: Settings, key: str, *, enabled: bool, url: str) -> int:
    """Store the switch and address; returns how many stored credentials were
    forgotten.  Changing the address forgets every credential for it: each
    was given for the lab's own site, and must never be replayed elsewhere."""
    module = provider(key)
    url = (url or module.DEFAULT_URL).strip().rstrip("/")
    if not url_is_acceptable(url):
        raise LabSyncError("labsync.error_url")
    previous = provider_settings(settings, key)["url"]
    forgotten = 0
    with transaction(settings) as connection:
        if url != previous:
            forgotten = connection.execute(
                """UPDATE lab_accounts SET secret='', refresh_secret='', phone='', secret_expires_at=NULL,
                       updated_at=? WHERE provider=? AND (secret<>'' OR refresh_secret<>'')""",
                (utc_now(), key),
            ).rowcount
        for name, value in ((f"labsync_{key}_enabled", "1" if enabled else "0"), (f"labsync_{key}_url", url)):
            connection.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (name, value, utc_now()),
            )
    return forgotten


def instance_counts(settings: Settings, key: str) -> dict[str, int]:
    with connect(settings) as connection:
        accounts = connection.execute(
            "SELECT COUNT(*) FROM lab_accounts WHERE provider=? AND secret<>''", (key,)
        ).fetchone()[0]
        states = dict(connection.execute(
            "SELECT state, COUNT(*) FROM lab_orders WHERE provider=? GROUP BY state", (key,)
        ).fetchall())
    return {"accounts": int(accounts), "orders": sum(states.values()),
            **{state: int(states.get(state, 0)) for state in ("imported", "linked", "pending", "unavailable", "failed")}}


# --- accounts ----------------------------------------------------------------------


def account(settings: Settings, user_id: str, key: str):
    with connect(settings) as connection:
        return connection.execute(
            "SELECT * FROM lab_accounts WHERE user_id=? AND provider=?", (user_id, key)
        ).fetchone()


def save_credentials(settings: Settings, user_id: str, key: str, form: dict[str, str]) -> str:
    """Store what connects this person; returns the message key to show.  A
    password provider signs in here and may first ask for a texted code."""
    module = provider(key)
    if signs_in(module):
        return _sign_in(settings, user_id, key, form)
    _store_credentials(settings, user_id, key, module.parse_credentials(form))
    return "labsync.saved_credentials"


def _store_credentials(settings: Settings, user_id: str, key: str, parsed: dict) -> None:
    with transaction(settings) as connection:
        connection.execute(
            """INSERT INTO lab_accounts(user_id, provider, secret, refresh_secret, phone, secret_expires_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET secret=excluded.secret,
                   refresh_secret=excluded.refresh_secret, phone=excluded.phone,
                   secret_expires_at=excluded.secret_expires_at, updated_at=excluded.updated_at""",
            (user_id, key, parsed["secret"], parsed.get("refresh_secret") or "", parsed["phone"],
             parsed["expires_at"], utc_now()),
        )


# --- signing in with phone and password (a lab with only a mobile app) -------------
#
# The password goes to the lab's sign-in endpoint once and is never stored.
# When the lab texts a code first, the challenge waits here for the code.
# ponytail: in-process and per worker; a restart drops a pending code and the
# person signs in again.  Move it to a table if this ever runs multi-process.
_PENDING: dict[tuple[str, str], dict] = {}
_PENDING_LOCK = threading.Lock()
SAVED_CODE_SENT = "labsync.password_code_sent"
SAVED_CHOOSE = "labsync.sms_choose_person"


def _device_state(row) -> dict:
    """This connection's device id and trusted-device token, kept across
    reconnects (``forget`` keeps them) so the lab knows the device and need
    not text a code every time."""
    try:
        state = json.loads(row["refresh_secret"]) if row and row["refresh_secret"] else {}
    except (json.JSONDecodeError, TypeError):
        state = {}
    state = state if isinstance(state, dict) else {}
    if not re.fullmatch(r"[0-9a-f-]{36}", str(state.get("device_id") or "")):
        state["device_id"] = str(uuid.uuid4())
    return {"device_id": state["device_id"], "trusted": state.get("trusted") or None}


def _live_pending(user_id: str, key: str) -> dict | None:
    """The waiting sign-in step, dropped when its time is up."""
    with _PENDING_LOCK:
        entry = _PENDING.get((user_id, key))
        if entry and entry["until"] < time.monotonic():
            _PENDING.pop((user_id, key), None)
            entry = None
    return entry


def pending_code(user_id: str, key: str) -> dict | None:
    """The texted-code step waiting for this person, if any (masked phone and
    code length only)."""
    entry = _live_pending(user_id, key)
    if not entry:
        return None
    users = entry["challenge"].get("users")
    return {"phone_masked": entry["challenge"]["phone_masked"],
            "code_length": entry["challenge"]["code_length"], **({"users": users} if users else {})}


def _verify_pending(module, url: str, user_id: str, key: str, form: dict[str, str], chosen: str) -> dict:
    """The texted-code step.  A reply that is still a challenge (the phone
    opens several accounts) is stored for the person to choose from."""
    entry = _live_pending(user_id, key)
    if not entry:
        raise LabSyncError("labsync.password_error_code_expired")
    challenge, code = entry["challenge"], form.get("code")
    if challenge.get("users"):
        # The phone opened several accounts: the person picked one of them.
        if chosen not in {user["id"] for user in challenge["users"]}:
            raise LabSyncError("labsync.sms_error_person")
        challenge, code = {**challenge, "patient": chosen}, challenge["code"]
    parsed = module.verify_code(url, challenge, code, entry["state"], entry["phone"])
    if "challenge" in parsed:
        with _PENDING_LOCK:
            _PENDING[(user_id, key)] = {**entry, "challenge": parsed["challenge"]}
    return parsed


def _sign_in(settings: Settings, user_id: str, key: str, form: dict[str, str]) -> str:
    if not active(settings, key):
        raise LabSyncError(ERROR_OFF)
    module, url = provider(key), provider_settings(settings, key)["url"]
    chosen = str(form.get("patient") or "").strip()
    if str(form.get("code") or "").strip() or chosen:
        parsed = _verify_pending(module, url, user_id, key, form, chosen)
        if "challenge" in parsed:
            return SAVED_CHOOSE
    else:
        state = _device_state(account(settings, user_id, key))
        parsed = module.start_sign_in(url, form.get("phone"), form.get("password"), state)
        if "challenge" in parsed:
            lifetime = max(60, min(int(parsed["challenge"]["expires_in"]), 900))
            with _PENDING_LOCK:
                _PENDING[(user_id, key)] = {"challenge": parsed["challenge"], "state": state,
                                            "phone": parsed["phone"], "until": time.monotonic() + lifetime}
            return SAVED_CODE_SENT
    with _PENDING_LOCK:
        _PENDING.pop((user_id, key), None)
    _store_credentials(settings, user_id, key, parsed)
    return "labsync.saved_credentials"


def forget(settings: Settings, user_id: str, key: str) -> None:
    """Drop the credential and the lab's person list.  The chosen person and
    the order history stay, so reconnecting later never re-imports.  For a
    password lab only the device identity stays (no token): the next sign-in
    from here is the same device to the lab."""
    with _PENDING_LOCK:
        _PENDING.pop((user_id, key), None)
    row = account(settings, user_id, key)
    device = (json.dumps(_device_state(row)) if row and row["refresh_secret"] and signs_in(provider(key)) else "")
    with transaction(settings) as connection:
        connection.execute(
            """UPDATE lab_accounts SET secret='', refresh_secret=?, phone='', secret_expires_at=NULL,
                   persons_json=NULL, checked_at=NULL, updated_at=? WHERE user_id=? AND provider=?""",
            (device, utc_now(), user_id, key),
        )


def _expired(expires_at: str | None) -> bool:
    return bool(expires_at) and str(expires_at)[:19] <= datetime.now(UTC).isoformat(timespec="seconds")[:19]


def _client(settings: Settings, key: str, secret: str, phone: str, refresh: str | None = None):
    module = provider(key)
    url = provider_settings(settings, key)["url"]
    if not signs_in(module):
        return module.Client(url, secret, phone)
    if refresh is None:
        # The access token identifies its account row: callers that hold only
        # the token still get the refresh token that renews it.
        with connect(settings) as connection:
            found = connection.execute(
                "SELECT refresh_secret FROM lab_accounts WHERE provider=? AND secret=? AND secret<>''", (key, secret)
            ).fetchone()
        refresh = found[0] if found else ""
    return module.Client(url, secret, phone, refresh)


def _store_rolled_secret(settings: Settings, user_id: str, key: str, old: str, client) -> None:
    """Keep the newest credential the server issued: Synevo's session cookie
    rolls; a mobile app's access token is renewed with its refresh token,
    which the lab may rotate at the same time."""
    if client.secret and client.secret != old:
        refresh = getattr(client, "refresh_secret", None)
        with transaction(settings) as connection:
            connection.execute(
                """UPDATE lab_accounts SET secret=?, refresh_secret=COALESCE(?, refresh_secret), updated_at=?
                    WHERE user_id=? AND provider=? AND secret=?""",
                (client.secret, refresh, utc_now(), user_id, key, old),
            )


def _patient(connection, user_id: str):
    return connection.execute(
        "SELECT * FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (user_id,)
    ).fetchone()


def demographics(remote: dict, patient) -> dict[str, object]:
    """Whether a lab person is plausibly this record's person.  ``ok`` only
    when date of birth *and* sex are known on both sides and agree; anything
    else needs the person's explicit confirmation."""
    ours_dob = str(patient["date_of_birth"] or "") if patient else ""
    ours_sex = str(patient["sex_at_birth"] or "") if patient else ""
    ours_sex = ours_sex if ours_sex in {"male", "female"} else ""
    birthday = None if not (ours_dob and remote.get("birthday")) else ours_dob == remote["birthday"]
    sex = None if not (ours_sex and remote.get("sex")) else ours_sex == remote["sex"]
    return {"birthday": birthday, "sex": sex, "ok": birthday is True and sex is True}


def check_account(settings: Settings, user_id: str, key: str) -> list[dict]:
    """Call the lab with the stored credential and keep its person list."""
    if not active(settings, key):
        raise LabSyncError(ERROR_OFF)
    row = account(settings, user_id, key)
    if not row or not row["secret"]:
        raise LabSyncError(ERROR_NO_CREDENTIALS)
    if _expired(row["secret_expires_at"]):
        raise LabSyncError(ERROR_EXPIRED)
    client = _client(settings, key, row["secret"], row["phone"], row["refresh_secret"])
    try:
        people, expires = client.check()
    finally:
        _store_rolled_secret(settings, user_id, key, row["secret"], client)
    with transaction(settings) as connection:
        connection.execute(
            """UPDATE lab_accounts SET persons_json=?, checked_at=?, secret_expires_at=COALESCE(?, secret_expires_at),
                   updated_at=? WHERE user_id=? AND provider=?""",
            (json.dumps(people, ensure_ascii=False), utc_now(), expires, utc_now(), user_id, key),
        )
        # A person the account no longer lists, who never brought an order,
        # is a stale choice -- a sign-in under the wrong identity listed a
        # blank person -- and would otherwise keep the record it was linked to
        # from the real one.  Links with order history stay: they are what
        # keeps a reconnect from re-importing.
        listed = [str(person["id"]) for person in people]
        connection.execute(
            f"""DELETE FROM lab_person_links WHERE account_user_id=? AND provider=?
                   AND remote_person_id NOT IN ({",".join("?" * len(listed)) or "''"})
                   AND NOT EXISTS (SELECT 1 FROM lab_orders o WHERE COALESCE(o.account_user_id, o.owner_user_id)=lab_person_links.account_user_id
                                   AND o.provider=lab_person_links.provider
                                   AND o.remote_person_id=lab_person_links.remote_person_id)""",
            (user_id, key, *listed),
        )
    return people


# --- whose record each lab person feeds ---------------------------------------------
#
# One lab account usually lists a whole family.  Each person on it is linked
# to the account holder (imported straight away) or to another Anamna
# user the holder shares records with in either direction (fetched, but held
# as "awaiting" until that user accepts).  See migrations/036.

LINK_KEYS = frozenset({
    "labsync.link_saved_self", "labsync.link_saved_other", "labsync.link_saved_running",
    "labsync.link_removed", ERROR_LINK_TARGET, "labsync.inbox_accepted",
    "labsync.inbox_declined", "labsync.inbox_consent_saved",
})
#: Order states the holder's run may still change for a link's target;
#: everything else is the target's own record (or their explicit "no").
_HELD_STATES = ("awaiting", "pending", "accepted", "failed")


def link_candidates(settings: Settings, user_id: str) -> list[dict]:
    """Whose record a lab person can feed: oneself, then everybody who shares
    a record with this user or is shared with by them — the people the app
    already knows as family.  Never a list of every account on the instance."""
    with connect(settings) as connection:
        me = connection.execute("SELECT id, email, display_name FROM users WHERE id=?", (user_id,)).fetchone()
        if me is None:
            return []
        rows = connection.execute(
            """SELECT DISTINCT u.id, u.display_name FROM users u
                WHERE u.disabled_at IS NULL AND u.id<>? AND (
                      u.id IN (SELECT owner_user_id FROM record_shares WHERE grantee_email=?)
                   OR u.email IN (SELECT grantee_email FROM record_shares WHERE owner_user_id=?))
                ORDER BY u.display_name COLLATE NOCASE""",
            (user_id, me["email"], user_id),
        ).fetchall()
        return [
            {"id": str(row["id"]), "name": str(row["display_name"]), "self": str(row["id"]) == user_id,
             "patient": _patient(connection, str(row["id"]))}
            for row in [me, *rows]
        ]


def _people(row) -> list[dict]:
    return json.loads(row["persons_json"]) if row and row["persons_json"] else []


def _link(connection, account_user_id: str, key: str, remote_id: str):
    return connection.execute(
        "SELECT * FROM lab_person_links WHERE account_user_id=? AND provider=? AND remote_person_id=?",
        (account_user_id, key, str(remote_id)),
    ).fetchone()


def has_links(settings: Settings, user_id: str, key: str) -> bool:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT 1 FROM lab_person_links WHERE account_user_id=? AND provider=? AND consent<>'refused' LIMIT 1",
            (user_id, key),
        ).fetchone() is not None


def _drop_held(connection, owner_user_id: str, account_user_id: str, key: str, remote_id: str) -> None:
    """Forget what was fetched for another user and never entered their record."""
    connection.execute(
        f"""DELETE FROM lab_orders WHERE owner_user_id=? AND account_user_id=? AND provider=?
              AND remote_person_id=? AND document_id IS NULL
              AND state IN ({", ".join("?" for _ in _HELD_STATES)})""",
        (owner_user_id, account_user_id, key, str(remote_id), *_HELD_STATES),
    )


def _remote_person(people: list[dict], existing, remote_id: str) -> dict:
    """The lab person being linked: from the live list, else as last stored."""
    chosen = next((person for person in people if person["id"] == str(remote_id)), None)
    if chosen is None and existing is not None:
        chosen = json.loads(existing["remote_person_json"])
    if chosen is None:
        raise LabSyncError(ERROR_PATIENT_UNKNOWN)
    return chosen


def _link_consent(existing, target_id: str, user_id: str) -> str:
    """Your own record needs no consent; an existing decision about the same
    target is kept, anything else is asked again."""
    if target_id == user_id:
        return "owner"
    same = existing is not None and str(existing["target_user_id"]) == target_id
    if same and existing["consent"] in {"asked", "accepted"}:
        return str(existing["consent"])
    return "asked"


def link_person(settings: Settings, user_id: str, key: str, remote_id: str, target: str, confirmed: bool) -> dict:
    """Link one person on the holder's lab account to a record.  ``target`` is
    ``self``, another user's id from :func:`link_candidates`, or empty to
    stop importing that person.  Returns the link (``None`` when removed)."""
    people = _people(account(settings, user_id, key))
    with connect(settings) as connection:
        existing = _link(connection, user_id, key, remote_id)
    chosen = _remote_person(people, existing, remote_id)
    if not target:
        unlink_person(settings, user_id, key, remote_id)
        return {"person": chosen, "target": None}
    target_id = user_id if target == "self" else str(target)
    candidate = next((c for c in link_candidates(settings, user_id) if c["id"] == target_id), None)
    if candidate is None:
        raise LabSyncError(ERROR_LINK_TARGET)
    if candidate["patient"] is None:
        raise LabSyncError(ERROR_NO_PROFILE)
    match = demographics(chosen, candidate["patient"])
    if not match["ok"] and not confirmed:
        raise LabSyncError("labsync.error_confirm")
    # Several lab people may feed one record: a lab keeps a second profile for
    # the same person after a surname change or a second registration.  Orders
    # are keyed per record by their number, so one listed under both arrives
    # once; the date-of-birth and sex check above guards against a stranger.
    with transaction(settings) as connection:
        if (existing is not None and str(existing["target_user_id"]) not in (target_id, user_id)):
            _drop_held(connection, str(existing["target_user_id"]), user_id, key, remote_id)
        consent = _link_consent(existing, target_id, user_id)
        connection.execute(
            """INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json,
                   target_user_id, consent, mismatch_confirmed, created_at, decided_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(account_user_id, provider, remote_person_id) DO UPDATE SET
                   remote_person_json=excluded.remote_person_json, target_user_id=excluded.target_user_id,
                   consent=excluded.consent, mismatch_confirmed=excluded.mismatch_confirmed,
                   decided_at=CASE WHEN lab_person_links.target_user_id=excluded.target_user_id
                                   THEN lab_person_links.decided_at END,
                   updated_at=excluded.updated_at""",
            (user_id, key, str(remote_id), json.dumps(chosen, ensure_ascii=False), target_id, consent,
             0 if match["ok"] else 1, utc_now(), utc_now()),
        )
        return {"person": chosen, "target": target_id, "consent": consent}


def unlink_person(settings: Settings, user_id: str, key: str, remote_id: str) -> None:
    """Stop feeding a record from this lab person.  The holder's own order
    history stays (so linking again never re-imports); what was held for
    another user and never accepted is dropped."""
    with transaction(settings) as connection:
        existing = _link(connection, user_id, key, remote_id)
        if existing is None:
            return
        if str(existing["target_user_id"]) != user_id:
            _drop_held(connection, str(existing["target_user_id"]), user_id, key, remote_id)
        connection.execute(
            "DELETE FROM lab_person_links WHERE account_user_id=? AND provider=? AND remote_person_id=?",
            (user_id, key, str(remote_id)),
        )


# --- the receiving side: results another user's lab account fetched for you -------


def _target_link(connection, target_user_id: str, account_user_id: str, key: str, remote_id: str):
    link = _link(connection, account_user_id, key, remote_id)
    if link is None or str(link["target_user_id"]) != target_user_id or account_user_id == target_user_id:
        raise LabSyncError(ERROR_PATIENT_UNKNOWN)
    return link


def decide_orders(settings: Settings, user_id: str, key: str, account_user_id: str, remote_id: str,
                  order_ids: list[str], accept: bool) -> int:
    """Accept or decline results held for this user.  Accepted ones are
    imported by the holder's next sync (started here); declined ones lose
    their lab rows and are never offered again."""
    with transaction(settings) as connection:
        _target_link(connection, user_id, account_user_id, key, remote_id)
        marks = ", ".join("?" for _ in order_ids) or "NULL"
        changed = connection.execute(
            f"""UPDATE lab_orders SET state=?, error_key=NULL,
                    rows_json=CASE WHEN ? THEN rows_json END, rows_hash=CASE WHEN ? THEN rows_hash END,
                    last_synced_at=?
                 WHERE owner_user_id=? AND account_user_id=? AND provider=? AND remote_person_id=?
                   AND state='awaiting' AND order_id IN ({marks})""",
            ("accepted" if accept else "declined", int(accept), int(accept), utc_now(), user_id,
             account_user_id, key, str(remote_id), *order_ids),
        ).rowcount
    if accept and changed:
        _kick(settings, account_user_id, key)
    return changed


def set_consent(settings: Settings, user_id: str, key: str, account_user_id: str, remote_id: str,
                consent: str) -> None:
    """``accepted``: take this link's results without asking (and accept what
    waits now); ``asked``: ask each time; ``refused``: stop the link — what
    waits is dropped and the holder's runs skip it until they link again."""
    if consent not in {"accepted", "asked", "refused"}:
        raise LabSyncError(ERROR_PATIENT_UNKNOWN)
    with transaction(settings) as connection:
        _target_link(connection, user_id, account_user_id, key, remote_id)
        connection.execute(
            """UPDATE lab_person_links SET consent=?, decided_at=?, updated_at=?
                WHERE account_user_id=? AND provider=? AND remote_person_id=?""",
            (consent, utc_now(), utc_now(), account_user_id, key, str(remote_id)),
        )
        if consent == "refused":
            _drop_held(connection, user_id, account_user_id, key, remote_id)
        elif consent == "accepted":
            connection.execute(
                """UPDATE lab_orders SET state='accepted', last_synced_at=? WHERE owner_user_id=?
                    AND account_user_id=? AND provider=? AND remote_person_id=? AND state='awaiting'""",
                (utc_now(), user_id, account_user_id, key, str(remote_id)),
            )
    if consent == "accepted":
        _kick(settings, account_user_id, key)


def _kick(settings: Settings, account_user_id: str, key: str) -> None:
    """Start the holder's sync so accepted results arrive now.  A run already
    in progress, a provider switched off or an expired credential leaves them
    ``accepted``: the next run imports them, and the inbox says so."""
    try:
        start_sync(settings, account_user_id, key)
    except LabSyncError:
        pass


def inbox(settings: Settings, user) -> list[dict]:
    """Links that feed this user's record from somebody else's lab account,
    with the results waiting for a decision."""
    if not user or user.get("token_kind") in {"guest", "api"}:
        return []
    enabled = set(active_providers(settings))
    with connect(settings) as connection:
        links = connection.execute(
            """SELECT l.*, u.display_name AS holder FROM lab_person_links l JOIN users u ON u.id=l.account_user_id
                WHERE l.target_user_id=? AND l.account_user_id<>? ORDER BY l.created_at""",
            (user["id"], user["id"]),
        ).fetchall()
        entries = []
        for link in links:
            if link["provider"] not in enabled:
                continue
            orders = connection.execute(
                """SELECT * FROM lab_orders WHERE owner_user_id=? AND account_user_id=? AND provider=?
                    AND remote_person_id=? ORDER BY ordered_at IS NOT NULL, ordered_at DESC, order_id DESC""",
                (user["id"], link["account_user_id"], link["provider"], link["remote_person_id"]),
            ).fetchall()
            states: dict[str, int] = {}
            for order in orders:
                states[str(order["state"])] = states.get(str(order["state"]), 0) + 1
            holder_state = connection.execute(
                "SELECT sync_state, sync_detail_key FROM lab_accounts WHERE user_id=? AND provider=?",
                (link["account_user_id"], link["provider"]),
            ).fetchone()
            entries.append({
                "key": link["provider"], "name": provider(link["provider"]).NAME,
                "account_user_id": str(link["account_user_id"]), "holder": str(link["holder"]),
                "person": json.loads(link["remote_person_json"]), "consent": str(link["consent"]),
                "mismatch_confirmed": bool(link["mismatch_confirmed"]),
                "match": demographics(json.loads(link["remote_person_json"]), _patient(connection, user["id"])),
                "states": states,
                "holder_failed": bool(holder_state and holder_state["sync_state"] == "failed"),
                "awaiting": [
                    {"order_id": str(order["order_id"]), "ordered_at": order["ordered_at"],
                     "ready": int(order["ready"]), "total": int(order["total"]),
                     "rows": [row for row in json.loads(order["rows_json"] or "[]")
                              if row.get("result") not in (None, "") and row.get("resulttype") not in INFO_RESULT_TYPES]}
                    for order in orders if order["state"] == "awaiting"
                ],
                "accepted": [str(order["order_id"]) for order in orders if order["state"] == "accepted"],
            })
    return entries


def inbox_count(settings: Settings, user) -> int:
    """How many results wait for this user's decision (a cheap count for a
    notice outside the profile)."""
    if not user or user.get("token_kind") in {"guest", "api"}:
        return 0
    enabled = active_providers(settings)
    if not enabled:
        return 0
    with connect(settings) as connection:
        return int(connection.execute(
            f"""SELECT COUNT(*) FROM lab_orders WHERE owner_user_id=? AND state='awaiting'
                 AND provider IN ({", ".join("?" for _ in enabled)})""",
            (user["id"], *enabled),
        ).fetchone()[0])


# --- the cross-check --------------------------------------------------------------


def _same_number(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-9 * max(1.0, abs(left), abs(right))


def _real_number(value: object) -> bool:
    """A stored order number that is a number, not a captured day of the month."""
    return bool(value) and len(str(value)) > 2


def _documents_by_number(connection, owner_user_id: str, numbers: set[str]) -> dict[str, list[str]]:
    """number → every document carrying it, on the document itself or on one
    of its reports (a compound PDF), oldest first; one query for any number of
    orders.  Duplicates of another document are left out — they hold no
    observations of their own — and so is the lab's own record of an order
    (:data:`LAB_RECORD`): it is the lab's rows, not a reading of them."""
    if not numbers:
        return {}
    marks = ",".join("?" for _ in numbers)
    found: dict[str, list[str]] = {"": []}  # "" keeps every hit in order, oldest first
    for row in connection.execute(
        f"""SELECT d.id, d.order_identifier, r.order_identifier report_order FROM documents d
              LEFT JOIN reports r ON r.document_id=d.id AND r.order_identifier IN ({marks})
             WHERE d.owner_user_id=? AND d.duplicate_of_document_id IS NULL AND d.extraction_strategy<>'lab_api'
               AND (d.order_identifier IN ({marks}) OR r.id IS NOT NULL)
             ORDER BY d.imported_at, d.id""",
        (*numbers, owner_user_id, *numbers),
    ):
        for number in ({str(row["order_identifier"] or ""), str(row["report_order"] or "")} & numbers) | {""}:
            if str(row["id"]) not in found.setdefault(number, []):
                found[number].append(str(row["id"]))
    return found


def _pick(found: dict[str, list[str]], numbers: list[str]) -> list[str]:
    wanted = {str(number) for number in numbers if number}
    hits = {doc for number in wanted for doc in found.get(number, [])}
    return [doc for doc in found.get("", []) if doc in hits]


def _kept_documents(connection, document_ids: list) -> dict[str, str]:
    """document → the document kept in its place: itself, or the one it was
    marked a copy of (an order linked before its document was set aside)."""
    ids = sorted({str(doc) for doc in document_ids if doc})
    if not ids:
        return {}
    return {str(row[0]): str(row[1] or row[0]) for row in connection.execute(
        f"SELECT id, duplicate_of_document_id FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)}


def _duplicate_pairs(connection, document_ids: set[str]) -> list[tuple[str, str]]:
    """(newer, older) for every duplicate relation among these documents that
    nobody called different."""
    ids = sorted(document_ids)
    if len(ids) < 2:
        return []
    marks = ",".join("?" * len(ids))
    return [(str(row[0]), str(row[1])) for row in connection.execute(
        f"""SELECT source_document_id, target_document_id FROM document_relations
             WHERE relationship='duplicate' AND COALESCE(notes, '')<>?
               AND source_document_id IN ({marks}) AND target_document_id IN ({marks})""",
        (NOT_DUPLICATE_NOTE, *ids, *ids))]


def documents_for_order(connection, owner_user_id: str, numbers: list[str]) -> list[str]:
    """Every document carrying one of these order numbers (oldest first)."""
    wanted = {str(number) for number in numbers if number}
    return _pick(_documents_by_number(connection, owner_user_id, wanted), list(wanted))


_OBS_COLUMNS = """o.id, o.document_id, o.page_number, o.raw_name, o.value_numeric, o.value_text, o.comparator,
                  o.unit_raw, o.verification_status, o.vendor_interpretation, o.vendor_interpretation_source,
                  o.vendor_reference_text, o.vendor_reference_low, o.vendor_reference_high, o.concept_id,
                  o.evidence_text, o.specimen, r.order_identifier report_order"""


def _observation_rows(connection, owner_user_id: str, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    marks = ",".join("?" for _ in document_ids)
    return [dict(row) for row in connection.execute(
        f"""SELECT {_OBS_COLUMNS}
              FROM observations o LEFT JOIN reports r ON r.id=o.report_id
             WHERE o.owner_user_id=? AND o.document_id IN ({marks})
               AND o.verification_status <> 'rejected'
               -- Our own calculation (eGFR from creatinine) is not the lab's to
               -- confirm: it would show as "not in the lab's record" on every report.
               AND COALESCE(o.extraction_method, '') NOT LIKE 'derived!_%' ESCAPE '!'
             ORDER BY o.document_id, o.page_number, o.rowid""",
        (owner_user_id, *document_ids),
    )]


def _for_order(rows: list[dict], numbers: list[str], document_ids: list[str]) -> list[dict]:
    """This order's values among ``rows``.  A compound PDF can hold another
    order's report; its values are not this order's to judge.  A one- or
    two-character "number" is a misread day."""
    wanted, documents = {str(number) for number in numbers}, set(document_ids)
    return [row for row in rows if row["document_id"] in documents
            and (not _real_number(row["report_order"]) or str(row["report_order"]) in wanted)]


def _observations(connection, owner_user_id: str, numbers: list[str], document_ids: list[str]) -> list[dict]:
    return _for_order(_observation_rows(connection, owner_user_id, document_ids), numbers, document_ids)


def _obs_view(obs: dict) -> dict:
    return {
        "id": obs["id"],
        "document_id": obs["document_id"],
        "page": obs["page_number"],
        "name": obs["raw_name"],
        "value_numeric": obs["value_numeric"],
        "value_text": obs["value_text"],
        "comparator": obs["comparator"],
        "unit": obs["unit_raw"] or "",
        "status": obs["verification_status"],
        "evidence": (obs.get("evidence_text") or "")[:300],
        "reference": obs.get("vendor_reference_text") or "",
        "interpretation": obs.get("vendor_interpretation"),
        "from_lab": obs.get("vendor_interpretation_source") == "lab_record",
        "concept_id": obs.get("concept_id"),
        "specimen": obs.get("specimen"),
    }


#: Lab spellings of a unit that mean exactly the unit our parser stores.
#: Folded here, for the comparison only: «10^12 клітин/л» is a count of 10^12
#: per litre; «AI (Індекс антитіл)» is "AI" with its own explanation; EskuLab's
#: «індекс позитивності» is the dimensionless index the PDF prints as «індекс».
_LAB_UNIT_WORDS = re.compile(r"\([^()]*\)|клітин")
_LAB_UNIT_FOLDS = {"індекс позитивності": "індекс"}
#: A result that says the result is elsewhere, not what it is: «результат
#: готовий», Synevo's «Ваш результат готовий і знаходиться в додатковому pdf
#: файлі» (the ALEX² panel: 296 values, all in the PDF).
_PLACEHOLDER_RE = re.compile(r"результат\s+готов|додатков\w*\s+pdf", re.I)
#: Our reading of a value that is only an inference from the printed bounds
#: (pipeline.interpretation) — a lab's own flag outranks it.
_DERIVED = (None, "", "within_vendor_range")


def _bounds(text: object) -> tuple[float | None, float | None]:
    """The interval a reference text states, or (None, None) — including for
    a sex- or age-qualified text, which says nothing about this person alone."""
    found = reference_bounds(str(text or "")) if text else (None, None)
    return found[0], found[1]


def _same_bound(left: float | None, right: float | None) -> bool:
    return (left is None) == (right is None) and (left is None or _same_number(float(left), float(right)))


def _lab_reading(row: dict, obs: dict, number: float | None, age: int | None = None, sex: str | None = None) -> str:
    """What a lab's "critical" flag means for this value: below or above which
    edge, read from the report's interval (as stored, or the band of a
    multi-population text that fits this person) and else from the lab's own.
    A flag whose direction no interval shows (a word, a value inside every
    interval) is ``borderline`` — the verdict shows "indeterminate", never
    green."""
    value = number if number is not None else obs.get("value_numeric")
    if value is not None:
        for low, high in ((obs.get("vendor_reference_low"), obs.get("vendor_reference_high")),
                          applicable_reference_bounds(obs.get("vendor_reference_text"), age, sex, float(value)),
                          applicable_reference_bounds(" ".join(row.get("norm") or []), age, sex, float(value))):
            if low is not None and float(value) <= float(low):
                return "low"
            if high is not None and float(value) >= float(high):
                return "high"
    return "borderline"


def _band_limits(text: object, age: int | None, sex: str | None, value: float | None = None) -> ReferenceLimits:
    """The band a reference text states for this person, with whether each
    bound is part of it («5.5 - 7.0» includes 5.5, «< 35» excludes 35)."""
    text = collapse_space(str(text or ""))
    if not text:
        return ReferenceLimits()
    plain = reference_limits(text)
    if plain.low is not None or plain.high is not None:
        return plain
    band = applicable_band(text, age, sex, value)
    if band is not None:
        return reference_limits(band.rsplit(":", 1)[-1])
    low, high = applicable_reference_bounds(text, age, sex, value)
    # A sex clause loses its signs on the way: a strict one anywhere in the
    # text keeps a value on the bound outside, as the stricter reading.
    inclusive = not re.search(r"[<>](?!=)", text)
    return ReferenceLimits(low, high, inclusive, inclusive)


def _holds(value: float, limits: ReferenceLimits) -> bool:
    low, high = limits.low, limits.high
    return ((low is None or value > low or (value == low and limits.low_inclusive))
            and (high is None or value < high or (value == high and limits.high_inclusive)))


def _inside_printed_band(obs: dict, row: dict, age: int | None, sex: str | None) -> bool:
    """The value lies inside the band the report prints for this person, a
    bound the band includes counting as inside; with no band readable on the
    report, inside the lab's own.  The first band found decides."""
    value = obs.get("value_numeric")
    if value is None:
        return False
    stored = ReferenceLimits(obs.get("vendor_reference_low"), obs.get("vendor_reference_high"),
                             obs.get("vendor_reference_low_inclusive") != 0,
                             obs.get("vendor_reference_high_inclusive") != 0)
    for limits in (stored, _band_limits(obs.get("vendor_reference_text"), age, sex, float(value)),
                   _band_limits(" ".join(row.get("norm") or []), age, sex, float(value))):
        if limits.low is not None or limits.high is not None:
            return _holds(float(value), limits)
    return False


def _states_no_interval(obs: dict, row: dict) -> bool:
    """Neither the report nor the lab's record prints anything to judge by:
    «-» or nothing at all.  EskuLab's API marks such a row "critical" (every
    row of some 2022 orders) while the paper prints no flag, and a "critical"
    with no interval to point a direction is no reading of ours to adopt."""
    texts = [str(obs.get("vendor_reference_text") or ""), *(str(line) for line in row.get("norm") or [])]
    return not any(re.sub(r"[\s\-–—]+", "", text) for text in texts)


def _lab_units(unit: str) -> set[str]:
    """Every canonical form the lab's spelling may stand for: as printed, and
    with explanatory words dropped."""
    folded = _LAB_UNIT_FOLDS.get(unit.strip().casefold(), unit)
    return {canonical_unit(unit), canonical_unit(re.sub(r"\s+", "", _LAB_UNIT_WORDS.sub("", folded)))}


def _same_text(left: object, right: object) -> bool:
    """Equal as words, or equal once bracketed glosses are dropped on both
    sides: «позитивний(+) (positive)» is what the PDF prints as «позитивний(+)»."""
    a, b = name_key(left), name_key(right)
    return a == b or (bool(loose_name_key(left)) and loose_name_key(left) == loose_name_key(right))


def _info_text(row: dict) -> str:
    """A descriptive result folded for "is this observation part of it?"."""
    raw = row["result"]
    try:
        raw = json.dumps(json.loads(raw), ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    return name_key(f"{row['test']} {raw}")


def cross_check(rows: list[dict], observations: list[dict], order_id: str = "") -> dict:
    """Compare the lab's rows with the parsed observations.  Pure: no database.

    ``match`` same analyte, value and unit; ``value_mismatch``;
    ``unit_mismatch``; ``name_mismatch`` value and unit agree but the name read
    from the PDF differs (a wrapped label lost its tail, or the only unpaired
    row and value of the order carry the same result under another name, such
    as an English concept name); ``missing`` a lab
    row with no observation (typically a unit the parser's allowlist does not
    know); ``extra`` an observation with no lab row; ``info`` headings,
    microbiology, coprogram, cytology, method notes or no result printed, and
    observations that are part of such a descriptive result — shown, never
    judged.  ``flag`` marks a bound value whose lab normal/critical flag
    disagrees with the range we read from the report: informational only.
    """
    pool = [{**obs, "_key": name_key(obs["raw_name"]), "_loose": loose_name_key(obs["raw_name"]), "_used": False}
            for obs in observations]
    lab_loose = Counter(loose_name_key(row["test"]) for row in rows)
    obs_loose = Counter(obs["_loose"] for obs in pool)
    items = [_check_row(row, pool, lab_loose, obs_loose) for row in rows]

    info_texts = [(item, _info_text(item["lab"])) for item in items
                  if item["cls"] == "info" and item["lab"]["resulttype"] in INFO_RESULT_TYPES]
    for obs in pool:
        if not obs["_used"]:
            _place_unpaired(obs, items, info_texts)
    _pair_lone_row(items, pool)
    for item in items:
        item.pop("_number", None)
        item.pop("_sign", None)
    counts = {cls: sum(1 for item in items if item["cls"] == cls) for cls in CLASSES}
    counts["flag"] = sum(1 for item in items if item["flag"])
    counts["reference_differs"] = sum(1 for item in items if item.get("reference_differs"))
    return {
        "order_id": order_id,
        "computed_at": utc_now(),
        "counts": counts,
        "items": items,
        "by_observation": {item["obs"]["id"]: item["cls"] for item in items if item["obs"]},
    }


def _judge(item: dict, row: dict, obs: dict, number, sign) -> None:
    """Class the pair (value and unit), then note where the lab's flag and
    reference interval disagree with ours."""
    _judge_value(item, row, obs, number, sign)
    _judge_flag(item, row, obs, number)
    _judge_reference(item, row, obs)


def _judge_value(item: dict, row: dict, obs: dict, number, sign) -> None:
    if number is not None:
        # Some reports print no unit for a row (Expert Hospital's liver
        # enzymes): nothing to disagree with, and the lab's own record
        # names it — ``unit_from_lab`` lets the sync adopt it.
        item["unit_from_lab"] = not (obs["unit_raw"] or "").strip() and bool(row["units"].strip())
        item["unit_differs"] = (not item["unit_from_lab"]
                                and canonical_unit(obs["unit_raw"]) not in _lab_units(row["units"]))
        same_value = (obs["value_numeric"] is not None and _same_number(float(obs["value_numeric"]), number)
                      and comparator(obs["comparator"]) == sign)
    else:
        # A word has no unit to agree on: «не виявлені Leu/µL» is the
        # same finding with or without the unit column.
        same_value = _same_text(obs["value_text"], row["result"])
    if not same_value:
        item["cls"] = "value_mismatch"
    else:
        item["cls"] = "unit_mismatch" if item["unit_differs"] else "match"


def _judge_flag(item: dict, row: dict, obs: dict, number) -> None:
    ours, adopted = obs["vendor_interpretation"], obs.get("vendor_interpretation_source") == "lab_record"
    if row["state"] == "critical" and adopted:
        item["flag"] = "lab_flag_adopted"  # the verdict already follows the lab
    elif row["state"] == "critical" and ours in _DERIVED:
        item["flag"] = "lab_out_ours_in"
        item["lab_reading"] = _lab_reading(row, obs, number)
    elif row["state"] == "normal" and ours in {"high", "low", "positive"} and not adopted:
        item["flag"] = "lab_in_ours_out"


def _judge_reference(item: dict, row: dict, obs: dict) -> None:
    # The interval the lab keeps against the one printed on the report:
    # Iron «9–30.4» on the PDF, «Від 11.6 до 31.3» in the lab's record.
    # «Від 0 до 2.59» and «до 2,59» are one interval: a lower bound of 0
    # is no lower bound.
    lab_low, lab_high = _bounds(" ".join(row.get("norm") or []))
    ours_low, ours_high = obs.get("vendor_reference_low"), obs.get("vendor_reference_high")
    lab_low, ours_low = (None if not low else low for low in (lab_low, ours_low))
    item["reference_differs"] = (
        (lab_low is not None or lab_high is not None) and (ours_low is not None or ours_high is not None)
        and not (_same_bound(lab_low, ours_low) and _same_bound(lab_high, ours_high)))


def _find_observation(row: dict, pool: list[dict], lab_loose: Counter, obs_loose: Counter, number) -> dict | None:
    """The first unused observation that reads as this lab row, by name."""
    key, loose = name_key(row["test"]), loose_name_key(row["test"])
    free = [obs for obs in pool if not obs["_used"]]
    candidates = [obs for obs in free if obs["_key"] == key]
    if not candidates and row["units"]:
        glued = name_key(f"{row['test']}, {row['units']}")
        candidates = [obs for obs in free if obs["_key"] == glued]
    if not candidates and lab_loose.get(loose) == 1 and obs_loose.get(loose) == 1:
        candidates = [obs for obs in free if obs["_loose"] == loose]
    if not candidates:
        # The lab names the specimen in front («Аналіз крові: Швидкість осідання
        # еритроцитів (ШОЕ, ESR)»); the PDF reader drops it from the name.
        bare = name_key(without_specimen_label(str(row["test"])))
        if bare != key:
            candidates = [obs for obs in free if obs["_key"] == bare]
    if not candidates and len(key) >= 8:
        # The report names the row by the heading it was printed beneath
        # («Метілентетрагідрофолатредуктаза (MTHFR 677 C>T)», «Вовчаковий
        # антикоагулянт, скринінговий тест»); the lab's row keeps the bare
        # name.  Equal names pair in page order, so the two MTHFR rows do too.
        candidates = [obs for obs in free
                      if obs["_key"].endswith("," + key) or obs["_key"].startswith(key + "(")]
    if number is not None:
        exact = [obs for obs in candidates
                 if obs["value_numeric"] is not None and _same_number(float(obs["value_numeric"]), number)]
        candidates = exact or candidates
    return candidates[0] if candidates else None


def _check_row(row: dict, pool: list[dict], lab_loose: Counter, obs_loose: Counter) -> dict:
    sign, number = parse_result(row["result"])
    is_info = (row["resulttype"] in INFO_RESULT_TYPES or row["result"] in {"", "-", "—"}
               or bool(_PLACEHOLDER_RE.search(row["result"])) or bool(_NOTE_ROW_RE.match(str(row["test"] or ""))))
    obs = _find_observation(row, pool, lab_loose, obs_loose, number)
    if obs is not None:
        obs["_used"] = True
    item = {"cls": "", "lab": row, "obs": _obs_view(obs) if obs else None, "flag": "", "unit_differs": False,
            "_number": number, "_sign": sign}
    if is_info:
        item["cls"] = "info"
    elif obs is None:
        item["cls"] = "missing"
    else:
        _judge(item, row, obs, number, sign)
    return item


def _place_unpaired(obs: dict, items: list[dict], info_texts: list[tuple[dict, str]]) -> None:
    """An observation no lab row claimed: the wrapped-label partner of a
    missing row, a part of a descriptive result, or an extra."""
    # A wrapped label that lost its tail: «Ліпопротеїди високої щільності
    # (ЛПВЩ» for «… (ЛПВЩ, HDL)».  Paired only by a unique prefix *and* the
    # same number, so a truncated name never borrows another test's row.
    prefixed = [item for item in items if item["cls"] == "missing" and len(obs["_key"]) >= 8
                and name_key(item["lab"]["test"]).startswith(obs["_key"])
                and item["_number"] is not None and obs["value_numeric"] is not None
                and _same_number(float(obs["value_numeric"]), item["_number"])]
    if len(prefixed) == 1:
        item = prefixed[0]
        item["obs"] = _obs_view(obs)
        _judge(item, item["lab"], obs, item["_number"], item["_sign"])
        if item["cls"] == "match":
            item["cls"] = "name_mismatch"
        return
    covering = _covering_item(obs, items, info_texts)
    if covering is not None:
        items.append({"cls": "info", "lab": covering["lab"], "obs": _obs_view(obs), "flag": "",
                      "unit_differs": False, "part_of": True})
        return
    items.append({"cls": "extra", "lab": None, "obs": _obs_view(obs), "flag": "", "unit_differs": False})


def _covering_item(obs: dict, items: list[dict], info_texts: list[tuple[dict, str]]) -> dict | None:
    """The descriptive result this observation is a part of, if any."""
    # Part of a descriptive result the lab keeps as one block — a
    # coprogram parameter, an antibiotic in a susceptibility table.
    # Matched by the label's tail, or by every word of it: a coprogram
    # nests «змінені» under «М'язові волокна».
    tail = obs["_loose"][-20:]
    words = [name_key(word) for word in re.findall(r"\w{4,}", re.sub(r"\([^()]*\)", "", str(obs["raw_name"])))]
    covering = next((item for item, text in info_texts
                     if (len(tail) >= 4 and tail in text) or (words and all(word in text for word in words))), None)
    # The lab's record only says "the result is in the PDF" (ALEX²): every
    # value read from that PDF is the result it points to, not an extra.
    return covering or next((item for item in items if item["cls"] == "info"
                             and _PLACEHOLDER_RE.search(item["lab"]["result"])), None)


def _pair_lone_row(items: list[dict], pool: list[dict]) -> None:
    """The only unpaired row and the only unpaired value of the order that
    agree on the result are the same test, named differently."""
    missing = [item for item in items if item["cls"] == "missing"]
    extra = [item for item in items if item["cls"] == "extra"]
    if len(missing) != 1 or len(extra) != 1:
        return
    lone, spare = missing[0], extra[0]
    obs = next(o for o in pool if o["id"] == spare["obs"]["id"])
    if lone["_number"] is not None:
        same = (obs["value_numeric"] is not None and _same_number(float(obs["value_numeric"]), lone["_number"])
                and comparator(obs["comparator"]) == lone["_sign"])
    else:
        same = obs["value_numeric"] is None and _same_text(obs["value_text"], lone["lab"]["result"])
    if not same:
        return
    lone["obs"] = spare["obs"]
    _judge(lone, lone["lab"], obs, lone["_number"], lone["_sign"])
    if lone["cls"] == "match":
        lone["cls"] = "name_mismatch"
    items.remove(spare)


def _numbers(order_row) -> list[str]:
    return [str(value) for value in (order_row["order_id"], order_row["remote_ref"]) if value]


def check_order(connection, owner_user_id: str, order_row) -> dict | None:
    """The live cross-check for one tracked order, or None without lab rows
    (some orders come with a PDF and no structured values at all)."""
    return check_orders(connection, owner_user_id, [order_row]).get(_order_key(order_row))


def _order_key(row) -> tuple[str, str]:
    return str(row["provider"]), str(row["order_id"])


def check_orders(connection, owner_user_id: str, order_rows: list) -> dict[tuple[str, str], dict | None]:
    """(provider, order id) → its live cross-check, for any number of orders in two
    queries (PERF-13: the profile used to run two per order)."""
    with_rows = [row for row in order_rows if row["rows_json"] and json.loads(row["rows_json"])]
    # The lab's record of an order IS its rows: comparing it with them would
    # report every value as "matches the lab record" and offer to verify it.
    records = _lab_records(connection, [row["document_id"] for row in with_rows])
    with_rows = [row for row in with_rows if str(row["document_id"] or "") not in records]
    found = _documents_by_number(connection, owner_user_id,
                                 {number for row in with_rows for number in _numbers(row)})
    picked = {_order_key(row): _pick(found, _numbers(row)) for row in with_rows}
    kept = _kept_documents(connection, [row["document_id"] for row in with_rows])
    pairs = _duplicate_pairs(connection, {doc for docs in picked.values() for doc in docs} | set(kept.values()))
    plan = {}
    for row in with_rows:
        own = kept.get(str(row["document_id"] or ""), "")
        # The order's own document first, and never a copy of a report: a
        # Telegram re-upload carrying the same order number paired the lab's
        # rows with its values and left the kept document's as "extra".  A
        # copy is the other side of a duplicate relation with the order's
        # document, or the newer side of one between two others.
        copies = {b if a == own else a for a, b in pairs if own in (a, b)} | {a for a, b in pairs}
        document_ids = [own] if own else []
        document_ids += [doc for doc in picked[_order_key(row)] if doc != own and doc not in copies]
        plan[_order_key(row)] = (row, document_ids)
    pooled = _observation_rows(connection, owner_user_id,
                               sorted({doc for _, docs in plan.values() for doc in docs}))
    results: dict[tuple[str, str], dict | None] = {_order_key(row): None for row in order_rows}
    for key, (row, document_ids) in plan.items():
        rank = {doc: index for index, doc in enumerate(document_ids)}
        mine = sorted(_for_order(pooled, _numbers(row), document_ids), key=lambda obs: rank[obs["document_id"]])
        result = cross_check(json.loads(row["rows_json"]), mine, key[1])
        result["document_ids"] = document_ids
        result["provider"] = row["provider"]
        results[key] = result
    return results


def _persist_check(connection, owner_user_id: str, order_row, result: dict | None) -> None:
    if result is None:
        return
    connection.execute(
        """UPDATE lab_orders SET crosscheck_json=?, crosscheck_at=?
            WHERE owner_user_id=? AND provider=? AND order_id=?""",
        (json.dumps({"counts": result["counts"], "documents": result["document_ids"]}), result["computed_at"],
         owner_user_id, order_row["provider"], order_row["order_id"]),
    )


def _orders_for_document(connection, owner_user_id: str, document_id: str) -> list:
    document = connection.execute(
        "SELECT order_identifier FROM documents WHERE id=? AND owner_user_id=?", (document_id, owner_user_id)
    ).fetchone()
    if document is None:
        return []
    numbers = {str(document["order_identifier"])} if _real_number(document["order_identifier"]) else set()
    numbers |= {
        str(row[0]) for row in connection.execute(
            "SELECT order_identifier FROM reports WHERE document_id=? AND order_identifier IS NOT NULL", (document_id,))
        if _real_number(row[0])
    }
    marks = ",".join("?" for _ in numbers) or "NULL"
    return connection.execute(
        f"""SELECT * FROM lab_orders WHERE owner_user_id=? AND rows_json IS NOT NULL
             AND (document_id=? OR order_id IN ({marks}) OR remote_ref IN ({marks}))
             ORDER BY provider, order_id""",
        (owner_user_id, document_id, *numbers, *numbers),
    ).fetchall()


def _enabled_rows(settings: Settings, rows: list) -> list:
    enabled = set(active_providers(settings))
    return [row for row in rows if row["provider"] in enabled]


def document_check(settings: Settings, user, document_id: str) -> dict | None:
    """What the document page's cross-check panel shows, or None when there is
    nothing to show: every provider off, a guest, or no lab rows for it."""
    if not user or user.get("token_kind") in {"guest", "api"}:
        return None
    enabled = set(active_providers(settings))
    if not enabled:
        return None
    with connect(settings) as connection:
        orders = [row for row in _orders_for_document(connection, user["id"], document_id)
                  if row["provider"] in enabled]
        checks = [check for check in check_orders(connection, user["id"], orders).values() if check]
    if not checks:
        return None
    by_observation: dict[str, str] = {}
    verifiable: list[str] = []
    rows = {(row["provider"], str(row["order_id"])): row for row in orders}
    for check in checks:
        by_observation.update(check["by_observation"])
        verifiable += [item["obs"]["id"] for item in check["items"]
                       if item["cls"] == "match" and item["obs"]["document_id"] == document_id
                       and item["obs"]["status"] in {"extracted", "corrected"}]
        row = rows[(check["provider"], check["order_id"])]
        check.update(ready=int(row["ready"]), total=int(row["total"]), lab_status=row["lab_status"],
                     changed_at=row["rows_changed_at"], provider_name=provider(row["provider"]).NAME,
                     other_documents=[doc for doc in check["document_ids"] if doc != document_id])
    return {"checks": checks, "by_observation": by_observation, "verifiable": verifiable}


def observation_classes(settings: Settings, user, document_id: str) -> dict[str, str]:
    """observation id → cross-check class, for a per-row badge."""
    check = document_check(settings, user, document_id)
    return check["by_observation"] if check else {}


def verify_matches(settings: Settings, user_id: str, document_id: str, observation_ids: list[str],
                   token_kind: str | None = None) -> int:
    """Mark verified the values the person was shown as matching the lab and
    asked to verify — re-checked now, so a value that changed after the page
    rendered is not verified on stale evidence.  Audited per value, like the
    state route.  Runs from a person's button press — or from the owner's
    ``agent`` credential, when the owner has authorised that; ``token_kind``
    then lands in the audit row, so the record says it was not their hand."""
    wanted = set(observation_ids)
    with transaction(settings) as connection:
        if connection.execute("SELECT 1 FROM documents WHERE id=? AND owner_user_id=?", (document_id, user_id)).fetchone() is None:
            raise LookupError(document_id)
        orders = _enabled_rows(settings, _orders_for_document(connection, user_id, document_id))
        eligible: dict[str, dict] = {}
        for row in orders:
            check = check_order(connection, user_id, row)
            for item in (check or {}).get("items", []):
                obs = item["obs"]
                if (item["cls"] == "match" and obs and obs["id"] in wanted and obs["document_id"] == document_id
                        and obs["status"] in {"extracted", "corrected"}):
                    eligible[obs["id"]] = {"previous": obs["status"], "order_id": check["order_id"],
                                           "provider": row["provider"]}
        for observation_id, info in eligible.items():
            connection.execute(
                "UPDATE observations SET verification_status='verified' WHERE id=? AND owner_user_id=?",
                (observation_id, user_id),
            )
            connection.execute(
                """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
                                            details_json, created_at)
                   VALUES (?, ?, 'observation_verify', 'observation', ?, ?, ?)""",
                (user_id, user_id, observation_id,
                 json.dumps({"previous_state": info["previous"], "document_id": document_id,
                             "via": "lab_crosscheck", "provider": info["provider"], "order_id": info["order_id"],
                             **({"token_kind": token_kind} if token_kind else {})}),
                 utc_now()),
            )
        for row in orders:
            _persist_check(connection, user_id, row, check_order(connection, user_id, row))
    return len(eligible)


# --- sync --------------------------------------------------------------------------


def _claim_run(settings: Settings, user_id: str, key: str) -> bool:
    stale = (datetime.now(UTC) - STALE_RUN).isoformat(timespec="seconds")
    with transaction(settings, immediate=True) as connection:
        return bool(connection.execute(
            """UPDATE lab_accounts SET sync_state='running', sync_detail_key=NULL, sync_started_at=?,
                   sync_finished_at=NULL WHERE user_id=? AND provider=?
                   AND (sync_state<>'running' OR sync_started_at IS NULL OR sync_started_at < ?)""",
            (utc_now(), user_id, key, stale),
        ).rowcount)


def _finish_run(settings: Settings, user_id: str, key: str, state: str, detail: str | None, summary: dict) -> None:
    with transaction(settings) as connection:
        connection.execute(
            """UPDATE lab_accounts SET sync_state=?, sync_detail_key=?, sync_finished_at=?, sync_summary_json=?
                WHERE user_id=? AND provider=?""",
            (state, detail, utc_now(), json.dumps(summary), user_id, key),
        )


def _earlier_copy(settings: Settings, user_id: str, document_id: str) -> str | None:
    """The document a just-imported file repeats, which then becomes its copy.

    A clinic's PDF of a report the person uploaded by hand is rarely the same
    bytes (a re-export), so the import recognises it only once it is read:
    the pipeline records a ``duplicate`` relation when the words, or every
    result, are the same.  The order is then linked to the earlier upload and
    the new file set aside, as a byte-identical file would be."""
    with transaction(settings) as connection:
        found = connection.execute(
            """SELECT r.target_document_id FROM document_relations r
                 JOIN documents d ON d.id=r.target_document_id
                WHERE r.source_document_id=? AND r.relationship='duplicate' AND r.notes LIKE 'auto:%'
                  AND d.owner_user_id=? AND d.duplicate_of_document_id IS NULL
                ORDER BY d.imported_at LIMIT 1""",
            (document_id, user_id),
        ).fetchone()
        if found is None:
            return None
        try:
            mark_document_duplicate(connection, user_id, document_id, str(found[0]), user_id)
        except (DuplicateRefused, LookupError):
            return None
        return str(found[0])


def _upload_target(settings: Settings, name: str) -> Path:
    """Same corner of the sources tree as a browser upload (app._upload_target)."""
    folder = settings.source_dir / "uploads" / utc_now()[:7]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    counter = 1
    while target.exists():
        target = folder / f"{Path(name).stem}-{counter}{Path(name).suffix}"
        counter += 1
    return target


def _wait_for_job(settings: Settings, job_id: str, inline: bool):
    if inline:
        intake.drain_now(settings)
    deadline = time.monotonic() + JOB_WAIT_SECONDS
    while True:
        with connect(settings) as connection:
            job = connection.execute("SELECT state, document_id FROM upload_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None or job["state"] in {"done", "failed", "skipped"} or time.monotonic() > deadline:
            return job
        time.sleep(0.5)


def _upsert_order(connection, user_id: str, key: str, person_id: str, order: dict, *, account_user_id: str,
                  **fields) -> None:
    """``user_id`` is the record that receives the order; ``account_user_id``
    whose lab credential fetched it — set once, on first sight: the same order
    may later arrive through the receiver's own connection too."""
    now = utc_now()
    base = {
        "remote_ref": order.get("remote_ref"),
        "ordered_at": order.get("ordered_at"),
        "lab_status": order.get("lab_status"),
        "ready": int(order.get("ready") or 0),
        "total": int(order.get("total") or 0),
        "last_synced_at": now,
        **fields,
    }
    columns = ", ".join(base)
    connection.execute(
        f"""INSERT INTO lab_orders(owner_user_id, account_user_id, provider, remote_person_id, order_id,
                first_seen_at, {columns})
            VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in base)})
            ON CONFLICT(owner_user_id, provider, order_id) DO UPDATE SET remote_person_id=excluded.remote_person_id,
            account_user_id=COALESCE(lab_orders.account_user_id, excluded.account_user_id),
            {", ".join(f"{name}=excluded.{name}" for name in base)}""",
        (user_id, account_user_id, key, person_id, order["order_id"], now, *base.values()),
    )


def _content_match(connection, user_id: str, key: str, order: dict, rows: list[dict]) -> str | None:
    """A document of this lab, dated within a day of the order, printing no
    (or a misread) order number, whose values agree with the lab's rows: the
    old reports that carry no number are recognised by what they say.  At
    least half of the document's values must match, so a same-day report of
    a different order is never claimed."""
    days = [date.fromisoformat(day) for day in order.get("dates") or []]
    if not days or not rows:
        return None
    low, high = (min(days) - timedelta(days=1)).isoformat(), (max(days) + timedelta(days=1)).isoformat()
    numbers = [order["order_id"], order.get("remote_ref")]
    candidates = connection.execute(
        """SELECT d.id, d.order_identifier FROM documents d JOIN vendors v ON v.id=d.vendor_id
            WHERE d.owner_user_id=? AND v.canonical_name=? AND d.duplicate_of_document_id IS NULL
              AND d.extraction_strategy<>'lab_api' AND d.report_date BETWEEN ? AND ?
              AND d.id NOT IN (SELECT document_id FROM lab_orders WHERE owner_user_id=? AND document_id IS NOT NULL
                                  AND NOT (provider=? AND order_id=?))
            ORDER BY d.imported_at""",
        (user_id, provider(key).VENDOR, low, high, user_id, key, order["order_id"]),
    ).fetchall()
    best, best_score = None, None
    for candidate in candidates:
        if _real_number(candidate["order_identifier"]) and str(candidate["order_identifier"]) not in numbers:
            continue
        observations = _observations(connection, user_id, [n for n in numbers if n], [candidate["id"]])
        matches = cross_check(rows, observations)["counts"]["match"]
        # More matching values first; on a tie, the report holding nothing
        # beyond the lab's rows («Печінкові проби-1» before «Печінкові проби 3»,
        # which adds total protein to the same seven values).
        score = (matches, -abs(len(observations) - len(rows)))
        if matches and matches * 2 >= len(observations) and (best_score is None or score > best_score):
            best, best_score = str(candidate["id"]), score
    return best


#: An order the lab left part-done this long is not going to finish: the
#: ready results are imported and the order says so (EskuLab 5189508 has sat
#: at 9 of 40 since 2022).
PARTIAL_IMPORT_AFTER = timedelta(days=30)


def _stalled(order: dict, today: date | None = None) -> bool:
    day = str(order.get("ordered_at") or "")[:10]
    if order.get("complete") or not int(order.get("ready") or 0) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return False
    return date.fromisoformat(day) <= (today or date.today()) - PARTIAL_IMPORT_AFTER


def _audit(connection, owner_user_id: str, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (owner_user_id, owner_user_id, action, entity_type, entity_id, json.dumps(details, ensure_ascii=False),
         utc_now()),
    )


def _results_document(connection, user_id: str, key: str, numbers: list, documents: list) -> str | None:
    """The document holding the order's results, among ``documents`` (the
    linked one first, then those printing the order number).  An ALEX² order
    prints its number on a cover sheet with no values; the 296 results are a
    second PDF, which carries the lab's order number only in its file name or
    title.  Linking the cover made the cross-check compare nothing (DOCC-15)."""
    documents = [doc for doc in dict.fromkeys(documents) if doc]
    if documents:
        marks = ",".join("?" for _ in documents)
        with_values = {str(row[0]) for row in connection.execute(
            f"""SELECT DISTINCT document_id FROM observations WHERE owner_user_id=? AND document_id IN ({marks})
                  AND verification_status<>'rejected'""", (user_id, *documents))}
        for doc in documents:
            if doc in with_values:
                return doc
    numbers = [str(number) for number in numbers if number and len(str(number)) >= 5]
    for number in numbers:
        pattern = re.compile(rf"(?<!\d){re.escape(number)}(?!\d)")
        for row in connection.execute(
            """SELECT d.id, d.original_filename, d.title FROM documents d JOIN vendors v ON v.id=d.vendor_id
                WHERE d.owner_user_id=? AND v.canonical_name=? AND d.duplicate_of_document_id IS NULL
                  AND d.extraction_strategy<>'lab_api' AND (d.original_filename LIKE ? OR d.title LIKE ?)
                  AND EXISTS (SELECT 1 FROM observations o WHERE o.document_id=d.id
                                 AND o.verification_status<>'rejected')
                  AND d.id NOT IN (SELECT document_id FROM lab_orders WHERE owner_user_id=?
                                      AND document_id IS NOT NULL AND NOT (provider=? AND order_id IN (?, ?)))
                ORDER BY d.imported_at, d.id""",
            (user_id, provider(key).VENDOR, f"%{number}%", f"%{number}%", user_id, key,
             numbers[0], numbers[-1]),
        ):
            if pattern.search(f"{row['original_filename']} {row['title']}"):
                return str(row["id"])
    return documents[0] if documents else None


# --- an order the lab reports with no file ----------------------------------------
#
# Some finished orders have results in the lab's record and no PDF at all:
# Ekspert's ``has_file: false`` (a rapid antigen test entered at the desk), a
# Synevo in-lab order with no web id, one behind an eHealth one-time code.
# Their rows used to stay in ``lab_orders`` and reach nothing.  They are filed
# as a document of their own — the lab's record of the order, stored as the
# JSON its service answered with.  Not a PDF, never shown as one: the document
# page says "reported by the lab's online service, no PDF issued", with the
# lab, the order number and the day.  The values stay ``extracted`` like any
# import.  A real report arriving later (the lab attaches the file, or the
# person uploads it) takes the order over, and the record is set aside as its
# copy (``mark_document_duplicate``), so nothing is counted twice.

#: ``documents.extraction_strategy`` (and ``observations.extraction_method``)
#: of the lab's own record of an order.
LAB_RECORD = "lab_api"


def _lab_records(connection, document_ids: list) -> set[str]:
    """Which of these documents are the lab's own record of an order."""
    ids = sorted({str(doc) for doc in document_ids if doc})
    if not ids:
        return set()
    return {str(row[0]) for row in connection.execute(
        f"SELECT id FROM documents WHERE extraction_strategy=? AND id IN ({','.join('?' * len(ids))})",
        (LAB_RECORD, *ids))}


def _record_line(row: dict) -> str:
    """One row as evidence text: the lab's words, nothing of ours."""
    value = " ".join(part for part in (row["result"], row["units"]) if part)
    norm = "; ".join(row["norm"])
    return f"{row['test']}: {value}" + (f" ({norm})" if norm else "")


#: A line of the lab's reference block that says how it was measured
#: («Безціанидовий SLS-метод», «Виконано на аналізаторі ...», «Лейкоцити
#: визначаються за активністю лейкоцитестерази.»), not what is normal.  One
#: predicate with the PDF reader's (`parsers.method_note`).
_method_note = method_note


#: A row name that is a number and one word («16 генотип») says what was
#: measured only beside its test: Synevo's HPV genotyping lists fourteen of
#: them under «ПЛР. ВПЛ ВКР (генотипування 16, 18, …)».
_BARE_NAME_RE = re.compile(r"\d+\s+[^\W\d_]+")
#: A packet's catalogue code (EskuLab «F9008 Кальпротектин …»).
_PACKET_CODE_RE = re.compile(r"^[A-ZА-ЯІЇЄ]\d{3,5}\s+")


def _record_name(row: dict) -> str:
    """The row's name, with its test in front when the name alone says nothing:
    «ПЛР. ВПЛ ВКР, 16 генотип», the «heading, name» form the PDF reader gives
    a row printed under its heading."""
    name = without_specimen_label(str(row["test"]))
    if not _BARE_NAME_RE.fullmatch(name.strip()):
        return name
    test = collapse_space(re.sub(r"\([^()]*\)", " ", _PACKET_CODE_RE.sub("", str(row.get("packet") or ""))))
    test = test.strip(" ,;:-\"«»")
    return f"{test}, {name.strip()}" if test else name


def _record_value(row: dict, site: str | None = None) -> ParsedObservation | None:
    """A lab row as a value, or None for a heading, a descriptive block
    (microbiology, cytology — kept in the record file, not split into values),
    a note, a signature or a row with no result.  ``site`` is the smear
    sampling site the rows above named («ТОЧКА 2» / «VAGINA»)."""
    result = row["result"]
    if (not row["test"] or result in {"", "-", "—"} or row["resulttype"] in INFO_RESULT_TYPES
            or _PLACEHOLDER_RE.search(result) or _NOTE_ROW_RE.match(str(row["test"]))):
        return None
    sign, number = parse_result(result)
    norm = "; ".join(line for line in row["norm"] if not _method_note(line)) or None
    limits = reference_limits(norm)
    name = _record_name(row)
    value_text = None if number is not None else result
    grade = _GRADE_RESULT_RE.match(str(result).strip()) if name.strip().casefold() == "висновок" else None
    if grade:
        name, value_text = collapse_space(grade["name"]), grade["grade"]
    return ParsedObservation(
        raw_name=name, value_numeric=number, value_text=value_text,
        comparator=sign, unit_raw=row["units"] or None, reference_text=norm, reference_low=limits.low,
        reference_high=limits.high, page_number=1, evidence_text=_record_line(row), confidence=0.9,
        extraction_method=LAB_RECORD,
        reference_low_inclusive=limits.low_inclusive, reference_high_inclusive=limits.high_inclusive,
        # The lab's own "out of range" is the vendor's reading here: there is
        # no printed report for the bounds to speak for -- except its own
        # interval, which decides as a printed one does (a "critical" on a
        # bound «5.5 - 7.0» includes is the bounds' reading, in range).
        vendor_interpretation=_lab_reading(row, {}, number)
        if row["state"] == "critical" and not _inside_printed_band({"value_numeric": number}, row, None, None)
        and not _states_no_interval({}, row)
        else None,
        specimen=site,
    )


def _record_title(rows: list[dict]) -> str:
    """Every packet the order holds («Аналіз сечі загальний (…) · Загальний аналіз
    крові (…)»), or the first valued test when it names none.  The first packet
    alone titled a urinalysis-and-blood-count order as a urinalysis."""
    packets = list(dict.fromkeys(row["packet"].strip('"«» ') for row in rows if row["packet"].strip('"«» ')))
    if packets:
        return joined_title(packets)
    return next((row["test"] for row in rows if _record_value(row) is not None), "")


def _retitle_lab_records(settings: Settings, connection) -> int:
    """Give stored lab records the title :func:`_record_title` reads today.  A
    record has no file to re-read, so this is the only way a better title
    reaches one; a title a person chose is left alone."""
    changed = 0
    for row in connection.execute(
            "SELECT id, source_path, title FROM documents WHERE extraction_strategy=? "
            "AND COALESCE(title_set_by, '') <> 'human'", (LAB_RECORD,)).fetchall():
        try:
            payload = json.loads(resolve_source_path(settings, str(row["source_path"])).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = [item for item in payload.get("rows") or [] if isinstance(item, dict) and item.get("test")]
        title = _record_title(rows)[:240]
        if title and title != row["title"]:
            connection.execute("UPDATE documents SET title=? WHERE id=?", (title, row["id"]))
            connection.execute("UPDATE reports SET title=? WHERE document_id=?", (title, row["id"]))
            changed += 1
    return changed


def _record_values(rows: list[dict]) -> list[tuple[dict, ParsedObservation | None]]:
    """Every row with the value it files as (None: not a value), in order.

    A smear prints its sampling site as a row of its own -- «ТОЧКА 2» /
    «VAGINA», then the seven readings taken there, then «ТОЧКА 3» / «CERVIX»
    and the same seven again.  Stored as results, the site lines were values
    and the fourteen readings below them carried no site, so the vaginal and
    cervical leukocytes could not be told apart.  The site is each reading's
    specimen instead, up to the next site or the conclusion.
    """
    site: str | None = None
    out: list[tuple[dict, ParsedObservation | None]] = []
    for row in rows:
        test = str(row.get("test") or "")
        if _SITE_ROW_RE.match(test):
            site = collapse_space(str(row.get("result") or "")) or None
            out.append((row, None))
            continue
        if test.strip().casefold().startswith("висновок"):
            site = None
        out.append((row, _record_value(row, site)))
    return out


def _record_day(order: dict) -> str | None:
    days = sorted(order.get("dates") or [])
    day = days[0] if days else str(order.get("ordered_at") or "")[:10]
    return day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or "") else None


def _file_lab_record(settings, connection, user_id: str, key: str, patient_id: str, order: dict,
                     rows: list[dict]) -> str | None:
    """File an order's rows as the lab's record of it; the document id, or
    None when no row carries a value.  The caller commits."""
    values = [(row, parsed) for row, parsed in _record_values(rows) if parsed is not None]
    if not values:
        return None
    lab, order_id, day, now = provider(key), str(order["order_id"]), _record_day(order), utc_now()
    title = _record_title(rows)
    payload = {
        "source": "lab_online_service", "provider": key, "lab": lab.NAME, "vendor": lab.VENDOR,
        "order_id": order_id, "remote_ref": order.get("remote_ref"), "ordered_at": order.get("ordered_at"),
        "lab_status": order.get("lab_status"), "no_file_reason": order.get("unavailable"),
        "received_at": now, "rows": rows,
    }
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    target = _upload_target(settings, f"{key}-{order_id} lab record.json")
    target.write_bytes(data)
    text = "\n".join(_record_line(row) for row in rows if row["test"])
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    document_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        vendor_id = ensure_vendor(connection, lab.VENDOR, None)
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, content_sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, order_identifier, report_date, collected_at,
                   imported_at, status)
               VALUES (?, ?, ?, ?, ?, ?, 'application/json', ?, ?, ?, 1, ?, 'laboratory', ?, 1, ?, ?, ?, ?, 'final')""",
            (document_id, user_id, patient_id, vendor_id, target.name, str(target.resolve()), len(data),
             hashlib.sha256(data).hexdigest(), text_hash, title[:240], LAB_RECORD, order_id, day, day, now),
        )
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, native_text_sha256,
                   extraction_method, native_char_count, image_count, review_status)
               VALUES (?, 1, ?, ?, ?, ?, 0, 'not_reviewed')""",
            (document_id, text, text_hash, LAB_RECORD, len(text)),
        )
        connection.execute(
            """INSERT INTO reports(id, owner_user_id, patient_id, document_id, vendor_id, title, clinical_type,
                   report_date, start_page, end_page, order_identifier, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'laboratory', ?, 1, 1, ?, 'final', ?)""",
            (report_id, user_id, patient_id, document_id, vendor_id, title[:240], day, order_id, now),
        )
        for _row, parsed in values:
            observation_id = insert_observation(
                connection, owner_user_id=user_id, patient_id=patient_id, document_id=document_id,
                report_id=report_id, vendor_id=vendor_id, observed_at=day, parsed=parsed)
            if parsed.vendor_interpretation:
                connection.execute(
                    "UPDATE observations SET vendor_interpretation_source='lab_record' WHERE id=?", (observation_id,))
        store_positions(connection, document_id, target)
        open_review_task(connection, user_id, document_id, [reason_part("review.verify_n", count=len(values))])
        index_search(connection, document_id, user_id,
                     " ".join([target.name, title, lab.VENDOR, "laboratory", text]))
        _audit(connection, user_id, "labsync_lab_record_filed", "document", document_id,
               {"provider": key, "order_id": order_id, "values": len(values), "reason": order.get("unavailable"),
                "parser_version": PARSER_VERSION})
        refresh_derived_observations(connection)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return document_id


def _retire_lab_record(connection, user_id: str, record_id: str, document_id: str, key: str, order_id: str) -> bool:
    """Set the lab's record aside as a copy of the document that now holds the
    order.  A value the person ruled on that the other does not hold keeps
    the record standing (``DuplicateRefused``): their ruling is not discarded."""
    try:
        mark_document_duplicate(connection, user_id, record_id, document_id, user_id)
    except (DuplicateRefused, LookupError) as exc:
        # ponytail: both stay in the record and the order points at the newer
        # document; the person settles it on the page (Mark as duplicate).
        logger.warning("labsync: lab record %s kept beside %s: %s", record_id, document_id, exc)
        return False
    _audit(connection, user_id, "labsync_lab_record_retired", "document", record_id,
           {"provider": key, "order_id": order_id, "replaced_by": document_id})
    return True


def lab_record(settings: Settings, document_id: str) -> dict | None:
    """What the document page shows for the lab's own record of an order: the
    lab, the order number, the day and the rows exactly as the lab's service
    returned them — read from the stored file.  None for any other document."""
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT source_path, report_date, order_identifier FROM documents WHERE id=? AND extraction_strategy=?",
            (document_id, LAB_RECORD)).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(resolve_source_path(settings, str(row["source_path"])).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    reason = payload.get("no_file_reason")
    return {
        "lab": str(payload.get("lab") or ""),
        "order_id": str(payload.get("order_id") or row["order_identifier"] or ""),
        "day": row["report_date"],
        "received_at": str(payload.get("received_at") or "")[:10] or None,
        "reason_key": reason if reason in ERROR_KEYS else None,
        "rows": [item for item in payload.get("rows") or [] if isinstance(item, dict) and item.get("test")],
    }


class _OrderSync:
    """One order being brought into one record.  Holds what the steps of
    :func:`_sync_order` share; each step returns the ``(outcome, changed)``
    that ends the sync, or ``None`` to go on."""

    def __init__(self, settings, account_user_id, owner_user_id, key, record_patient_id, client, person, order,
                 inline):
        self.settings, self.key, self.client = settings, key, client
        self.user_id = owner_user_id
        self.record_patient_id, self.person, self.order, self.inline = record_patient_id, person, order, inline
        self.order_id = order["order_id"]
        self.upsert = functools.partial(_upsert_order, account_user_id=account_user_id)
        with connect(settings) as connection:
            self.tracked = connection.execute(
                "SELECT * FROM lab_orders WHERE owner_user_id=? AND provider=? AND order_id=?",
                (self.user_id, key, self.order_id),
            ).fetchone()
        self.previous = str(self.tracked["state"]) if self.tracked is not None else None

    def save(self, state: str, **fields) -> None:
        with transaction(self.settings) as connection:
            self.upsert(connection, self.user_id, self.key, self.person["id"], self.order, state=state, **fields)

    def settled(self) -> tuple[str, bool] | None:
        if self.previous in {"removed", "declined"}:
            return "already", False
        if self.previous in {"imported", "linked"} and not self.tracked["document_id"]:
            # The person deleted the document. Respect that: never bring it back.
            self.save("removed")
            return "removed", False
        return None

    def read_rows(self) -> None:
        self.rows = self.client.rows(self.order, self.person)
        digest = hashlib.sha256(json.dumps(self.rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.changed = self.previous in {"imported", "linked"} and self.tracked["rows_hash"] not in (None, digest)
        self.stalled = _stalled(self.order)
        self.complete = bool(self.order["complete"]) or self.stalled
        self.rows_fields = {"rows_json": json.dumps(self.rows, ensure_ascii=False), "rows_hash": digest,
                            "error_key": "labsync.partial_imported" if self.stalled else None,
                            **({"rows_changed_at": utc_now()} if self.changed else {})}
        # An accepted order that fails stays accepted (with its reason), so the
        # next run retries it instead of asking the person a second time.
        self.failed = "accepted" if self.previous == "accepted" else "failed"

    def hold(self) -> tuple[str, bool]:
        """Keep the lab's rows for the record's owner to decide on."""
        state = "awaiting" if self.complete else "pending"
        self.save(state, **self.rows_fields)
        return ("already" if self.previous == state else state), False

    def locate(self) -> None:
        """The documents already in the record that carry this order."""
        numbers = [self.order_id, self.order.get("remote_ref")]
        self.linked_before = str(self.tracked["document_id"]) if self.previous in {"imported", "linked"} else None
        with connect(self.settings) as connection:
            # The lab's own record holds the order only until a report does: it is
            # not "the document already linked", so the search below still runs.
            self.record = next(iter(_lab_records(
                connection, [self.tracked["document_id"] if self.tracked is not None else None])), None)
            if self.record and self.linked_before == self.record:
                self.linked_before = None
            self.held = documents_for_order(connection, self.user_id, numbers)
            if not self.held and not self.linked_before:
                found = _content_match(connection, self.user_id, self.key, self.order, self.rows)
                self.held = [found] if found else []
            self.best = _results_document(connection, self.user_id, self.key, numbers,
                                          [self.linked_before, *self.held]) \
                if self.linked_before or self.held else None

    def without_report(self) -> tuple[tuple[str, bool] | None, str | None, str | None]:
        """No report in the record yet: ``(result, state, document_id)``, the
        result ending the sync, else the state to file the order under."""
        if self.record and (self.order.get("unavailable") or not self.complete):
            return self.keep_record(), None, None
        if not self.complete:
            self.save("pending", **self.rows_fields)
            return ("pending", False), None, None
        if self.order.get("unavailable"):
            return self.file_record_only(), None, None
        result, document_id, fresh = self.fetch_reports()
        if result is not None:
            return result, None, None
        # Every file was one already in the record (uploaded by hand): linked.
        return None, ("imported" if fresh else "linked"), document_id

    def keep_record(self) -> tuple[str, bool]:
        # Still no report.  An amended record is filed anew and the old one
        # set aside as its copy, exactly as a report would replace it.
        document_id = self.record
        if self.changed:
            with transaction(self.settings) as connection:
                document_id = _file_lab_record(self.settings, connection, self.user_id, self.key,
                                               self.record_patient_id, self.order, self.rows) or self.record
                if document_id != self.record:
                    _retire_lab_record(connection, self.user_id, self.record, document_id, self.key, self.order_id)
        self.save("imported", document_id=document_id,
                  **{**self.rows_fields, "error_key": self.order.get("unavailable")})
        return ("reported" if document_id != self.record else "already"), self.changed

    def file_record_only(self) -> tuple[str, bool]:
        with transaction(self.settings) as connection:
            document_id = _file_lab_record(self.settings, connection, self.user_id, self.key,
                                           self.record_patient_id, self.order, self.rows)
            self.upsert(connection, self.user_id, self.key, self.person["id"], self.order,
                        state="imported" if document_id else "unavailable",
                        **{**self.rows_fields, "error_key": self.order["unavailable"],
                           **({"document_id": document_id} if document_id else {})})
        if document_id:
            return "reported", False
        return ("already" if self.previous == "unavailable" else "unavailable"), False

    def fetch_reports(self) -> tuple[tuple[str, bool] | None, str | None, bool]:
        """Download and queue every PDF: ``(result, document_id, fresh)``."""
        document_id, fresh = None, False
        try:
            for index, pdf in enumerate(self.client.pdfs(self.order, self.person)):
                kind, found = self.file_pdf(index, pdf)
                if kind == "failed":
                    return ("failed", False), document_id, fresh
                document_id = document_id or found
                fresh = fresh or kind == "fresh"
        except LabSyncError as exc:
            if not self.stalled or exc.key == ERROR_AUTH or document_id:
                raise
            # A part-done order whose ready part the lab offers no report for:
            # it keeps waiting, and says why.
            self.save("pending", **{**self.rows_fields, "error_key": "labsync.partial_no_pdf"})
            return (("already" if self.previous == "pending" else "pending"), False), document_id, fresh
        return None, document_id, fresh

    def file_pdf(self, index: int, pdf: bytes) -> tuple[str, str | None]:
        """One report: ``("failed", None)``, ``("same", id)`` for a document
        already in the record, or ``("fresh", id)`` for a newly read one."""
        # A clinic that names its documents (Doctor ELEKS) passes the
        # day and the name on in the file name, for the classifier.
        hint = " ".join(re.sub(r'[\\/:*?"<>|]+', " ", str(self.order.get("filename_hint") or "")).split())[:120]
        target = _upload_target(
            self.settings,
            f"{self.key}-{self.order_id}{'-' + str(index) if index else ''}{' ' + hint if hint else ''}.pdf")
        target.write_bytes(pdf)
        with connect(self.settings) as connection:
            same = connection.execute(
                "SELECT id FROM documents WHERE owner_user_id=? AND sha256=? ORDER BY imported_at LIMIT 1",
                (self.user_id, file_sha256(target)),
            ).fetchone()
        if same:
            target.unlink(missing_ok=True)
            return "same", str(same["id"])
        job_id = intake.enqueue(
            self.settings, owner_user_id=self.user_id, patient_id=self.record_patient_id,
            batch_id=str(uuid.uuid4()), kind="document", filename=target.name, source_path=target,
            byte_size=len(pdf), start=not self.inline,
        )
        self.save("importing", upload_job_id=job_id, **self.rows_fields)
        job = _wait_for_job(self.settings, job_id, self.inline)
        if job is None or job["state"] != "done" or not job["document_id"]:
            self.save(self.failed, error_key=ERROR_INGEST)
            return "failed", None
        earlier = _earlier_copy(self.settings, self.user_id, str(job["document_id"]))
        if earlier:
            return "same", earlier
        return "fresh", str(job["document_id"])

    def finish(self, state: str, document_id: str | None) -> tuple[str, bool]:
        """File the order under ``state`` and run the cross-check on it."""
        with transaction(self.settings) as connection:
            if self.linked_before and document_id != self.linked_before:
                _audit(connection, self.user_id, "labsync_order_relinked", "document", document_id,
                       {"provider": self.key, "order_id": self.order_id, "from_document_id": self.linked_before})
            if self.record and document_id and document_id != self.record:
                _retire_lab_record(connection, self.user_id, self.record, document_id, self.key, self.order_id)
            self.upsert(connection, self.user_id, self.key, self.person["id"], self.order, state=state,
                        document_id=document_id, **self.rows_fields)
            row = connection.execute(
                "SELECT * FROM lab_orders WHERE owner_user_id=? AND provider=? AND order_id=?",
                (self.user_id, self.key, self.order_id),
            ).fetchone()
            apply_check(connection, self.user_id, row)
        return ("already" if self.previous == state and not self.record else state), self.changed


def _sync_order(settings, account_user_id, owner_user_id, key, record_patient_id, client, person, order, inline,
                hold=False):
    """One order for one record; returns ``(outcome, changed)``.  The outcome
    is the order's new state, or ``already`` when that state was reached on an
    earlier run.  ``changed`` says the lab amended rows of an order already in
    the record.  ``hold``: the record belongs to another user who has not
    agreed to take this link's results without asking — keep the lab's rows
    so they can decide, and touch nothing in their record."""
    run = _OrderSync(settings, account_user_id, owner_user_id, key, record_patient_id, client, person, order, inline)
    done = run.settled()
    if done is not None:
        return done
    run.read_rows()
    if hold and run.previous not in {"accepted", "importing", "imported", "linked"}:
        return run.hold()
    run.locate()
    if run.linked_before:
        state, document_id = run.previous, run.best or run.linked_before
    elif run.held:
        state, document_id = "linked", run.best or run.held[0]
    else:
        done, state, document_id = run.without_report()
        if done is not None:
            return done
    return run.finish(state, document_id)


def apply_check(connection, user_id: str, row) -> dict[str, int]:
    """Everything a sync does with an order's stored lab rows once the order
    is in the record — no lab is called: adopt units the report never printed,
    carry the lab's flags into the verdict, store the counts, and open (or
    close) the review task for results the reading lacks.  Returns what
    changed."""
    key, order_id = str(row["provider"]), str(row["order_id"])
    check = check_order(connection, user_id, row)
    units = _adopt_lab_units(connection, user_id, key, order_id, check)
    flags = _apply_lab_flags(connection, user_id, key, order_id, check)
    if units or flags["set"] or flags["undone"]:
        check = check_order(connection, user_id, row)
    _persist_check(connection, user_id, row, check)
    return {"units": units, "flags": flags["set"], "flags_undone": flags["undone"],
            "notes": _store_lab_comments(connection, user_id, key, order_id, check),
            "collected": _collected_from_order(connection, user_id, row),
            "record_kept": _keep_unread_record_values(connection, user_id, row, check),
            "tasks": _review_missing(connection, user_id, key, row, check)}


def _lab_comments(row: dict) -> list[str]:
    """What the lab wrote under a descriptive result (EskuLab's culture JSON:
    ``comments`` and each organism's ``defaultComment``), once each."""
    try:
        result = json.loads(row["result"])
    except (ValueError, TypeError):
        return []
    if not isinstance(result, dict):
        return []
    found = [*(result.get("comments") or []),
             *((entry.get("bacteria") or {}).get("defaultComment") for entry in result.get("bacteria_found") or []
               if isinstance(entry, dict))]
    return list(dict.fromkeys(collapse_space(str(text)) for text in found if isinstance(text, str) and text.strip()))


def _store_lab_comments(connection, user_id: str, key: str, order_id: str, check: dict | None) -> int:
    """Keep the lab's comment on a culture with the organism it is about, in
    the value's note («Staphylococcus epidermidis природньо резистентний до
    цефтазидиму», «Виявлений збудник Lactobacillus spp. є контамінантом …»).
    The PDF prints it under the table, where no row reads it; without it a
    growth against «Не виявлено» stands unexplained.  A comment that only
    restates a value («Ступінь бактеріурії 1,0*10^3 КУО/мл») is left out.
    Idempotent: a note already holding the comment is not touched."""
    items = (check or {}).get("items", [])
    values = list({item["obs"]["id"]: item["obs"] for item in items if item["obs"]}.values())
    stored = 0
    for item in items:
        if item["cls"] != "info" or item.get("part_of"):
            continue
        material = word_key(item["lab"].get("material"))
        for comment in _lab_comments(item["lab"]):
            words = word_key(comment)
            for obs in values:
                name = word_key(re.sub(r"\([^()]*\)", " ", str(obs["name"] or ""))).strip(" .,:;")
                specimen = word_key(obs.get("specimen"))
                if (len(name) < 4 or not re.search(rf"(?<!\w){re.escape(name)}(?!\w)", words)
                        or re.match(rf"{re.escape(name)}\W*[<>≤≥]?\s*\d", words)
                        or (material and specimen and material != specimen)):
                    continue
                changed = connection.execute(
                    """UPDATE observations SET note=CASE WHEN TRIM(COALESCE(note, ''))='' THEN ?
                                                     ELSE note || ' ' || ? END
                        WHERE id=? AND owner_user_id=? AND instr(COALESCE(note, ''), ?)=0""",
                    (comment, comment, obs["id"], user_id, comment)).rowcount
                if changed:
                    stored += 1
                    _audit(connection, user_id, "observation_note_from_lab", "observation", obs["id"],
                           {"provider": key, "order_id": order_id, "note": comment})
    return stored


def _keep_unread_record_values(connection, user_id: str, row, check: dict | None) -> int:
    """The lab's record of an order holds what the order's report does not.

    A report that takes an order over sets the record aside as its copy
    (:func:`_retire_lab_record`), which empties it -- and a value the PDF
    reader missed was then gone from the record altogether (a 2016 beta-hCG
    «< 0.1 мМО/мл», whose unit the reader did not know).  So after every
    cross-check the record keeps exactly the rows the report lacks: restored
    from the lab's rows and stood up again while there are any, emptied and
    set aside again once the report reads them all.  Rows that share a value
    with an unpaired reading of the report are left to the person (likely the
    same result under another name).  A record a person set aside themselves
    is left alone.  Returns the values added or removed."""
    document_id = str(row["document_id"] or "")
    if not document_id or check is None:
        return 0
    record = connection.execute(
        """SELECT d.id, d.patient_id, d.vendor_id, d.report_date, d.duplicate_of_document_id, r.id report_id
             FROM documents d JOIN vendors v ON v.id=d.vendor_id LEFT JOIN reports r ON r.document_id=d.id
            WHERE d.owner_user_id=? AND d.extraction_strategy=? AND d.order_identifier=? AND d.id<>?
              AND v.canonical_name=?
            ORDER BY d.imported_at DESC, d.id LIMIT 1""",
        (user_id, LAB_RECORD, str(row["order_id"]), document_id, provider(str(row["provider"])).VENDOR)).fetchone()
    if record is None or record["report_id"] is None or not _set_aside_by_sync(connection, record):
        return 0
    spare = [item["obs"] for item in check["items"] if item["cls"] == "extra"]
    wanted: dict[str, ParsedObservation] = {}
    for item in check["items"]:
        parsed = _record_value(item["lab"]) if item["cls"] == "missing" else None
        if parsed is None or any(_same_result(parsed, obs) for obs in spare):
            continue
        wanted[parsed.evidence_text] = parsed
    held = connection.execute(
        "SELECT id, evidence_text, verification_status FROM observations WHERE document_id=? AND extraction_method=?",
        (record["id"], LAB_RECORD)).fetchall()
    changed = 0
    for obs in held:
        if obs["evidence_text"] not in wanted and obs["verification_status"] == "extracted":
            connection.execute("DELETE FROM observations WHERE id=?", (obs["id"],))
            changed += 1
    present = {obs["evidence_text"] for obs in held}
    for line, parsed in wanted.items():
        if line not in present:
            observation_id = insert_observation(
                connection, owner_user_id=user_id, patient_id=record["patient_id"], document_id=record["id"],
                report_id=record["report_id"], vendor_id=record["vendor_id"], observed_at=record["report_date"],
                parsed=parsed)
            if parsed.vendor_interpretation:
                connection.execute(
                    "UPDATE observations SET vendor_interpretation_source='lab_record' WHERE id=?", (observation_id,))
            changed += 1
    if not changed:
        return 0
    left = connection.execute("SELECT COUNT(*) FROM observations WHERE document_id=?", (record["id"],)).fetchone()[0]
    if left and record["duplicate_of_document_id"]:
        connection.execute("UPDATE documents SET duplicate_of_document_id=NULL WHERE id=?", (record["id"],))
        connection.execute(
            """DELETE FROM document_relations WHERE relationship='duplicate' AND notes='person:duplicate'
                AND ((source_document_id=? AND target_document_id=?) OR (source_document_id=? AND target_document_id=?))""",
            (record["id"], document_id, document_id, record["id"]))
        _audit(connection, user_id, "labsync_lab_record_kept", "document", str(record["id"]),
               {"provider": str(row["provider"]), "order_id": str(row["order_id"]), "beside": document_id,
                "values": left})
    elif not left and not record["duplicate_of_document_id"]:
        _retire_lab_record(connection, user_id, str(record["id"]), document_id, str(row["provider"]),
                           str(row["order_id"]))
    refresh_derived_observations(connection)
    return changed


def _set_aside_by_sync(connection, record) -> bool:
    """The record stands, or the sync set it aside -- not a person: the last
    word on it is the sync's retirement, not a person's "Mark as duplicate"."""
    if not record["duplicate_of_document_id"]:
        return True
    last = connection.execute(
        """SELECT action FROM audit_events WHERE entity_type='document' AND entity_id=?
             AND action IN ('document_marked_duplicate', 'labsync_lab_record_retired') ORDER BY id DESC LIMIT 1""",
        (record["id"],)).fetchone()
    return last is not None and last[0] == "labsync_lab_record_retired"


def _same_result(parsed: ParsedObservation, obs: dict) -> bool:
    if parsed.value_numeric is not None:
        return obs["value_numeric"] is not None and _same_number(float(obs["value_numeric"]), parsed.value_numeric)
    return obs["value_numeric"] is None and _same_text(obs["value_text"], parsed.value_text)


def _collected_from_order(connection, user_id: str, row) -> int:
    """Give the order's document the collection time the lab's order holds,
    when the page printed none (an EskuLab POLYCHECK sheet prints only the
    examination day; an Expert Hospital count only the date)."""
    document_id = row["document_id"]
    moment = lab_order_collected_at(connection, str(document_id)) if document_id else None
    if not moment:
        return 0
    changed = connection.execute(
        """UPDATE documents SET collected_at=? WHERE id=? AND owner_user_id=?
            AND COALESCE(collected_at, '')='' AND extraction_strategy<>?""",
        (moment, document_id, user_id, LAB_RECORD)).rowcount
    if changed:
        _audit(connection, user_id, "document_collected_from_lab", "document", str(document_id),
               {"provider": str(row["provider"]), "order_id": str(row["order_id"]), "collected_at": moment})
    return changed


def _unit_fits(unit: str, concept_id: str | None, preferred: str | None) -> bool:
    """A lab's unit is adopted only where it is a real unit of this measurement:
    the concept's own unit, or one convertible to it.  Specific gravity is
    dimensionless — the «г/мл» Ekspert's record carries folds to nothing — and
    a concept with no unit of its own gets none from a lab either (OPS-37)."""
    if not preferred:
        return False
    target = canonical_unit(preferred)
    for folded in _lab_units(unit):
        if folded and (folded == target or convert_value(1.0, folded, target, concept_id or "") is not None):
            return True
    return False


def _adopt_lab_units(connection, user_id: str, key: str, order_id: str, check: dict | None) -> int:
    """Give a value the unit its report never printed, from the lab's own
    record of the same result — only where the two agree on the number and
    the unit is a real unit of that measurement.  A unitless ALT is otherwise
    a second trend line beside every other lab's ALT in U/L, and a curated
    range written in U/L skips it.  The value stays unverified; the audit row
    says where the unit came from."""
    adopted = 0
    for item in (check or {}).get("items", []):
        if item["cls"] != "match" or not item.get("unit_from_lab"):
            continue
        unit = item["lab"]["units"].strip()
        concept = connection.execute(
            "SELECT o.concept_id, c.preferred_unit FROM observations o LEFT JOIN concepts c ON c.id=o.concept_id "
            "WHERE o.id=?", (item["obs"]["id"],),
        ).fetchone()
        if concept is None or not _unit_fits(unit, concept["concept_id"], concept["preferred_unit"]):
            continue
        changed = connection.execute(
            """UPDATE observations SET unit_raw=?, unit_canonical=? WHERE id=? AND owner_user_id=?
                AND (unit_raw IS NULL OR TRIM(unit_raw)='')""",
            (unit, stored_unit(unit, concept["preferred_unit"]), item["obs"]["id"], user_id),
        ).rowcount
        if changed:
            adopted += 1
            _audit(connection, user_id, "observation_unit_from_lab", "observation", item["obs"]["id"],
                   {"unit": unit, "provider": key, "order_id": order_id, "value": item["lab"]["result"]})
    return adopted


def undo_unfit_units(connection) -> int:
    """Take back every unit a sync adopted that is not a real unit of that
    measurement (before OPS-37 «г/мл» landed on a urine specific gravity).
    Idempotent: a value whose unit is no longer the adopted one is left
    alone.  Audited ``observation_unit_from_lab_undone``."""
    undone = 0
    for event in connection.execute(
        """SELECT a.owner_user_id, a.entity_id, a.details_json, o.unit_raw, o.concept_id, c.preferred_unit
             FROM audit_events a JOIN observations o ON o.id=a.entity_id
             LEFT JOIN concepts c ON c.id=o.concept_id
            WHERE a.action='observation_unit_from_lab' ORDER BY a.id""").fetchall():
        unit = str(json.loads(event["details_json"] or "{}").get("unit") or "")
        if not unit or event["unit_raw"] != unit or _unit_fits(unit, event["concept_id"], event["preferred_unit"]):
            continue
        connection.execute("UPDATE observations SET unit_raw=NULL, unit_canonical=? WHERE id=?",
                           (stored_unit(None, event["preferred_unit"]), event["entity_id"]))
        _audit(connection, str(event["owner_user_id"]), "observation_unit_from_lab_undone", "observation",
               str(event["entity_id"]), {"unit": unit, "reason": "not_a_unit_of_this_measurement"})
        undone += 1
    return undone


def _age(person) -> int | None:
    """Whole years on the day of the reading (today when undated)."""
    born, day = str(person["date_of_birth"] or "")[:10], str(person["observed_at"] or "")[:10]
    try:
        born_on = date.fromisoformat(born)
        on = date.fromisoformat(day) if day else date.today()
    except ValueError:
        return None
    return on.year - born_on.year - ((on.month, on.day) < (born_on.month, born_on.day))


def _apply_lab_flags(connection, user_id: str, key: str, order_id: str, check: dict | None) -> dict[str, int]:
    """Carry the lab's own "out of range" flag into the vendor tier of the
    verdict (CONTRACTS §5).  Only where the lab's row and our value agree,
    only over our own inference from the printed bounds, and only where the
    band printed for this person (or, with none readable, the lab's own) does
    not hold the value (:func:`_inside_printed_band`).  A flag the
    lab later drops (an amended result), that no longer belongs to the same
    value, or that the printed band contradicts, is taken back to the printed
    range's reading.
    Audited ``observation_flag_from_lab`` / ``…_undone``."""
    done = {"set": 0, "undone": 0}
    for item in (check or {}).get("items", []):
        obs = item["obs"]
        if not obs:
            continue
        agrees = item["cls"] in {"match", "name_mismatch"}
        # An adopted flag is read again too: its band depends on the
        # person's age and sex, and a reading made before the profile had
        # them ("borderline" between a woman's and a man's bands) must not
        # outlive the profile being filled in.
        if agrees and (item["flag"] == "lab_out_ours_in" or (obs["from_lab"] and item["flag"] == "lab_flag_adopted")):
            kind, count = _flag_from_lab(connection, user_id, key, order_id, item, obs)
            done[kind] += count
        elif obs["from_lab"] and not (agrees and item["flag"] == "lab_flag_adopted"):
            done["undone"] += _undo_lab_flag(connection, user_id, key, order_id, obs)
    return done


def _flag_from_lab(connection, user_id: str, key: str, order_id: str, item: dict, obs: dict) -> tuple[str, int]:
    """Adopt the lab's flag on one value, or take it back where the printed
    band holds the value: ``("set" | "undone", 1 when the value changed)``."""
    person = connection.execute(
        """SELECT p.date_of_birth, p.sex_at_birth, o.observed_at, o.vendor_reference_text,
                  o.vendor_reference_low, o.vendor_reference_high, o.vendor_reference_low_inclusive,
                  o.vendor_reference_high_inclusive, o.value_numeric
             FROM observations o LEFT JOIN patients p ON p.id=o.patient_id WHERE o.id=?""",
        (obs["id"],)).fetchone()
    if person is None:
        return "set", 0
    sex = person["sex_at_birth"] if person["sex_at_birth"] in {"male", "female"} else None
    item["lab_reading"] = _lab_reading(item["lab"], dict(person), None, _age(person), sex)
    if _inside_printed_band(dict(person), item["lab"], _age(person), sex) or _states_no_interval(
            dict(person), item["lab"]):
        # The band printed for this person holds the value -- on an inclusive
        # bound too (pH 5.5 against «5.5 - 7.0», basophils 1 against «0-1»)
        # -- and the paper prints no flag: the printed band decides.  EskuLab's
        # API sets "critical" on such values, and on whole 2022 orders; a copy
        # of the same report with no lab order judges them in range, and one
        # result must not be judged two ways.  An adoption is taken back.
        # So is one over a row that prints no interval at all («-»): the
        # "critical" points no direction and the paper flags nothing.
        return "undone", _undo_lab_flag(connection, user_id, key, order_id, obs) if obs["from_lab"] else 0
    changed = connection.execute(
        """UPDATE observations SET vendor_interpretation=?, vendor_interpretation_source='lab_record'
            WHERE id=? AND owner_user_id=? AND (
                  (vendor_interpretation_source IS NULL
                   AND (vendor_interpretation IS NULL OR vendor_interpretation IN ('', 'within_vendor_range')))
               OR (vendor_interpretation_source='lab_record' AND COALESCE(vendor_interpretation, '') <> ?))""",
        (item["lab_reading"], obs["id"], user_id, item["lab_reading"]),
    ).rowcount
    if not changed:
        return "set", 0
    _audit(connection, user_id, "observation_flag_from_lab", "observation", obs["id"],
           {"provider": key, "order_id": order_id, "value": item["lab"]["result"],
            "lab_state": "critical", "interpretation": item["lab_reading"],
            "previous": obs["interpretation"]})
    return "set", 1


def _undo_lab_flag(connection, user_id: str, key: str, order_id: str, obs: dict) -> int:
    """Take a flag the lab no longer stands behind back to the printed range's reading."""
    stored = connection.execute("SELECT * FROM observations WHERE id=? AND owner_user_id=?",
                                (obs["id"], user_id)).fetchone()
    if stored is None:
        return 0
    derived = interpretation(ParsedObservation(
        raw_name=stored["raw_name"], value_numeric=stored["value_numeric"], value_text=stored["value_text"],
        comparator=stored["comparator"], unit_raw=stored["unit_raw"],
        reference_text=stored["vendor_reference_text"], reference_low=stored["vendor_reference_low"],
        reference_high=stored["vendor_reference_high"], page_number=stored["page_number"] or 1,
        evidence_text=stored["evidence_text"] or "", confidence=stored["confidence"] or 0.0,
        reference_low_inclusive=stored["vendor_reference_low_inclusive"] != 0,
        reference_high_inclusive=stored["vendor_reference_high_inclusive"] != 0),
        stored["concept_id"])
    connection.execute(
        "UPDATE observations SET vendor_interpretation=?, vendor_interpretation_source=NULL WHERE id=?",
        (derived, obs["id"]))
    _audit(connection, user_id, "observation_flag_from_lab_undone", "observation", obs["id"],
           {"provider": key, "order_id": order_id, "interpretation": derived,
            "previous": obs["interpretation"]})
    return 1


# --- review tasks for what the reading lacks (OPS-19) -------------------------------
#
# CONTRACTS §2: `review_tasks.reason_key` + `reason_params_json` (migration 037,
# F2) render through `pipeline.review_reason_text` with t_plural on
# params["count"].  `reason` keeps an English sentence for anything that reads
# the old column.  One task per document and order; it follows the cross-check:
# updated when the missing rows change, closed when none are left, and never
# reopened over the same rows once the person resolved it.
REVIEW_MISSING = "labsync.review_missing"


def _review_columns(connection) -> bool:
    return {"reason_key", "reason_params_json"} <= {
        row[1] for row in connection.execute("PRAGMA table_info(review_tasks)")}


def _review_missing(connection, user_id: str, key: str, row, check: dict | None) -> int:
    document_id = row["document_id"]
    if not document_id or check is None:
        return 0
    names = [item["lab"]["test"] for item in check["items"] if item["cls"] == "missing"]
    lab_name, order_id = provider(key).NAME, str(row["order_id"])
    params = {"count": len(names), "lab": lab_name, "order": order_id, "names": "; ".join(names)[:600]}
    reason = (f"The {lab_name} record of order {order_id} has {len(names)} result(s) that were not read from "
              f"this document: {params['names']}. Add them from the lab cross-check, or check the pages.")
    keyed = _review_columns(connection)
    tasks = _review_tasks(connection, user_id, document_id, lab_name, order_id, keyed)
    open_tasks = [task for task in tasks if task["state"] == "open"]
    if not names:
        return _close_review_tasks(connection, open_tasks)
    same = [task for task in tasks
            if (json.loads(task["reason_params_json"] or "{}").get("names") if keyed else task["reason"]) ==
            (params["names"] if keyed else reason)]
    if open_tasks:
        if same and same[0]["state"] == "open":
            return 0
        target = open_tasks[0]["id"]
        connection.execute("UPDATE review_tasks SET reason=? WHERE id=?", (reason, target))
        if keyed:
            connection.execute("UPDATE review_tasks SET reason_params_json=? WHERE id=?",
                               (json.dumps(params, ensure_ascii=False), target))
        return 1
    if same:
        return 0  # the person resolved it over these very rows: not asked again
    task_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, created_at)
           VALUES (?, ?, 'document', ?, ?, ?)""", (task_id, user_id, document_id, reason, utc_now()))
    if keyed:
        connection.execute("UPDATE review_tasks SET reason_key=?, reason_params_json=? WHERE id=?",
                           (REVIEW_MISSING, json.dumps(params, ensure_ascii=False), task_id))
    return 1


def _close_review_tasks(connection, open_tasks: list) -> int:
    """Nothing is missing any more: resolve what was open."""
    for task in open_tasks:
        connection.execute(
            """UPDATE review_tasks SET state='resolved', resolution='lab_crosscheck_clear', resolved_at=?
                WHERE id=?""", (utc_now(), task["id"]))
    return len(open_tasks)


def _review_tasks(connection, user_id: str, document_id: str, lab_name: str, order_id: str, keyed: bool) -> list:
    """This order's missing-results tasks on the document, newest first."""
    if keyed:
        return [task for task in connection.execute(
            """SELECT id, state, reason_params_json FROM review_tasks WHERE owner_user_id=? AND entity_type='document'
                AND entity_id=? AND reason_key=? ORDER BY created_at DESC""", (user_id, document_id, REVIEW_MISSING))
            if json.loads(task["reason_params_json"] or "{}").get("order") == order_id]
    return connection.execute(
        """SELECT id, state, reason FROM review_tasks WHERE owner_user_id=? AND entity_type='document'
            AND entity_id=? AND reason LIKE ? ORDER BY created_at DESC""",
        (user_id, document_id, f"The {lab_name} record of order {order_id} %")).fetchall()


def _clean_record_references(connection) -> int:
    """Drop the method lines a lab record filed into its values' reference
    text before :func:`_method_note` existed; the bounds are read again from
    what is left.  Only the lab's own record rows, never a parsed report."""
    changed = 0
    for row in connection.execute(
            "SELECT id, vendor_reference_text FROM observations WHERE extraction_method=? "
            "AND vendor_reference_text IS NOT NULL", (LAB_RECORD,)).fetchall():
        lines = str(row["vendor_reference_text"]).split("; ")
        kept = [line for line in lines if not _method_note(line)]
        if len(kept) == len(lines):
            continue
        norm = "; ".join(kept) or None
        limits = reference_limits(norm)
        connection.execute(
            "UPDATE observations SET vendor_reference_text=?, vendor_reference_low=?, vendor_reference_high=?, "
            "vendor_reference_low_inclusive=?, vendor_reference_high_inclusive=? WHERE id=?",
            (norm, limits.low, limits.high, int(limits.low_inclusive), int(limits.high_inclusive), row["id"]))
        changed += 1
    return changed


def _refresh_record_values(settings: Settings, connection) -> int:
    """Read every stored lab record's rows again with :func:`_record_values`.

    Records filed before it kept a smear's «ТОЧКА n» site lines, its reader's
    signature and the panel's «Примітка» as values, left the site off the
    readings under it, the specimen label in the ESR's name and a purity
    grade under «Висновок».  The rows are the record's own file, so nothing is
    guessed: a stored value is paired with its row by the row's own line (in
    order, so the vaginal and cervical «Еритроцити: не виявлені» keep apart).
    A value that is no longer one is deleted, and one that is renamed is
    updated, only while nobody has ruled on it ('extracted').  A renamed value
    takes the concept its new name resolves to at once (the bare «16 генотип»
    concepts kept the HPV rows renamed «ПЛР. ВПЛ ВКР, 16 генотип» until a
    restart), and a reference an earlier reader dropped comes back from the
    record (the quintile percentage's scale explanation).
    """
    changed = 0
    for document in connection.execute(
            "SELECT id, source_path, vendor_id FROM documents WHERE extraction_strategy=?", (LAB_RECORD,)).fetchall():
        try:
            payload = json.loads(resolve_source_path(settings, str(document["source_path"])).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        stored = connection.execute(
            "SELECT id, raw_name, value_text, specimen, evidence_text, verification_status, concept_id, "
            "vendor_interpretation_source, vendor_reference_text, report_id, unit_raw FROM observations "
            "WHERE document_id=? AND extraction_method=? ORDER BY rowid", (document["id"], LAB_RECORD)).fetchall()
        unused = list(stored)
        for row, parsed in _record_values(payload.get("rows") or []):
            if not row.get("test"):
                continue
            line = _record_line(row)
            match = next((obs for obs in unused if obs["evidence_text"] == line), None)
            if match is None:
                continue
            unused.remove(match)
            if match["verification_status"] != "extracted":
                continue
            if parsed is None:
                connection.execute("DELETE FROM observations WHERE id=?", (match["id"],))
                changed += 1
                continue
            touched = False
            if match["vendor_interpretation_source"] == "lab_record" and not parsed.vendor_interpretation:
                # A "critical" the record's own interval contradicts: the bounds' reading.
                connection.execute(
                    "UPDATE observations SET vendor_interpretation=?, vendor_interpretation_source=NULL WHERE id=?",
                    (interpretation(parsed, match["concept_id"]), match["id"]))
                touched = True
            if (parsed.raw_name, parsed.value_text, parsed.specimen) != (
                    match["raw_name"], match["value_text"], match["specimen"]):
                connection.execute("UPDATE observations SET raw_name=?, value_text=?, specimen=? WHERE id=?",
                                   (parsed.raw_name, parsed.value_text, parsed.specimen, match["id"]))
                touched = True
            if match["vendor_reference_text"] is None and parsed.reference_text:
                connection.execute(
                    "UPDATE observations SET vendor_reference_text=?, vendor_reference_low=?, vendor_reference_high=?, "
                    "vendor_reference_low_inclusive=?, vendor_reference_high_inclusive=? WHERE id=?",
                    (parsed.reference_text, parsed.reference_low, parsed.reference_high,
                     int(parsed.reference_low_inclusive), int(parsed.reference_high_inclusive), match["id"]))
                touched = True
            concept_id, preferred = resolve_parsed_concept(connection, parsed, match["report_id"],
                                                           str(document["vendor_id"]), parsed.specimen)
            if concept_id != match["concept_id"]:
                connection.execute("UPDATE observations SET concept_id=?, unit_canonical=? WHERE id=?",
                                   (concept_id, stored_unit(match["unit_raw"], preferred, concept_id), match["id"]))
                touched = True
            changed += touched
    return changed


def recheck(settings: Settings) -> dict[str, int]:
    """Re-run every stored order's post-sync steps without calling any lab:
    the repair after a deploy that changed them.  Idempotent — a second run
    changes nothing.  Takes back unfit units, re-points an order linked to a
    document with no values at the one holding its results, then
    :func:`apply_check` per order."""
    summary = {"orders": 0, "relinked": 0, "units": 0, "units_undone": 0, "flags": 0, "flags_undone": 0, "tasks": 0,
               "references": 0, "titles": 0, "record_values": 0, "notes": 0, "collected": 0, "record_kept": 0}
    with transaction(settings) as connection:
        summary["units_undone"] = undo_unfit_units(connection)
        summary["references"] = _clean_record_references(connection)
        summary["record_values"] = _refresh_record_values(settings, connection)
        summary["titles"] = _retitle_lab_records(settings, connection)
        for row in connection.execute(
                """SELECT * FROM lab_orders WHERE state IN ('imported', 'linked') AND document_id IS NOT NULL
                    ORDER BY owner_user_id, provider, ordered_at, order_id""").fetchall():
            owner, key = str(row["owner_user_id"]), str(row["provider"])
            if key not in PROVIDERS:
                continue
            summary["orders"] += 1
            linked, numbers = str(row["document_id"]), _numbers(row)
            best = _results_document(connection, owner, key, numbers,
                                     [linked, *documents_for_order(connection, owner, numbers)])
            if best and best != linked:
                connection.execute("UPDATE lab_orders SET document_id=? WHERE owner_user_id=? AND provider=? "
                                   "AND order_id=?", (best, owner, key, row["order_id"]))
                _audit(connection, owner, "labsync_order_relinked", "document", best,
                       {"provider": key, "order_id": str(row["order_id"]), "from_document_id": linked})
                summary["relinked"] += 1
                row = connection.execute("SELECT * FROM lab_orders WHERE owner_user_id=? AND provider=? "
                                         "AND order_id=?", (owner, key, row["order_id"])).fetchone()
            for name, count in apply_check(connection, owner, row).items():
                summary[name] += count
    return summary


def _sync_link(settings, account_user_id, key, client, link, person, record_patient_id, summary, inline) -> None:
    """Every order of one lab person, into the record its link names."""
    owner = str(link["target_user_id"]) if link is not None else account_user_id
    hold = link is not None and link["consent"] == "asked"
    orders = sorted(client.orders(person), key=lambda order: str(order.get("ordered_at") or ""))
    summary["total"] += len(orders)
    for order in orders:
        if summary["orders"] and ORDER_DELAY_SECONDS:
            time.sleep(ORDER_DELAY_SECONDS)
        _progress(settings, account_user_id, key, summary, order)
        summary["orders"] += 1
        changed = False
        try:
            outcome, changed = _sync_order(settings, account_user_id, owner, key, record_patient_id, client, person,
                                           order, inline, hold)
        except LabSyncError as exc:
            if exc.key == ERROR_AUTH:
                raise
            outcome = "failed"
            _record_failure(settings, account_user_id, owner, key, person, order, exc.key)
        except Exception:  # noqa: BLE001 -- one bad order must not end the run
            logger.exception("labsync: %s order failed", key)
            outcome = "failed"
            _record_failure(settings, account_user_id, owner, key, person, order, ERROR_INGEST)
        summary[outcome] += 1
        summary["changed"] += int(changed)


def _progress(settings, account_user_id: str, key: str, summary: dict, order: dict) -> None:
    """Where a running sync is, for the card: how many of how many, and which
    one now (a clinic's name for the document, or the order number)."""
    with transaction(settings) as connection:
        connection.execute(
            "UPDATE lab_accounts SET sync_summary_json=? WHERE user_id=? AND provider=? AND sync_state='running'",
            (json.dumps({**summary, "current": str(order.get("packet") or order["order_id"])[:200]},
                        ensure_ascii=False), account_user_id, key),
        )


def _record_failure(settings, account_user_id, owner, key, person, order, error_key) -> None:
    with transaction(settings) as connection:
        previous = connection.execute(
            "SELECT state FROM lab_orders WHERE owner_user_id=? AND provider=? AND order_id=?",
            (owner, key, order["order_id"]),
        ).fetchone()
        state = "accepted" if previous is not None and previous["state"] == "accepted" else "failed"
        _upsert_order(connection, owner, key, person["id"], order, account_user_id=account_user_id,
                      state=state, error_key=error_key)


def sync(settings: Settings, user_id: str, key: str, *, secret: str | None = None, phone: str | None = None,
         person: dict | None = None, inline: bool = False, claimed: bool = False) -> dict:
    """Bring every linked person's orders at one lab into the records their
    links name — the holder's own straight away, another user's held until
    they accept.  Idempotent: a second run with nothing new changes nothing.
    Errors are recorded per order; only a refused credential stops the run
    (every later call would fail too).  ``person`` (CLI use) syncs that one
    lab person into the holder's own record, without a stored link."""
    summary: dict[str, object] = {
        "provider": key, "orders": 0, "total": 0, "imported": 0, "reported": 0, "linked": 0, "already": 0, "pending": 0,
        "unavailable": 0, "failed": 0, "removed": 0, "changed": 0, "awaiting": 0, "people": 0,
        "crosscheck": dict.fromkeys((*CLASSES, "flag"), 0),
    }
    with transaction(settings) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO lab_accounts(user_id, provider, updated_at) VALUES (?, ?, ?)", (user_id, key, utc_now()))
    if not claimed and not _claim_run(settings, user_id, key):
        raise LabSyncError(ERROR_RUNNING)
    try:
        _sync_account(settings, user_id, key, secret, phone, person, inline, summary)
    except LabSyncError as exc:
        _finish_run(settings, user_id, key, "failed", exc.key, summary)
        raise
    except Exception:
        logger.exception("labsync: %s sync failed", key)
        _finish_run(settings, user_id, key, "failed", ERROR_INGEST, summary)
        raise
    _finish_run(settings, user_id, key, "done", None, summary)
    return summary


def _sync_account(settings: Settings, user_id: str, key: str, secret: str | None, phone: str | None,
                  person: dict | None, inline: bool, summary: dict) -> None:
    if not active(settings, key):
        raise LabSyncError(ERROR_OFF)
    row = account(settings, user_id, key)
    stored_secret = row["secret"] if row else ""
    secret = secret or stored_secret
    phone = phone or (row["phone"] if row else "")
    with connect(settings) as connection:
        links = [] if person is not None else connection.execute(
            """SELECT * FROM lab_person_links WHERE account_user_id=? AND provider=? AND consent<>'refused'
                ORDER BY target_user_id<>account_user_id, created_at""",
            (user_id, key),
        ).fetchall()
        patients = {str(link["target_user_id"]): _patient(connection, str(link["target_user_id"]))
                    for link in links}
        own_patient = _patient(connection, user_id)
    _require_ready(user_id, key, row, secret, phone, stored_secret, person, links, own_patient)
    client = _client(settings, key, secret, phone)
    try:
        work = [(None, person, own_patient)] if person is not None else [
            (link, json.loads(link["remote_person_json"]), patients[str(link["target_user_id"])])
            for link in links
        ]
        for link, lab_person, patient in work:
            if patient is None:
                # That record has no profile (deleted since the link was
                # made); nothing can be imported into it.
                continue
            summary["people"] += 1
            _sync_link(settings, user_id, key, client, link, lab_person, str(patient["id"]), summary, inline)
    finally:
        if secret == stored_secret:
            _store_rolled_secret(settings, user_id, key, stored_secret, client)
    with connect(settings) as connection:
        for tracked in connection.execute(
            """SELECT crosscheck_json FROM lab_orders WHERE owner_user_id=? AND provider=?
                AND crosscheck_json IS NOT NULL""",
            (user_id, key),
        ):
            for cls, count in json.loads(tracked[0])["counts"].items():
                summary["crosscheck"][cls] = summary["crosscheck"].get(cls, 0) + int(count)


def _require_ready(user_id: str, key: str, row, secret: str, phone: str, stored_secret: str,
                   person: dict | None, links: list, own_patient) -> None:
    """Refuse a run that cannot work: no credential, nobody linked, an expired
    credential, or a link into a record that has no profile."""
    if not secret or (key == eskulab.KEY and not phone):
        raise LabSyncError(ERROR_NO_CREDENTIALS)
    if person is None and not links:
        raise LabSyncError("labsync.error_no_patient")
    if _expired(row["secret_expires_at"] if row and secret == stored_secret else None) or (
            key == eskulab.KEY and _expired(eskulab.token_expiry(secret))):
        raise LabSyncError(ERROR_EXPIRED)
    if own_patient is None and (person is not None or any(
            str(link["target_user_id"]) == user_id for link in links)):
        raise LabSyncError(ERROR_NO_PROFILE)


def start_sync(settings: Settings, user_id: str, key: str) -> None:
    """Claim the run now (so a double press says "already running") and do
    the work on a background thread; the profile shows its progress."""
    if not _claim_run(settings, user_id, key):
        raise LabSyncError(ERROR_RUNNING)

    def run() -> None:
        started = time.monotonic()
        try:
            log_run(logger, f"labsync {key}", started, sync(settings, user_id, key, claimed=True))
        except LabSyncError as exc:
            # Recorded on the account row by sync(); the key is a catalog id.
            logger.warning("labsync %s run failed: %s", key, exc.key)
        except Exception:  # noqa: BLE001
            logger.exception("labsync: background sync failed")

    threading.Thread(target=run, name=f"anamna-labsync-{key}", daemon=True).start()


# --- what the profile shows -------------------------------------------------------


def _mask_phone(phone: str) -> str:
    return phone[:4] + "•" * max(0, len(phone) - 6) + phone[-2:] if len(phone) > 6 else ""


def profile_cards(settings: Settings, user) -> list[dict]:
    """One Connections-tab card per enabled provider; none for a guest link or
    an API credential, which are not the account holder in person."""
    if not user or user.get("token_kind") in {"guest", "api"}:
        return []
    return [_card(settings, user["id"], key) for key in active_providers(settings)]


def profile_card(settings: Settings, user, key: str) -> dict | None:
    """One provider's card (the in-place progress update), or None."""
    if not user or user.get("token_kind") in {"guest", "api"} or key not in PROVIDERS or not active(settings, key):
        return None
    return _card(settings, user["id"], key)


def _name_unlisted_targets(connection, links: dict, names: dict) -> None:
    """A linked user who is no longer family (share removed) still shows by
    name, so the holder can see and undo the link."""
    for link in links.values():
        target = str(link["target_user_id"])
        if target not in names:
            found = connection.execute("SELECT display_name FROM users WHERE id=?", (target,)).fetchone()
            names[target] = str(found["display_name"]) if found else "-"


def _held_states(connection, links: dict, user_id: str, key: str) -> dict[str, dict[str, int]]:
    """Per lab person linked to another user: how many orders sit in each state."""
    held: dict[str, dict[str, int]] = {}
    for remote_id, link in links.items():
        if str(link["target_user_id"]) == user_id:
            continue
        held[remote_id] = dict(connection.execute(
            """SELECT state, COUNT(*) FROM lab_orders WHERE owner_user_id=? AND account_user_id=? AND provider=?
                AND remote_person_id=? GROUP BY state""",
            (str(link["target_user_id"]), user_id, key, remote_id),
        ).fetchall())
    return held


def _person_label(person: dict) -> str:
    return " ".join(str(person.get(part) or "").strip() for part in ("lastname", "firstname", "middlename")).strip()


def _card_person(person: dict, link, candidates: list[dict], fed: dict, names: dict, held: dict,
                 user_id: str) -> dict:
    """``fed``: record id -> the lab people already linked to it on this account."""
    options = [
        {"id": "self" if c["self"] else c["id"], "user_id": c["id"], "name": c["name"], "self": c["self"],
         "has_profile": c["patient"] is not None, "match": demographics(person, c["patient"]),
         "also": [label for remote_id, label in fed.get(c["id"], []) if remote_id != person["id"]]}
        for c in candidates
    ]
    target = str(link["target_user_id"]) if link else None
    suggested = target or next((o["user_id"] for o in options if o["match"]["ok"] and o["has_profile"]), None)
    if not suggested:
        selected = ""
    else:
        selected = "self" if suggested == user_id else suggested
    return {
        **person,
        # What tells two profiles with the same name apart: the lab's own
        # number for the person (Synevo's patient code, EskuLab's patient id).
        "lab_id": next((str(m) for m in reversed(person.get("match_ids") or []) if str(m).isdigit()), str(person["id"])),
        "options": options,
        "selected": selected,
        "link": None if link is None else {
            "target": target, "self": target == user_id, "name": names.get(target, "-"),
            "consent": str(link["consent"]), "mismatch_confirmed": bool(link["mismatch_confirmed"]),
            "match": demographics(person, next((c["patient"] for c in candidates if c["id"] == target), None)),
            "states": held.get(person["id"], {}),
        },
    }


def _card(settings: Settings, user_id: str, key: str) -> dict:
    row = account(settings, user_id, key)
    candidates = link_candidates(settings, user_id)
    names = {c["id"]: c["name"] for c in candidates}
    with connect(settings) as connection:
        patient = _patient(connection, user_id)
        links = {str(link["remote_person_id"]): link for link in connection.execute(
            "SELECT * FROM lab_person_links WHERE account_user_id=? AND provider=? ORDER BY created_at",
            (user_id, key))}
        _name_unlisted_targets(connection, links, names)
        orders = connection.execute(
            """SELECT * FROM lab_orders WHERE owner_user_id=? AND provider=? AND COALESCE(account_user_id, owner_user_id)=?
                ORDER BY ordered_at IS NOT NULL, ordered_at DESC, order_id DESC""",
            (user_id, key, user_id),
        ).fetchall()
        # Live, not the counts stored at sync time: a re-read or a correction
        # since then changes the answer, and a stale number misleads.  One
        # batch for every order (PERF-13).
        live = check_orders(connection, user_id, [order for order in orders if order["document_id"]])
        held_ids = sorted({str(order["document_id"]) for order in orders if order["document_id"]})
        titles = {str(row[0]): str(row[1] or "") for row in connection.execute(
            f"SELECT id, title FROM documents WHERE owner_user_id=? AND id IN ({','.join('?' * len(held_ids))})",
            (user_id, *held_ids))} if held_ids else {}
        records = _lab_records(connection, held_ids)
        held = _held_states(connection, links, user_id, key)
    listed = _people(row)
    people = listed + [json.loads(link["remote_person_json"]) for remote_id, link in links.items()
                       if remote_id not in {person["id"] for person in listed}]
    fed: dict[str, list[tuple[str, str]]] = {}
    for remote_id, link in links.items():
        if link["consent"] != "refused":
            fed.setdefault(str(link["target_user_id"]), []).append(
                (remote_id, _person_label(json.loads(link["remote_person_json"]))))
    persons = [_card_person(person, links.get(person["id"]), candidates, fed, names, held, user_id)
               for person in people]
    secret = str(row["secret"]) if row else ""
    return {
        "key": key,
        "name": provider(key).NAME,
        "messages": getattr(provider(key), "MESSAGES", key),
        "sign_in": getattr(provider(key), "SIGN_IN", "paste"),
        "url": provider_settings(settings, key)["url"],
        "connected": bool(secret),
        "secret_tail": secret[-6:] if secret else "",
        "expires_at": row["secret_expires_at"] if row else None,
        "expired": _expired(row["secret_expires_at"]) if row else False,
        "phone": _mask_phone(str(row["phone"])) if secret else "",
        "has_profile": patient is not None,
        "persons": persons,
        "linked": sum(1 for p in persons if p["link"] and p["link"]["consent"] != "refused"),
        "family": len(candidates) > 1,
        **_card_sync_fields(row),
        "orders": [_card_order(order, records, live, titles) for order in orders],
    }


_SYNC_STATUS_COLUMNS = ("sync_state", "sync_finished_at")


def _card_sync_fields(row) -> dict:
    """Where the last sync stands, from the account row (idle without one)."""
    if not row:
        return {"sync_state": "idle", "sync_detail": None, "sync_finished_at": None, "summary": None}
    return {
        **{column: row[column] for column in _SYNC_STATUS_COLUMNS},
        "sync_detail": row["sync_detail_key"] if row["sync_detail_key"] in ERROR_KEYS else None,
        "summary": json.loads(row["sync_summary_json"]) if row["sync_summary_json"] else None,
    }


def _card_order(order, records: set, live: dict, titles: dict) -> dict:
    return {
        "order_id": order["order_id"],
        "ordered_at": order["ordered_at"],
        "lab_status": order["lab_status"],
        "ready": int(order["ready"]),
        "total": int(order["total"]),
        # In the record as the lab's own values, with no PDF: said as
        # such, never as "the sync downloaded the official PDF".
        "state": "reported" if str(order["document_id"] or "") in records else order["state"],
        "document_id": order["document_id"],
        "error_key": order["error_key"] if order["error_key"] in ERROR_KEYS else None,
        "changed_at": order["rows_changed_at"],
        "counts": (live.get(_order_key(order)) or {}).get("counts"),
        "has_rows": bool(order["rows_json"] and json.loads(order["rows_json"])),
        "title": titles.get(str(order["document_id"])),
    }


__all__ = [
    "LINK_KEYS", "LabSyncError", "PROVIDERS", "active", "active_providers", "check_account", "cross_check",
    "decide_orders", "document_check", "forget", "inbox", "inbox_count", "link_candidates", "link_person",
    "observation_classes", "profile_card", "profile_cards", "provider_settings", "recheck", "save_credentials",
    "save_provider_settings", "set_consent", "start_sync", "sync", "unlink_person", "verify_matches",
]

