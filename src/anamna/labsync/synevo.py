"""Synevo (https://www.synevo.ua) customer cabinet API, observed 2026-11-05.

Only the NextAuth session cookie authenticates: ``next-auth.session-token``
(HttpOnly, ~30-day rolling).  A bearer of the session's ``accessToken`` gets
401.  The server may re-issue the cookie in ``Set-Cookie``; the client keeps
the newest value so the stored connection keeps rolling.

* ``GET /api/auth/session`` → ``{user, expires, …}`` (validity and expiry only)
* ``GET /api/cabinet/user-persons`` → persons on the account
* ``POST /api/cabinet/get-orders`` ``{page}`` → paged orders
* ``POST /api/cabinet/get-results`` ``{page}`` → paged result groups, one per
  service, including in-lab ("offline") orders that have no web id
* ``POST /api/order/download-pdf`` ``{orderId: WebOrderId}`` → time-limited
  blob links to the official PDF (``main``) and any extra files
"""

from __future__ import annotations

import re
import urllib.parse

from . import common
from .common import ERROR_REPLY, LabSyncError, digits, iso_day, lab_row, sex_of

KEY = "synevo"
NAME = "Synevo"
VENDOR = "Synevo"
DEFAULT_URL = "https://www.synevo.ua"
COOKIE = "next-auth.session-token"
#: Where Synevo keeps result files.  Downloads go there without cookies, and
#: nowhere else (plus the configured origin itself, for a local test server).
BLOB_HOSTS = frozenset({"synevostatic.blob.core.windows.net"})
MAX_PAGES = 50

_SECRET_RE = re.compile(r"[A-Za-z0-9._~+/=%-]{40,8192}")
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SET_COOKIE_RE = re.compile(r"^\s*(?:__Secure-)?next-auth\.session-token=([^;]*)", re.I)


def parse_credentials(form: dict[str, str]) -> dict[str, str]:
    """The cookie value as copied from DevTools; a pasted ``name=value`` (or a
    whole Cookie header) is accepted too."""
    raw = str(form.get("token") or form.get("credentials_json") or "").strip()
    for part in raw.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name.strip().removeprefix("__Secure-") == COOKIE:
            raw = value.strip()
            break
    raw = raw.strip().strip('"')
    if not _SECRET_RE.fullmatch(raw):
        raise LabSyncError("labsync.error_credentials")
    return {"secret": raw, "phone": "", "expires_at": None}


def _text(regional: object) -> str:
    if isinstance(regional, list):
        for language in ("uk", "en", "ru"):
            for entry in regional:
                if isinstance(entry, dict) and entry.get("Language") == language and entry.get("Value"):
                    return str(entry["Value"])
    return ""


def _person_ids(person: object) -> list[str]:
    if isinstance(person, dict):
        person = person.get("_id")
    text = str(person or "")
    return [text] if _ID_RE.fullmatch(text) else []


def _range_state(in_range: object) -> str:
    """Synevo's InRange is True, False or absent; anything else is no verdict."""
    if in_range is True:
        return "normal"
    return "critical" if in_range is False else ""


