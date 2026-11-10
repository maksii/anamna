"""Esculab (https://esculab.com) customer API, observed 2026-11-04 (website)
and 2026-11-08 (Android app 3.0.6, ``com.mak.elab``, static analysis of its
Hermes bundle).

The app talks to ``https://cabinet-api.mz-group.com.ua``; esculab.com fronts
the same backend (one stored token answers ``findPatientSite`` on both, and
``/api/auth/*`` answers identically on both), so the configured address
serves sign-in and results alike.

Sign-in, as the app's SignInFlow and ConfirmFlow screens do it (phone and a
texted code, ``SIGN_IN = "sms"``; there is no password):

1. ``POST /api/auth/authorise`` ``{"phone": "+380XXXXXXXXX", "uuid": <uuid4>}``:
   the app builds the phone as ``+380`` and 9 digits and makes a fresh uuid
   per attempt; Esculab texts a 4-digit code.  The app ignores the reply.
2. ``POST /api/auth/application/accept`` ``{"code", "uuid"}`` with
   ``AccessPhone: <phone>`` → one entry per role on the number,
   ``{clientType: "PATIENT"|"DOCTOR", tokens: {token, exist, ...}}``.  The
   app keeps the PATIENT entry; none is its "User not found", and
   ``exist: false`` sends it to create a patient profile first.  A wrong code
   is an HTTP 4xx with Spring's error JSON (``status``).  The older
   ``POST /api/auth/accept`` (``{token, exist}``, patient only) is exported
   but not called by the code screen; its reply shape is read too.

The token is a JWT valid about a year (``exp``) with no renewal token: when
it ends, the person signs in again.  Nothing else is stored.

Every signed-in call carries two headers and no cookies:
``Authorization: Bearer <token>`` and ``AccessPhone: <phone>``.

* ``POST /api/customers/findPatientSite`` ``{"phone"}`` → persons on the account
* ``GET /api/customers/v2/orders`` → every order of every person
* ``GET /api/customers/getOrdersResult/{orderId}/{patientId}`` → result rows
* ``GET /api/results/getResults/{patientId}/{orderId}`` → the official PDF
  (person first: the reverse answers HTTP 500)
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import UTC, datetime

# expert as a module: it imports token_expiry from here.
from . import common, expert
from .common import ERROR_REPLY, LabSyncError, digits, iso_day, lab_row, parse_norm, sex_of

KEY = "esculab"
NAME = "Esculab"
VENDOR = "Esculab"
DEFAULT_URL = "https://esculab.com"
#: Phone and a texted code, no password (labsync._sign_in).
SIGN_IN = "sms"

_CODE_LENGTH = 4
_CODE_RE = re.compile(r"\d{4}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/=-]{16,4096}")
_NO_PATIENT = "labsync.esculab_error_no_patient"
_WRONG_CODE = "labsync.password_error_code"


def token_expiry(token: str) -> str | None:
    """The JWT ``exp`` claim as an ISO timestamp, read without verifying the
    signature — only to warn ahead of time, never to trust the token."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
        exp = claims.get("exp") if isinstance(claims, dict) else None
        if isinstance(exp, (int, float)) and not isinstance(exp, bool):
            return datetime.fromtimestamp(exp, UTC).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError, UnicodeError):
        return None
    return None


def _post(base_url: str, path: str, payload: dict, refused: str, headers: dict | None = None) -> object:
    """A sign-in call; a 4xx is the server saying no (``refused``)."""
    try:
        reply, _ = common.call("POST", base_url.rstrip("/") + path, headers=headers or {}, payload=payload)
    except LabSyncError as exc:
        if exc.status == 429:
            raise LabSyncError("labsync.password_error_throttled", 429) from None
        if exc.status and 400 <= exc.status < 500:
            raise LabSyncError(refused, exc.status) from None
        raise
    return reply


def start_sign_in(base_url: str, phone: object, password: object, state: dict) -> dict:
    """Ask Esculab to text a code; ``password`` and ``state`` are not part of
    this flow (no password, no device registration)."""
    phone = expert.normalize_phone(phone)
    session = str(uuid.uuid4())
    _post(base_url, "/api/auth/authorise", {"phone": phone, "uuid": session}, "labsync.sms_error_phone")
    return {"challenge": {"token": session, "phone_masked": phone[:4] + "•" * 7 + phone[-2:],
                          "code_length": _CODE_LENGTH, "expires_in": 300}, "phone": phone}


def _raise_if_refused(reply: object) -> None:
    """The accept reply's own refusals: a wrong code, or a number with no patient."""
    if isinstance(reply, dict):
        status = reply.get("status")
        if (isinstance(status, int) and status >= 400) or reply.get("message") == "Error verifying code":
            raise LabSyncError(_WRONG_CODE)
        if reply.get("message") == "User not found":
            raise LabSyncError(_NO_PATIENT)


def _patient_of(entries: list) -> dict:
    """The PATIENT entry of a per-role list, its ``tokens`` folded in."""
    entry = next((item for item in entries if isinstance(item, dict)
                  and str(item.get("clientType") or "").upper() == "PATIENT"), None)
    if entry is None:  # a doctor-only number, or nobody: the app's "User not found"
        raise LabSyncError(_NO_PATIENT)
    inner = entry.get("tokens")
    return {**entry, **inner} if isinstance(inner, dict) else entry


