"""Expert Hospital (Лікарня «Експерт», experthospital.com.ua) mobile
app API, observed from the Android app ``com.mobile.medexpert`` v1.6.10 build
96 on 2026-11-05 (static analysis only; no live sign-in).

The lab has no web cabinet.  The Flutter app talks JSON to its own backend
("MedExpert Backend", FastAPI-style ``{"detail": …}`` errors), which fronts the
hospital information system MedEir.  The base URL comes from the app's bundled
``.env.prod`` (``MEDEXPERT_API_BASE_URL``); every path starts ``/api/v1``.
Static headers are only ``Accept``/``Content-Type: application/json`` — no API
key, client id or tenant header — plus ``Authorization: Bearer <access>``.

Sign-in (phone + password, the app's own flow):

* ``POST /api/v1/auth/login`` ``{phone, password, device_id, device_name,
  platform, trusted_device_token}`` → tokens ``{access_token, refresh_token,
  token_type, trusted_device_token, …}`` or, on a device the account has not
  trusted yet, ``{two_factor_required: true, challenge_token, phone_masked,
  expires_in, code_length, method}``.  The phone is ``+380XXXXXXXXX``: the app
  masks the field as ``+38# (##) ### ## ##`` and sends ``"+" + digits``.
  ``device_id`` is a random UUID kept per installation.
* ``POST /api/v1/auth/2fa/verify`` ``{challenge_token, code, device_id,
  device_name, platform, fcm_token}`` → the same token reply; its
  ``trusted_device_token`` spares the SMS on the next sign-in.
* ``POST /api/v1/auth/refresh`` ``{refresh_token}`` → ``{access_token,
  refresh_token, token_type}``.  The app refreshes on HTTP 401 and sends the
  person back to sign-in when the refresh itself is refused.  403 carries a
  reason (``medeir_not_linked``, ``profile_incomplete``, ``phone_required``)
  that only the app can resolve.

Records (``family_member_id`` selects a relative; omitted for the holder):

* ``GET /api/v1/profile`` → ``{profile: {id, first_name, last_name,
  middle_name, dob, gender, is_linked_to_medeir, …}, phone, email, …}``
* ``GET /api/v1/profile/family`` → ``{items: [{id, profile_id, first_name,
  last_name, middle_name, dob, gender, relationship_type,
  is_linked_to_medeir, …}], total}``; ``id`` is the ``family_member_id``.
  The app loads no results for a person not linked to MedEir.
* ``GET /api/v1/medical/analyses`` → ``{items: [Analysis], total, skip, limit,
  has_more}``; ``Analysis`` = ``{id, name, category, status, status_code,
  date, result_date, has_file, has_abnormal_results, indicators?}``
* ``GET /api/v1/medical/analyses/{id}`` → one ``Analysis`` whose
  ``indicators`` are ``[{id, name, value, unit, reference_min, reference_max,
  reference_text, is_abnormal, note}]`` (all strings but the flag)
* ``GET /api/v1/medical/analyses/{id}/file`` → the PDF bytes
* ``GET /api/v1/medical/conclusions`` → the same page shape; each item
  names a visit's conclusion (``{id, name, date, doctor_name, speciality,
  has_file, files?}``).  ``GET …/conclusions/{id}`` adds what the doctor
  wrote: ``complaints, anamnesis, examination, diagnosis, diagnosis_codes,
  recommendations, medications [{name, reception_quantity,
  reception_frequency, take_from, take_to, quantity_in_recipe}]``.  Most
  carry no file; an attached one is a Word document (live, 2026-11-09).
* ``GET /api/v1/medical/research`` → examinations (X-ray, ultrasound):
  ``{id, research_type, body_part, date, research_date, doctor_name, status,
  conclusion, has_file, is_dicom}``; ``conclusion`` is the radiologist's
  typed report, and an X-ray's file is the radiograph (JPEG), not a report.
* ``GET /api/v1/medical/{conclusions|research}/{id}/file`` → the file as it
  can be opened (PDF, JPEG, .docx); ``…/files`` lists ``{file_id, source,
  name, size, mime_type}`` (``file_id: 0, source: "inline"`` is the app's
  own HTML view), ``…/files/{file_id}`` → one of several.

The three lists are the app's «Мої результати» (``medical_models.dart``).
The first sync read only analyses, so a visit's conclusion, its X-ray report
and its ultrasound never arrived.

Not a white-label platform: one backend, hard-coded Expert Hospital links, no
tenant or organisation parameter anywhere in the request models.  The base URL
is configuration all the same, so a second lab on this backend is one
:func:`lab` entry in ``labsync.PROVIDERS``; a different mobile-only vendor is a
new module with the same ``SIGN_IN = "password"`` interface.
"""