class Client:
    def __init__(self, base_url: str, secret: str, phone: str = ""):
        self.base_url, self.secret = base_url.rstrip("/"), secret
        self._results: list[dict] | None = None

    def _cookie(self, person: dict | None) -> str:
        cookie = f"{COOKIE}={self.secret}"
        return cookie + (f"; selectedPatient={person['id']}" if person else "")

    def _call(self, method: str, path: str, *, payload=None, person: dict | None = None):
        reply, cookies = common.call(method, self.base_url + path, payload=payload,
                                     headers={"Cookie": self._cookie(person)})
        for header in cookies:
            match = _SET_COOKIE_RE.match(header)
            if match and _SECRET_RE.fullmatch(match.group(1)):
                self.secret = match.group(1)  # NextAuth rolled the session
        return reply

    def check(self) -> tuple[list[dict], str | None]:
        session = self._call("GET", "/api/auth/session")
        # NextAuth answers {} for no session.  A live one carries `expires` and
        # a `user` that Synevo leaves empty ({}), so testing `user` for
        # truthiness rejected every valid cookie as signed out.
        if not isinstance(session, dict) or not session:
            raise LabSyncError("labsync.error_auth")
        reply = self._call("GET", "/api/cabinet/user-persons")
        if isinstance(reply, dict):
            reply = reply.get("items") or reply.get("persons") or reply.get("data") or []
        if not isinstance(reply, list):
            raise LabSyncError(ERROR_REPLY)
        people = [self._identity(person) for person in reply if isinstance(person, dict) and person.get("ProfileId")]
        for person in people:
            person["account_size"] = len(people)
        expires = str(session.get("expires") or "")[:19] or None
        return people, expires

    @staticmethod
    def _identity(person: dict) -> dict:
        """Only what identifies a person; Phone and Email are dropped here."""
        profile = str(person.get("ProfileId") or "")
        if not _ID_RE.fullmatch(profile):
            raise LabSyncError(ERROR_REPLY)
        ids = [profile, *_person_ids(person.get("PersonId")), *_person_ids(person.get("Person"))]
        return {
            "id": profile,
            "match_ids": list(dict.fromkeys(ids)),
            "firstname": str(person.get("FirstName") or "")[:80],
            "lastname": str(person.get("LastName") or "")[:80],
            "middlename": str(person.get("MiddleName") or "")[:80],
            "birthday": iso_day(person.get("BirthDate")),
            "sex": sex_of(person.get("Gender") or person.get("Sex")),
        }

    def _pages(self, path: str, person: dict) -> list[dict]:
        items: list[dict] = []
        page, pages = 1, 1
        while page <= min(pages, MAX_PAGES):
            reply = self._call("POST", path, payload={"page": page}, person=person)
            if not isinstance(reply, dict) or not isinstance(reply.get("items"), list):
                raise LabSyncError(ERROR_REPLY)
            items += [item for item in reply["items"] if isinstance(item, dict)]
            pages = int(reply.get("pagesCount") or 1)
            page += 1
        return items

    def _mine(self, item: dict, person: dict) -> bool:
        ids = _person_ids(item.get("Person"))
        return bool(set(ids) & set(person.get("match_ids") or [])) or (
            # The person list had one entry and the order names one person:
            # the ids differ only in which of Synevo's handles the order uses.
            person.get("account_size") == 1
        )

    def orders(self, person: dict) -> list[dict]:
        results = [item for item in self._pages("/api/cabinet/get-results", person) if self._mine(item, person)]
        return [
            self._order_entry(order, results)
            for order in self._pages("/api/cabinet/get-orders", person)
            if self._mine(order, person)
        ]

    def _order_entry(self, order: dict, results: list[dict]) -> dict:
        barcode = digits(order.get("Barcode"))
        web = str(order.get("WebOrderId") or "")
        web = web if re.fullmatch(r"\d{1,20}", web) else None
        groups = [item for item in results if str((item.get("Order") or {}).get("Barcode")) == barcode]
        parts = [item for item in order.get("Items") or [] if isinstance(item, dict)]
        ready = sum(1 for item in parts if item.get("IsReady"))
        dates = [iso_day(order.get("ExaminationDate")), iso_day(order.get("OrderDate"))]
        dates += [iso_day(item.get("ReadyAt")) for item in groups]
        if order.get("Esoz"):
            unavailable = "labsync.unavailable_esoz"
        else:
            unavailable = None if web else "labsync.unavailable_offline"
        return {
            "order_id": barcode,
            "remote_ref": web,
            "ordered_at": str(order.get("ExaminationDate") or order.get("OrderDate") or "")[:16].replace("T", " ") or None,
            "dates": sorted({day for day in dates if day}),
            "lab_status": str(order.get("StatusDescr") or "")[:40] or None,
            "ready": ready,
            "total": len(parts),
            "complete": bool(parts) and ready == len(parts),
            "unavailable": unavailable,
            "rows": [row for group in groups for row in self._rows(group)],
        }

    @staticmethod
    def _rows(group: dict) -> list[dict]:
        packet = _text((group.get("Service") or {}).get("NameRegional"))
        rows = []
        for result in group.get("Results") or []:
            if not isinstance(result, dict):
                continue
            name = str(result.get("Name") or "").strip()
            value = "" if result.get("Val") is None else str(result.get("Val"))
            rows.append(lab_row(
                test=name, result=value, units=result.get("Unit"),
                # A label ending in a colon, or a paragraph, is a method note
                # («Методи/Лабораторне обладнання:»), not a measurement; a value
                # pointing at a file («…в додатковому pdf файлі») is the ALEX2
                # panel, whose results arrive as a separate document.
                resulttype="info" if name.endswith(":") or len(value) > 200 or "pdf" in value.casefold() else "",
                state=_range_state(result.get("InRange")),
                norm=[" ".join(line.split()) for line in str(result.get("Range") or "").splitlines()],
                packet=packet, idtest=result.get("ResId"),
            ))
        return rows

    def rows(self, order: dict, _person: dict) -> list[dict]:
        return order["rows"] or []

    def _file_allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        own = urllib.parse.urlsplit(self.base_url)
        if parsed.username or parsed.password:
            return False
        if parsed.scheme == "https" and parsed.hostname in BLOB_HOSTS:
            return True
        return (parsed.scheme, parsed.netloc) == (own.scheme, own.netloc)

    def pdfs(self, order: dict, person: dict) -> list[bytes]:
        if not order.get("remote_ref"):
            raise LabSyncError(order.get("unavailable") or "labsync.unavailable_offline")
        reply = self._call("POST", "/api/order/download-pdf", payload={"orderId": order["remote_ref"]}, person=person)
        results = reply.get("results") if isinstance(reply, dict) and reply.get("res") == "ok" else None
        if not isinstance(results, dict) or not results.get("main"):
            raise LabSyncError("labsync.error_pdf")
        links = [str(results["main"])]
        for extra in results.get("extra") or []:
            if isinstance(extra, dict) and extra.get("file"):
                links.append(str(extra["file"]))
        files = []
        for link in links:
            if not self._file_allowed(link):
                raise LabSyncError("labsync.error_pdf")
            # The link is itself the (time-limited) credential: no cookie.
            body, _ = common.call("GET", link, headers={}, want="pdf")
            files.append(body)
        return files