def _patient_entry(reply: object) -> dict:
    """The PATIENT entry of the accept reply, its ``tokens`` folded in."""
    _raise_if_refused(reply)
    if isinstance(reply, list):
        entries = reply
    elif isinstance(reply, dict):
        entries = reply.get("tokens")
    else:
        entries = None
    if isinstance(entries, list):
        return _patient_of(entries)
    if isinstance(reply, dict) and reply.get("token"):  # /api/auth/accept: {token, exist}
        return reply
    raise LabSyncError("labsync.error_reply")


def verify_code(base_url: str, challenge: dict, code: object, state: dict, phone: str) -> dict:
    code = re.sub(r"\s", "", str(code or ""))
    if not _CODE_RE.fullmatch(code):
        raise LabSyncError(_WRONG_CODE)
    reply = _post(base_url, "/api/auth/application/accept", {"code": code, "uuid": challenge["token"]},
                  _WRONG_CODE, headers={"AccessPhone": phone})
    entry = _patient_entry(reply)
    if entry.get("exist") is False:
        raise LabSyncError(_NO_PATIENT)
    token = str(entry.get("token") or "")
    if not _TOKEN_RE.fullmatch(token):
        raise LabSyncError("labsync.error_reply")
    return {"secret": token, "refresh_secret": "", "phone": phone, "expires_at": token_expiry(token)}


class Client:
    def __init__(self, base_url: str, secret: str, phone: str, refresh: str | None = None):
        # ``refresh`` is what labsync._client hands every sign-in provider;
        # Esculab issues no renewal token, so there is nothing in it.
        self.base_url, self.secret, self.phone = base_url.rstrip("/"), secret, phone

    def _get(self, path: str, *, method: str = "GET", payload=None, want: str = "json"):
        reply, _ = common.call(method, self.base_url + path, payload=payload, want=want,
                               headers={"Authorization": f"Bearer {self.secret}", "AccessPhone": self.phone})
        return reply

    def check(self) -> tuple[list[dict], str | None]:
        reply = self._get("/api/customers/findPatientSite", method="POST", payload={"phone": self.phone})
        if not isinstance(reply, list):
            raise LabSyncError(ERROR_REPLY)
        return [self._identity(person) for person in reply if isinstance(person, dict)], token_expiry(self.secret)

    @staticmethod
    def _identity(person: dict) -> dict:
        """Only what identifies a person.  The reply also carries login,
        phone, e-mail and password fields; they are dropped here."""
        return {
            "id": digits(person.get("id")),
            "match_ids": [digits(person.get("id"))],
            "firstname": str(person.get("firstname") or "")[:80],
            "lastname": str(person.get("lastname") or "")[:80],
            "middlename": str(person.get("fathername") or "")[:80],
            "birthday": iso_day(person.get("birthday")),
            "sex": sex_of(person.get("sex") or person.get("gender")),
        }

    def orders(self, person: dict) -> list[dict]:
        reply = self._get("/api/customers/v2/orders")
        if not isinstance(reply, list):
            raise LabSyncError(ERROR_REPLY)
        wanted = set(person.get("match_ids") or [person["id"]])
        return [
            self._order_entry(order)
            for order in reply
            if isinstance(order, dict) and not order.get("deleted")
            and str((order.get("patient") or {}).get("id")) in wanted
        ]

    @staticmethod
    def _order_entry(order: dict) -> dict:
        status = str((order.get("status") or {}).get("status") or "")
        ready, total = int(order.get("ready") or 0), int(order.get("total") or 0)
        day = iso_day(order.get("dt"))
        return {
            "order_id": digits(order.get("orderId")),
            "remote_ref": None,
            "ordered_at": str(order.get("dt") or "")[:16] or None,
            "dates": [day] if day else [],
            "lab_status": status[:40] or None,
            "ready": ready,
            "total": total,
            "complete": status == "DONE" and 0 < total <= ready,
            "unavailable": None,
            "rows": None,
        }

    def rows(self, order: dict, person: dict) -> list[dict]:
        reply = self._get(f"/api/customers/getOrdersResult/{digits(order['order_id'])}/{digits(person['id'])}")
        if not isinstance(reply, list):
            raise LabSyncError(ERROR_REPLY)
        rows = []
        for row in reply:
            if not isinstance(row, dict):
                continue
            # The site's own page hides these service rows; so does this.
            if "1516" in str(row.get("packet") or "") and str(row.get("idtest")) in {"406", "262"}:
                continue
            rows.append(lab_row(test=row.get("test"), result=row.get("result"), units=row.get("units"),
                                resulttype=row.get("resulttype"), state=row.get("state"),
                                norm=parse_norm(row.get("norm")), packet=row.get("packet"),
                                material=row.get("material"), idtest=row.get("idtest")))
        return rows

    def pdfs(self, order: dict, person: dict) -> list[bytes]:
        return [self._get(f"/api/results/getResults/{digits(person['id'])}/{digits(order['order_id'])}", want="pdf")]