from __future__ import annotations

import json
import re
import types
from datetime import date

from . import common, visit_pdf
from .common import ERROR_REPLY, LabSyncError, digits, iso_day, lab_row, sex_of
from .esculab import token_expiry

KEY = "expert"
NAME = "Expert Hospital"
#: What the PDF classifier names these reports (ingest/classifier.py), so old
#: uploads are recognised by content.
VENDOR = "Expert Hospital"
DEFAULT_URL = "https://api-medexpert.experthospital.in.ua"
#: The person types phone and password once; tokens are stored, not those.
SIGN_IN = "password"
#: What the lab's device list shows for this connection.  The backend expects
#: the app's own platform values, so the platform is the app's.
DEVICE_NAME = "Anamna"
PLATFORM = "android"

_TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/=-]{16,4096}")
_CODE_RE = re.compile(r"\d{4,8}")


def normalize_phone(raw: object) -> str:
    """``+380XXXXXXXXX`` from what a person types: with or without +38, the
    leading 0, spaces or brackets."""
    number = re.sub(r"\D", "", str(raw or ""))
    if len(number) == 9:
        number = "380" + number
    elif len(number) == 10 and number.startswith("0"):
        number = "38" + number
    if not re.fullmatch(r"380\d{9}", number):
        raise LabSyncError("labsync.password_error_phone")
    return "+" + number


def _post(base_url: str, path: str, payload: dict, refused: str) -> dict:
    try:
        reply, _ = common.call("POST", base_url.rstrip("/") + path, headers={}, payload=payload)
    except LabSyncError as exc:
        if exc.status in (400, 401, 403, 404, 422):
            raise LabSyncError(refused, exc.status) from None
        if exc.status == 429:
            raise LabSyncError("labsync.password_error_throttled", 429) from None
        raise
    if not isinstance(reply, dict):
        raise LabSyncError(ERROR_REPLY)
    return reply


def _device(state: dict) -> dict:
    return {"device_id": state["device_id"], "device_name": DEVICE_NAME, "platform": PLATFORM}


def _credentials(reply: dict, state: dict, phone: str) -> dict:
    access, refresh = str(reply.get("access_token") or ""), str(reply.get("refresh_token") or "")
    if not _TOKEN_RE.fullmatch(access) or not _TOKEN_RE.fullmatch(refresh):
        raise LabSyncError(ERROR_REPLY)
    trusted = str(reply.get("trusted_device_token") or "") or state.get("trusted")
    kept = {"refresh": refresh, "device_id": state["device_id"], "trusted": trusted}
    return {"secret": access, "refresh_secret": json.dumps(kept), "phone": phone,
            "expires_at": token_expiry(refresh)}


