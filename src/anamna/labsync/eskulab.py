"""EskuLab (https://esculab.com) customer API, observed 2026-11-04.

The Next.js site authenticates every call with two headers and no cookies:
``Authorization: Bearer <accessKey cookie, URL-decoded>`` (a JWT, ~1 year) and
``AccessPhone: <localStorage.activePatientPhone>``.

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
import urllib.parse
from datetime import UTC, datetime

from . import common
from .common import ERROR_REPLY, LabSyncError, digits, iso_day, lab_row, parse_norm, sex_of

KEY = "eskulab"
NAME = "EskuLab"
VENDOR = "EskuLab"
DEFAULT_URL = "https://esculab.com"

ERROR_CREDENTIALS = "labsync.error_credentials"
_TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/=-]{16,4096}")
_PHONE_RE = re.compile(r"\+?\d{9,15}")


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


def parse_credentials(form: dict[str, str]) -> dict[str, str]:
    """The console snippet's JSON in one field, or token and phone in two."""
    blob = str(form.get("credentials_json") or "").strip()
    token, phone = str(form.get("token") or ""), str(form.get("phone") or "")
    if blob:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            raise LabSyncError(ERROR_CREDENTIALS) from None
        if not isinstance(data, dict):
            raise LabSyncError(ERROR_CREDENTIALS)
        token = str(data.get("token") or data.get("accessKey") or "")
        phone = str(data.get("phone") or data.get("activePatientPhone") or "")
    token = urllib.parse.unquote(token.strip())
    if token.casefold().startswith("bearer "):
        token = token[7:].strip()
    phone = re.sub(r"[\s().-]", "", phone.strip().strip('"'))
    if not _TOKEN_RE.fullmatch(token) or not _PHONE_RE.fullmatch(phone):
        raise LabSyncError(ERROR_CREDENTIALS)
    return {"secret": token, "phone": phone, "expires_at": token_expiry(token)}


class Client:
    def __init__(self, base_url: str, secret: str, phone: str):
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