def start_sign_in(base_url: str, phone: object, password: object, state: dict) -> dict:
    """Credentials, or ``{"challenge": …}`` when the lab texts a code first.
    ``state`` holds this connection's ``device_id`` and any ``trusted`` token."""
    phone = normalize_phone(phone)
    password = str(password or "")
    if not password or len(password) > 200:
        raise LabSyncError("labsync.password_error_invalid")
    reply = _post(base_url, "/api/v1/auth/login",
                  {"phone": phone, "password": password, **_device(state),
                   "trusted_device_token": state.get("trusted")},
                  "labsync.password_error_invalid")
    if reply.get("two_factor_required"):
        token = str(reply.get("challenge_token") or "")
        if not _TOKEN_RE.fullmatch(token):
            raise LabSyncError(ERROR_REPLY)
        length = reply.get("code_length")
        return {"challenge": {
            "token": token,
            "phone_masked": str(reply.get("phone_masked") or "")[:40],
            "code_length": length if isinstance(length, int) and 3 < length < 10 else None,
            "expires_in": reply.get("expires_in") if isinstance(reply.get("expires_in"), int) else 300,
        }, "phone": phone}
    return _credentials(reply, state, phone)


def verify_code(base_url: str, challenge: dict, code: object, state: dict, phone: str) -> dict:
    code = re.sub(r"\s", "", str(code or ""))
    if not _CODE_RE.fullmatch(code):
        raise LabSyncError("labsync.password_error_code")
    reply = _post(base_url, "/api/v1/auth/2fa/verify",
                  {"challenge_token": challenge["token"], "code": code, **_device(state), "fcm_token": None},
                  "labsync.password_error_code")
    return _credentials(reply, state, phone)


def _birthday(value: object) -> str:
    text = str(value or "")
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text[:10])
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            return ""
    return iso_day(text)


#: The hospital system prints every number with six decimals («5.380000»,
#: «Від 0.000000 до 2.590000»); the PDF prints «5.38».  Trailing zeros go, so
#: the value reads like the report and the cross-check compares like with like.
#: The first digit is written out so a substitution enters a run of digits only
#: by consuming one; the rest of the run is taken whole, a separator follows it.
_PADDED = re.compile(r"(?<![\d.,])(\d\d*+)[.,](\d+)(?!\d)")


def _unpad(match: re.Match) -> str:
    fraction = match[2].rstrip("0")
    if fraction == match[2]:
        return match[0]  # no trailing zero: already as the PDF prints it
    return match[1] + ("." + fraction if fraction else "")


def _trim(text: str) -> str:
    return _PADDED.sub(_unpad, text)


def _indicator_state(value: str, abnormal: object) -> str:
    if not value:
        return ""
    if abnormal is True:
        return "critical"
    return "normal" if abnormal is False else ""


def _norm(indicator: dict) -> list[str]:
    """The reference as the app prints it: «min - max», «≥ min», «≤ max», or
    the lab's own text."""
    text = _trim(" ".join(str(indicator.get("reference_text") or "").split()))
    low, high = (_trim(" ".join(str(indicator.get(key) or "").split())) for key in ("reference_min", "reference_max"))
    if text:
        return [text]
    if low and high:
        return [f"{low} - {high}"]
    if low:
        return [f"≥ {low}"]
    return [f"≤ {high}"] if high else []


class Client:
    def __init__(self, base_url: str, secret: str, phone: str = "", refresh: str = ""):
        self.base_url, self.secret, self.phone = base_url.rstrip("/"), secret, phone
        #: JSON: the refresh token, this connection's device id and trusted
        #: device token.  Rewritten when the lab rotates the refresh token.
        self.refresh_secret = refresh

    def _state(self) -> dict:
        try:
            state = json.loads(self.refresh_secret or "{}")
        except json.JSONDecodeError:
            return {}
        return state if isinstance(state, dict) else {}

    def _refresh(self) -> None:
        state = self._state()
        if not state.get("refresh"):
            raise LabSyncError("labsync.error_auth", 401)
        reply = _post(self.base_url, "/api/v1/auth/refresh", {"refresh_token": state["refresh"]}, "labsync.error_auth")
        # A reply without a new refresh token keeps the old one working.
        fresh = _credentials({**reply, "refresh_token": reply.get("refresh_token") or state["refresh"],
                              "trusted_device_token": None}, state, self.phone)
        self.secret, self.refresh_secret = fresh["secret"], fresh["refresh_secret"]

    def _get(self, path: str, person: dict | None = None, *, want: str = "json", again: bool = True,
             skip: int = 0):
        member = (person or {}).get("family_member_id")
        params = {"family_member_id": digits(member)} if member is not None else {}
        if skip:
            params["skip"] = skip
        query = "?" + "&".join(f"{name}={value}" for name, value in params.items()) if params else ""
        try:
            reply, _ = common.call("GET", self.base_url + path + query, want=want,
                                   headers={"Authorization": f"Bearer {self.secret}"})
            return reply
        except LabSyncError as exc:
            if exc.status == 401 and again:  # the access token lapsed: as the app does, refresh once
                self._refresh()
                return self._get(path, person, want=want, again=False, skip=skip)
            if exc.status == 403:  # not linked to MedEir, profile or phone missing: fixed in the app
                raise LabSyncError("labsync.expert_error_forbidden", 403) from None
            raise

    def check(self) -> tuple[list[dict], str | None]:
        reply = self._get("/api/v1/profile")
        own = reply.get("profile") if isinstance(reply, dict) else None
        family = self._get("/api/v1/profile/family")
        family = family.get("items") if isinstance(family, dict) else None
        if not isinstance(own, dict) or not isinstance(family, list):
            raise LabSyncError(ERROR_REPLY)
        people = [self._identity(own, None)]
        people += [self._identity(member, member.get("id")) for member in family if isinstance(member, dict)]
        return people, token_expiry(str(self._state().get("refresh") or ""))

    @staticmethod
    def _identity(person: dict, member: object) -> dict:
        """Only what identifies a person; phone, e-mail, QR and portal codes,
        MedEir identifiers and the address are dropped here."""
        ident = ("f" if member is not None else "p") + digits(person.get("id"))
        return {
            "id": ident,
            "match_ids": [ident],
            "family_member_id": int(digits(member)) if member is not None else None,
            "firstname": str(person.get("first_name") or "")[:80],
            "lastname": str(person.get("last_name") or "")[:80],
            "middlename": str(person.get("middle_name") or "")[:80],
            "birthday": _birthday(person.get("dob")),
            "sex": sex_of(person.get("gender")),
        }

    def _items(self, kind: str, person: dict) -> list[dict]:
        """Every item of one list, page after page while the lab says
        ``has_more``.  The live backend answered 44 analyses under
        ``limit: 20``, so it may ignore paging: a page that brings no new
        id ends the walk rather than looping on the first page."""
        found: dict[str, dict] = {}
        while True:
            reply = self._get(f"/api/v1/medical/{kind}", person, skip=len(found))
            items = reply.get("items") if isinstance(reply, dict) else None
            if not isinstance(items, list):
                raise LabSyncError(ERROR_REPLY)
            before = len(found)
            for item in items:
                if isinstance(item, dict) and digits(item.get("id")):
                    found.setdefault(digits(item.get("id")), item)
            if not reply.get("has_more") or len(found) == before:
                return list(found.values())

    def orders(self, person: dict) -> list[dict]:
        """Analyses, the visits' conclusions and the examinations: each as
        one order.  ``is_linked_to_medeir`` is not a gate: a live account
        answered ``false`` on its profile and still listed 44 analyses
        (2026-11-06)."""
        analyses = [self._order_entry(analysis) for analysis in self._items("analyses", person)]
        conclusions = [self._conclusion(item, person) for item in self._items("conclusions", person)]
        return [*analyses, *(_document_entry("conclusions", item) for item in conclusions),
                *(_document_entry("research", item) for item in self._items("research", person))]

    def _conclusion(self, item: dict, person: dict) -> dict:
        """The list names a conclusion, its doctor and day; what the doctor
        wrote (complaints … recommendations) is on the conclusion itself, and
        whether there is anything to file is known only from there."""
        detail = self._get(f"/api/v1/medical/conclusions/{digits(item.get('id'))}", person)
        return {**item, **detail} if isinstance(detail, dict) else item

    def _order_entry(self, analysis: dict) -> dict:
        indicators = analysis.get("indicators")
        rows = self._rows(analysis) if isinstance(indicators, list) and indicators else None
        day = str(analysis.get("date") or analysis.get("created_at") or "")
        return {
            "order_id": digits(analysis.get("id")),
            "remote_ref": None,
            "ordered_at": day[:16].replace("T", " ") or None,
            "dates": sorted({d for d in (iso_day(analysis.get("date")), iso_day(analysis.get("result_date"))) if d}),
            "lab_status": str(analysis.get("status") or analysis.get("status_code") or "")[:40] or None,
            "ready": sum(1 for row in rows if row["result"]) if rows else 0,
            "total": len(rows) if rows else 0,
            # Finished once the results are entered; the PDF is attached
            # then too, except for the few the lab never gives one.
            "complete": analysis.get("status_code") == "ResultSubmitted" or bool(analysis.get("has_file")),
            "unavailable": None if analysis.get("has_file") else "labsync.unavailable_nofile",
            "rows": rows,
        }

    @staticmethod
    def _rows(analysis: dict) -> list[dict]:
        packet = analysis.get("name")
        rows = []
        for item in analysis.get("indicators") or []:
            if not isinstance(item, dict):
                continue
            value = "" if item.get("value") is None else _trim(str(item["value"]).strip())
            rows.append(lab_row(
                test=item.get("name"), result=value, units=item.get("unit"),
                resulttype="info" if len(value) > 200 else "",
                state=_indicator_state(value, item.get("is_abnormal")),
                norm=_norm(item), packet=packet, idtest=item.get("id"),
            ))
        return rows

    def rows(self, order: dict, person: dict) -> list[dict]:
        if order.get("rows") is not None:
            return order["rows"]
        analysis = self._get(f"/api/v1/medical/analyses/{digits(order['order_id'])}", person)
        if not isinstance(analysis, dict):
            raise LabSyncError(ERROR_REPLY)
        rows = self._rows(analysis)
        # The list leaves indicators out; the counts are known only now.
        order.update(rows=rows, ready=sum(1 for row in rows if row["result"]), total=len(rows))
        return rows

    def pdfs(self, order: dict, person: dict) -> list[bytes]:
        kind, ident = _remote(order["order_id"])
        base = f"/api/v1/medical/{kind}/{ident}"
        if kind == "analyses":
            return [self._get(f"{base}/file", person, want="pdf")]
        files = [item for item in order.get("files") or [] if isinstance(item, dict) and _real_file(item)]
        if len(files) > 1:  # each attachment by its id
            attached = [self._file(f"{base}/files/{digits(item['file_id'])}", person, item.get("name"))
                        for item in files]
        elif order.get("has_file"):  # ``/file`` is the document in a form one can open
            attached = [self._file(f"{base}/file", person, files[0].get("name") if files else "")]
        else:
            attached = []
        attached = [data for data in attached if data]
        record = visit_pdf.record_pdf(kind, order.get("record") or {}, order["packet"],
                                      (order.get("dates") or [""])[0], order["order_id"])
        # A conclusion's text is the visit itself, whatever it attached.  An
        # examination's typed findings are its report when no PDF came: an
        # X-ray's files are the radiographs, its report is only that text.
        if record and (kind == "conclusions" or not any(data.startswith(b"%PDF") for data in attached)):
            attached.insert(0, record)
        if not attached:
            raise LabSyncError("labsync.error_pdf")
        return attached

    def _file(self, path: str, person: dict, name: object) -> bytes | None:
        """A file the pipeline can read: a PDF or a scan as it is, a Word
        document as a PDF of its text; anything else is left out (logged)."""
        data = self._get(path, person, want="file")
        if not isinstance(data, bytes):
            return None
        if data.startswith(b"%PDF") or any(data.startswith(magic) for magic in _SCANS):
            return data
        if visit_pdf.is_docx(data):
            return visit_pdf.docx_pdf(data, str(name or ""))
        common.logger.warning("labsync: expert file of an unreadable type left out (%s)", data[:8])
        return None


#: The lists that hold a visit's documents, and the letter that keeps their
#: ids apart from an analysis's in ``lab_orders`` (one id space per list).
DOCUMENT_KINDS = {"conclusions": "c", "research": "r"}
_KIND_OF = {letter: kind for kind, letter in DOCUMENT_KINDS.items()}
#: A scanned report: JPEG, PNG, TIFF.
_SCANS = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"II*\x00", b"MM\x00*")


def _remote(order_id: str) -> tuple[str, str]:
    """``(list, id)`` the lab knows an order by: ``c12`` is conclusion 12,
    a bare number an analysis."""
    order_id = str(order_id)
    if order_id[:1] in _KIND_OF:
        return _KIND_OF[order_id[:1]], digits(order_id[1:])
    return "analyses", digits(order_id)


def _real_file(item: dict) -> bool:
    """A stored file, not the page the app renders inline (``file_id: 0``,
    ``source: "inline"``, an HTML view of the record ``/file`` serves as a PDF)."""
    return digits(item.get("file_id")) not in ("", "0") and item.get("source") != "inline"


def _day(item: dict) -> str:
    return (iso_day(item.get("date")) or iso_day(item.get("research_date")) or _birthday(item.get("date_str"))
            or iso_day(item.get("created_at")))


def _document_entry(kind: str, item: dict) -> dict:
    """A conclusion or an examination as an order: no rows (its values, if
    any, come from reading the document), finished once the clinic has filed
    it.  Its day and name travel in the file name, as a clinic's document's
    do, so the reader titles it as the clinic did.  An examination is named
    by what was examined («Рентгенографія ОГК (дві проекції)»), its type
    («Комп'ютерна рентгенографія») when that is all there is."""
    day = _day(item)
    title = " ".join(str(item.get("title") or item.get("name") or item.get("body_part") or item.get("research_type")
                         or item.get("conclusion_type") or "").split())[:160]
    typed = any(visit_pdf.field_text(item.get(key)) for key, _ in visit_pdf.SECTIONS[kind])
    return {
        "order_id": DOCUMENT_KINDS[kind] + digits(item.get("id")),
        "remote_ref": None,
        "ordered_at": day or None,
        "dates": [day] if day else [],
        "lab_status": str(item.get("status") or "")[:40] or None,
        "ready": 0,
        "total": 0,
        "complete": True,
        # Neither a file nor a word written (a 2022 cardiology visit holds
        # only its doctor and day): nothing to file, and the order says so.
        "unavailable": None if item.get("has_file") or typed else "labsync.error_pdf",
        "rows": [],
        "packet": title,
        "filename_hint": f"{day} {title}" if day and title else "",
        # An examination's files are all of it (its report, its radiographs);
        # a conclusion's attachments are documents of their own.
        "hint_every_file": kind == "research",
        "has_file": bool(item.get("has_file")),
        "files": item.get("files") if isinstance(item.get("files"), list) else [],
        "record": item,
    }


def lab(key: str, name: str, vendor: str, default_url: str):
    """Another lab on this same backend: register ``lab(…)`` in
    ``labsync.PROVIDERS`` and give it ``labsync.<key>_lead``/``_admin_lead``/
    ``_expires_hint`` messages."""
    return types.SimpleNamespace(
        KEY=key, NAME=name, VENDOR=vendor, DEFAULT_URL=default_url, SIGN_IN=SIGN_IN, Client=Client,
        start_sign_in=start_sign_in, verify_code=verify_code, normalize_phone=normalize_phone,
    )
