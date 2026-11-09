"""Doctor Eleks — the clinic platform by ELEKS (doctor.eleks.com) behind the
patient apps of several Ukrainian clinics.  Each clinic ships its own build
of one white-label Expo/React Native app (``com.eleks.<clinic>``); they differ
only in a tenant id.  Observed from St. Paraskeva Medical Center 1.8.2
(``com.eleks.stparaskeva``) and Veselka 1.6.5 (``com.eleks.veselka``) on
2026-11-06: static analysis of the Hermes bytecode, plus the two calls the app
makes before anyone signs in.  Not the Expert Hospital vendor: a different stack,
transport and model.

One server for every clinic, ``https://portal-doctor.eleks.com/api``; the
clinic is the ``installationId`` in every request body.  Everything is a call
to a named stored procedure, POSTed as JSON::

    {"name": "<procedure>", "installationId": "<clinic>",
     "params": [{"name": "<Param>", "value": …}]}

to ``/api/va`` when the name contains ``Anonymous`` (no sign-in needed) and to
``/api/v`` with ``Authorization: Bearer <access>`` otherwise.  Parameter names
are the procedure's own (a stray one is refused: "@X is not a parameter for
procedure …").  Replies are ``{"value": …}`` for data procedures and
``{"menu"|"view": …}`` for the server-driven screens.

Sign-in, as the app's phone mode (both clinics' login screens are set to it,
``isPhoneLoginMode: "1"``, prefix ``+380``, 6-digit SMS code):

1. ``spiAnonymousAuthorizeByPhone {Phone}`` → ``value[0] = {statusCode,
   statusMessage, sessionGUID}``; the clinic texts a code.  The app compares
   ``statusCode`` loosely (``!= 200``), so "200" passes too.
2. ``spiAnonymousAuthorizeByPhone {Phone, OTPCode, SessionGUID}`` → one row
   ``{statusCode, userLogin, userPassword, token, refreshToken}``, or several
   ``{patientID, patientName}`` when the phone belongs to several accounts:
   the person picks one and the call is repeated with ``PatientID``.
3. ``POST /api/token`` (form) ``grant_type=password&username=<userLogin>@@@
   <installationId>&password=<userPassword>&token=<token>`` → ``{access_token,
   ".expires"}``.  ``userPassword`` is a server-issued secret, used once here
   and never stored.
4. Renewal: ``spiAnonymousTokenRefresh {RefreshToken}`` → ``value[0] =
   {expires, login, accessToken, refreshToken}``; the app renews once
   ``expires`` has passed (it posts to ``/api/runanonymous``, which answers as
   ``/api/va`` does).  Veselka's server has no such procedure (2026-11-09), so
   there a lapsed access token means signing in again.

Signed in, every call also carries ``Login``.  ``spiUserPatientDetails {Login,
DeviceInfoJson, DeviceIdentifier}`` → ``value = {user, patientList: [{patientID,
isMain, …}], …}``: the people this account may see.

Results.  The screens come from the server and their procedures differ per
clinic, so a sync follows the menu as the app does (live, both clinics,
2026-11-06): ``spzIBWApplicationDetails {DeviceIdentifier}`` → ``menu``; the
entry named ``Document`` («Документи») opens the documents screen
(St. Paraskeva ``spzIBWDocumentList``, Veselka ``spzIBWDocumentList_New``),
whose ``CTTab`` cells are its sub-tabs (St. Paraskeva: Консультації,
Лабораторія, Обстеження, Файли; Veselka: Консультації, Діагностика, Файли),
each a call of the same procedure with the tab's params.  A document is a
``List`` cell whose action is ``spzIBWDocumentView {documentID,
presentationName}``; its screen is a ``WebView`` whose ``iosUrl`` (and the
share action's ``url``) is ``/api/document?request=<base64 documentId,
validateId, presentationName, login>&installationID=…`` — the clinic's own
PDF, fetched with a plain GET as the app does.  Cells without such an action
(upload buttons, spacers) are not documents.  Values come from the PDF, as
from a hand upload; the screens carry none, so there is no clinic-side
cross-check for this family.

Adding a clinic of this family is one :func:`clinic` line in :data:`CLINICS`
(its ``installationId`` is in the app bundle's ``installationConfig``) plus
its vendor name in ``ingest/classifier.py``; the messages are shared.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import types
from datetime import UTC, datetime

from . import common
from .common import ERROR_REPLY, LabSyncError, digits, iso_day, sex_of
from .expert import _birthday, normalize_phone

ERROR_CODE = "labsync.password_error_code"
ERROR_UNMAPPED = "labsync.doctoreleks_error_unmapped"

logger = logging.getLogger("anamna.labsync.doctoreleks")

FAMILY = "doctoreleks"
DEFAULT_URL = "https://portal-doctor.eleks.com"
#: Phone and a texted code, no password (labsync._sign_in).
SIGN_IN = "sms"

_CODE_RE = re.compile(r"\d{4,8}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/=-]{8,4096}")
_GUID_RE = re.compile(r"[0-9A-Fa-f-]{8,64}")

#: The menu entry that opens the documents screen.
DOCUMENTS_MENU = "Document"
#: A list cell's action that opens one document.
_VIEW_RE = re.compile(r"\w*DocumentView")
#: Actions whose ``url`` is the document's file (the share button).
_URL_ACTIONS = {"shareRemoteFile", "downloadFile"}
#: Consent forms («Форма № 003-6/о Інформована добровільна згода», the
#: 063-2/о vaccination consent): the clinic files a blank printed template
#: with every visit (live Veselka, 2026-11-06) — no name, no finding, nothing
#: for a medical record, so they are not imported.
_CONSENT_RE = re.compile(r"згод", re.IGNORECASE)


def _params(values: dict) -> list[dict]:
    return [{"name": name, "value": value} for name, value in values.items()]


def _shape(value: object, depth: int = 0) -> object:
    """A reply's structure -- keys, types, lengths -- and never its values, so
    a reply this module cannot read can be logged without patient data."""
    if isinstance(value, dict):
        return {key: _shape(item, depth + 1) for key, item in list(value.items())[:40]} if depth < 4 else "{...}"
    if isinstance(value, list):
        return [f"list[{len(value)}]", _shape(value[0], depth + 1)] if value else "list[0]"
    if isinstance(value, str):
        return f"str({len(value)})"
    return type(value).__name__


def _unreadable(name: str, reply: object, why: str, key: str = ERROR_REPLY) -> LabSyncError:
    """Log what did not fit, then the error the person sees."""
    if isinstance(reply, str):
        # The server answers a bad call with a sentence (``@X is not a parameter
        # for procedure Y.``): procedure and parameter names, digits masked.
        logger.warning("doctoreleks %s: %s; server said: %s", name, why, re.sub(r"\d", "#", reply)[:300])
    else:
        logger.warning("doctoreleks %s: %s; reply shape: %s", name, why, json.dumps(_shape(reply))[:1500])
    return LabSyncError(key)


def _call(base_url: str, installation: str, name: str, values: dict, *, secret: str = "",
          refused: str = ERROR_REPLY) -> object:
    path = "/api/va" if "Anonymous" in name else "/api/v"
    try:
        reply, _ = common.call("POST", base_url.rstrip("/") + path,
                               headers={"Authorization": f"Bearer {secret}"} if secret else {},
                               payload={"name": name, "installationId": installation, "params": _params(values)})
    except LabSyncError as exc:
        if exc.status == 429:
            raise LabSyncError("labsync.password_error_throttled", 429) from None
        if exc.status in (400, 404, 422) and refused != ERROR_REPLY:
            raise LabSyncError(refused, exc.status) from None
        raise
    if isinstance(reply, str):
        raise _unreadable(name, reply, "a sentence instead of data")
    return reply


def _first_row(reply: object, name: str = "") -> dict:
    rows = reply.get("value") if isinstance(reply, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise _unreadable(name, reply, "no rows")
    return rows[0]


def start_sign_in(base_url: str, phone: object, password: object, state: dict, *, installation: str) -> dict:
    """Ask the clinic to text a code; ``password`` is not part of this flow."""
    phone = normalize_phone(phone)
    row = _first_row(_call(base_url, installation, "spiAnonymousAuthorizeByPhone", {"Phone": phone},
                           refused="labsync.sms_error_phone"))
    session = str(row.get("sessionGUID") or "")
    if str(row.get("statusCode")) != "200" or not _GUID_RE.fullmatch(session):
        raise LabSyncError("labsync.sms_error_phone")
    return {"challenge": {"token": session, "phone_masked": phone[:4] + "•" * 7 + phone[-2:],
                          "code_length": 6, "expires_in": 300}, "phone": phone}


def verify_code(base_url: str, challenge: dict, code: object, state: dict, phone: str, *,
                installation: str) -> dict:
    """Credentials — or, when the phone opens several accounts, the challenge
    again with ``users`` to choose from (``challenge["patient"]`` picks)."""
    code = re.sub(r"\s", "", str(code or ""))
    if not _CODE_RE.fullmatch(code):
        raise LabSyncError(ERROR_CODE)
    values = {"Phone": phone, "OTPCode": code, "SessionGUID": challenge["token"]}
    if challenge.get("patient"):
        # Sent back exactly as the server listed it (the app passes
        # ``selectedUser.patientID`` through untouched).
        values["PatientID"] = next((user["raw"] for user in challenge.get("users") or []
                                    if user["id"] == str(challenge["patient"])), challenge["patient"])
    reply = _call(base_url, installation, "spiAnonymousAuthorizeByPhone", values,
                  refused=ERROR_CODE)
    rows = reply.get("value") if isinstance(reply, dict) else None
    if isinstance(rows, list) and len(rows) > 1 and not challenge.get("patient"):
        users = [{"id": str(row.get("patientID")), "raw": row.get("patientID"),
                  "name": " ".join(str(row.get("patientName") or "").split())[:120]}
                 for row in rows if isinstance(row, dict) and row.get("patientID") not in (None, "")]
        return {"challenge": {**challenge, "code": code, "users": users}, "phone": phone}
    return _sign_in_row(base_url, installation, challenge, reply, state, phone)


def _issue_token(base_url: str, installation: str, login: str, secret: str, token: str) -> object:
    form = {"grant_type": "password", "username": f"{login}@@@{installation}", "password": secret}
    if token:
        form["token"] = token
    try:
        issued, _ = common.call("POST", base_url.rstrip("/") + "/api/token", headers={}, form=form)
    except LabSyncError as exc:
        if exc.status in (400, 401, 403):
            raise LabSyncError(ERROR_CODE, exc.status) from None
        raise
    return issued


def _sign_in_row(base_url: str, installation: str, challenge: dict, reply: object, state: dict, phone: str) -> dict:
    """Turn the one signed-in row into credentials through the token endpoint."""
    row = _first_row(reply, "spiAnonymousAuthorizeByPhone")
    # The app checks the status only before a person is chosen; after the
    # choice it signs in with whatever single row comes back.
    if not challenge.get("patient") and str(row.get("statusCode")) != "200":
        raise LabSyncError(ERROR_CODE)
    login, secret, token = (str(row.get(key) or "") for key in ("userLogin", "userPassword", "token"))
    refresh = str(row.get("refreshToken") or "")
    if not login or not secret:
        raise _unreadable("spiAnonymousAuthorizeByPhone", reply, "no login in the signed-in row")
    issued = _issue_token(base_url, installation, login, secret, token)
    if not isinstance(issued, dict):
        raise _unreadable("token", issued, "no token object")
    refresh = refresh or str(issued.get("refresh_token") or "")
    # The app keeps the token reply's own ``login`` when it has one (a person
    # chosen on a shared phone gets a login of their own), else the row's.
    login = str(issued.get("login") or login)
    try:
        return _credentials(str(issued.get("access_token") or ""), issued.get(".expires"), refresh, login, state, phone)
    except LabSyncError:
        raise _unreadable("token", issued, "no usable access token") from None


def _expiry(value: object) -> str | None:
    """``.expires`` is an HTTP date (``Thu, 06 Nov 2026 12:00:00 GMT``) from
    the token endpoint and ISO from the refresh procedure."""
    text = str(value or "").strip()
    for parse in (lambda t: datetime.strptime(t, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC),
                  lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))):
        try:
            moment = parse(text)
        except ValueError:
            continue
        return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="seconds")
    return None


def _credentials(access: str, expires: object, refresh: str, login: str, state: dict, phone: str) -> dict:
    """A renewal token is optional: St. Paraskeva issues none when a person is
    chosen from several on one phone (live, 2026-11-06), and the app then
    simply signs in again once the access token's time is up -- so does this."""
    if not _TOKEN_RE.fullmatch(access) or (refresh and not _TOKEN_RE.fullmatch(refresh)):
        raise LabSyncError(ERROR_REPLY)
    until = _expiry(expires)
    kept = {"refresh": refresh, "login": login, "expires": until, "device_id": state["device_id"]}
    # With a renewal token the session outlives the access token and its own
    # lifetime is not published; without one, the access expiry is the end.
    return {"secret": access, "refresh_secret": json.dumps(kept), "phone": phone,
            "expires_at": None if refresh else until}


def _records(reply: object) -> list[dict]:
    """A screen's cells, every view flattened."""
    if isinstance(reply, dict) and isinstance(reply.get("view"), list):
        return [cell for view in reply["view"] if isinstance(view, dict)
                for cell in (view.get("data") or []) if isinstance(cell, dict)]
    return []


def _actions(item: dict) -> list[dict]:
    """What tapping a cell (or menu entry) does, as the server parsed its ``actionXml``."""
    return [action for action in item.get("action") or [] if isinstance(action, dict) and action.get("name")]


def _proc(action: dict) -> tuple[str, dict]:
    """An action as a procedure call.  The server lowers the first letter of
    ``actionXml``'s parameter names (``Mode`` → ``mode``); the procedure takes
    them as written there."""
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    return str(action["name"]), {key[:1].upper() + key[1:]: value for key, value in params.items()}


def _when(cell: dict) -> str | None:
    """``YYYY-MM-DD[ HH:MM]``: St. Paraskeva sends ``orderValue`` (ISO);
    Veselka only prints the day («09.08.2026», or «12.03.2022, 15:17»)."""
    stamp = str(cell.get("orderValue") or "")
    if iso_day(stamp):
        return stamp[:16].replace("T", " ")
    printed = " ".join(str(cell.get(key) or "") for key in ("text1", "groupValue", "text_1_1"))
    found = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?", printed)
    if not found:
        return None
    day = f"{found[3]}-{found[2]}-{found[1]}"
    return f"{day} {int(found[4]):02d}:{found[5]}" if found[4] else day


def _title(cell: dict) -> str:
    """The document's name: the first text that is not its date."""
    for key in ("text2", "text_2_1", "text1", "text_1_1"):
        text = " ".join(str(cell.get(key) or "").split())
        if text and not re.match(r"\d{2}\.\d{2}\.\d{4}", text):
            return text[:300]
    return ""


class Client:
    def __init__(self, base_url: str, secret: str, phone: str = "", refresh: str = "", *, installation: str):
        self.base_url, self.secret, self.phone = base_url.rstrip("/"), secret, phone
        self.installation = installation
        #: JSON: refresh token, login, access expiry and device id.
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
        try:
            row = _first_row(_call(self.base_url, self.installation, "spiAnonymousTokenRefresh",
                                   {"RefreshToken": state["refresh"]}, refused="labsync.error_auth"))
            fresh = _credentials(str(row.get("accessToken") or ""), row.get("expires"),
                                 str(row.get("refreshToken") or state["refresh"]),
                                 str(row.get("login") or state.get("login") or ""),
                                 {"device_id": state.get("device_id")}, self.phone)
        except LabSyncError as exc:
            # Veselka's server has no renewal procedure at all ("Could not find
            # stored procedure 'spiAnonymousTokenRefresh'", live 2026-11-09, on
            # the app's own /api/runanonymous too), and a spent renewal token
            # answers a status row with no token in it.  Either way the session
            # is over: the person signs in again, as in the app -- not an
            # unreadable reply on every sync from then on.
            if exc.key != ERROR_REPLY or exc.status:
                raise
            raise LabSyncError("labsync.error_auth", 401) from None
        self.secret, self.refresh_secret = fresh["secret"], fresh["refresh_secret"]

    def _run(self, name: str, values: dict | None = None, *, again: bool = True) -> object:
        state = self._state()
        expires = state.get("expires")
        if again and expires and str(expires) <= datetime.now(UTC).isoformat(timespec="seconds"):
            self._refresh()  # as the app does: renew once the access token's time is up
            state, again = self._state(), False
        try:
            return _call(self.base_url, self.installation, name,
                         {"Login": state.get("login"), **(values or {})}, secret=self.secret)
        except LabSyncError as exc:
            if exc.status == 401 and again:
                self._refresh()
                return self._run(name, values, again=False)
            raise

    def check(self) -> tuple[list[dict], str | None]:
        # Veselka's server refuses ``DeviceIdentifier`` ("is not a parameter for
        # procedure spiUserPatientDetails"); the app adds it only when push
        # notifications are registered, so it is left out.
        reply = self._run("spiUserPatientDetails", {"DeviceInfoJson": None})
        value = reply.get("value") if isinstance(reply, dict) else None
        value = value[0] if isinstance(value, list) and value else value
        if not isinstance(value, dict):
            raise _unreadable("spiUserPatientDetails", reply, "no account details")
        listed = [p for p in value.get("patientList") or [] if isinstance(p, dict) and p.get("patientID") is not None]
        listed.sort(key=lambda p: not p.get("isMain"))  # the account's own person first
        if listed:
            return [self._identity(person) for person in listed], None
        # St. Paraskeva lists the people on the login in its card switcher
        # instead (2026-11-06).
        cards = self._cards()
        if cards:
            return [card["person"] for card in cards], None
        # An account whose results are its own (Veselka, 2026-11-06): no
        # patient list and no switcher, the signed-in login is the person.
        user = value.get("user") if isinstance(value.get("user"), dict) else {}
        login = str(user.get("userLogin") or self._state().get("login") or "")
        if not login:
            raise _unreadable("spiUserPatientDetails", reply, "neither a patient list nor a login")
        return [self._account_identity(user, login)], None

    @staticmethod
    def _account_identity(user: dict, login: str) -> dict:
        """The signed-in account as the one person on it, keyed by its login."""
        ident = "u" + hashlib.sha256(login.encode("utf-8")).hexdigest()[:16]
        name = " ".join(str(user.get("userName") or "").split())
        last, _, rest = name.partition(" ")
        first, _, middle = rest.partition(" ")
        return {
            "id": ident, "match_ids": [ident], "family_member_id": None, "main": True,
            "firstname": first[:80], "lastname": last[:80], "middlename": middle[:80],
            "birthday": _birthday(user.get("userBirthDate")), "sex": None,
        }

    @staticmethod
    def _identity(person: dict) -> dict:
        """Only what identifies a person.  ``patientID``/``patientName`` are
        the app's own field names; the date of birth and sex keys are the
        likeliest spellings, unconfirmed — when absent, the person confirms
        the match by hand (labsync.demographics)."""
        ident = digits(person.get("patientID"))
        name = " ".join(str(person.get("patientName") or person.get("fullName") or "").split())
        last, _, rest = name.partition(" ")
        first, _, middle = rest.partition(" ")
        return {
            "id": "p" + ident,
            "match_ids": ["p" + ident],
            "family_member_id": int(ident),
            "main": bool(person.get("isMain")),
            "firstname": first[:80], "lastname": last[:80], "middlename": middle[:80],
            "birthday": _birthday(person.get("birthDate") or person.get("dateOfBirth")),
            "sex": sex_of(person.get("sex") or person.get("gender")),
        }

    def _screen(self) -> tuple[str, dict, object]:
        """The menu's documents screen: its procedure, its params, its reply."""
        menu = self._run("spzIBWApplicationDetails", {"DeviceIdentifier": self._state().get("device_id")})
        entries = [item for item in (menu.get("menu") if isinstance(menu, dict) else None) or []
                   if isinstance(item, dict) and item.get("name") == DOCUMENTS_MENU and _actions(item)]
        if not entries:
            raise _unreadable("spzIBWApplicationDetails", menu, "no documents menu",
                              ERROR_UNMAPPED)
        name, params = _proc(_actions(entries[0])[0])
        return name, params, self._run(name, params)

    def _cards(self, screen: tuple[str, dict, object] | None = None) -> list[dict]:
        """The medical cards this login may switch between: the documents
        screen's «(активна мед-карта)» row opens ``spzIBWProfileSelectPopup``
        («Оберіть активну мед-карту»), a card per person, each picked by
        ``spzIBWPatientRoleSelectConfirm {patientID}`` (St. Paraskeva,
        2026-11-06).  ``[]`` when the clinic has no switcher (Veselka)."""
        _, _, reply = screen or self._screen()
        popup = next((action for cell in _records(reply) for action in _actions({"action": cell.get("action2")})
                      if "ProfileSelect" in action["name"]), None)
        if popup is None:
            return []
        cards = []
        for cell in _records(self._run(*_proc(popup))):
            pick = next((action for action in _actions(cell)
                         if re.fullmatch(r"\d{1,20}", str((action.get("params") or {}).get("patientID") or ""))), None)
            if pick is None:
                continue
            ident = str(pick["params"]["patientID"])
            printed = " ".join(str(cell.get("text_2_1") or "").split())
            last, _, rest = re.sub(r" ?\(актив[^)]*\)", "", printed).partition(" ")
            first, _, middle = rest.partition(" ")
            cards.append({"active": "(актив" in printed, "pick": pick, "person": {
                "id": "p" + ident, "match_ids": ["p" + ident], "family_member_id": int(ident),
                # «Власний профіль» heads the login's own card; the rest are
                # «Перелік доступних профілів».
                "main": str(cell.get("groupValue") or "").strip().casefold().startswith("власн"),
                "firstname": first[:80], "lastname": last[:80], "middlename": middle[:80],
                "birthday": _birthday(str(cell.get("text_2_2") or "").strip()),
                "sex": {"res:male": "male", "res:female": "female"}.get(str(cell.get("image_1_1") or "")),
            }})
        if cards and not any(card["person"]["main"] for card in cards):
            cards[0]["person"]["main"] = True
        return cards

    def _select(self, card: dict) -> None:
        """Make a card the active one, as the app does: its confirmation
        screen's «Так» runs the save procedure (``spiSelectedPatientSave
        {SelectedPatientID, Platform}``); the screen-opening actions beside it
        are skipped."""
        confirm = self._run(*_proc(card["pick"]))
        saves = [action for cell in _records(confirm) if cell.get("cellTemplate") == "CTButton"
                 for action in _actions(cell) if action["name"].startswith("spi")]
        if not saves:
            raise _unreadable(card["pick"]["name"], confirm, "no confirming button",
                              ERROR_UNMAPPED)
        for action in saves:
            self._run(*_proc(action))

    def _read(self, name: str, params: dict, screen: object) -> list[dict]:
        """Every sub-tab of the documents screen, each document once."""
        tabs = [_proc(action) for cell in _records(screen) if cell.get("cellTemplate") == "CTTab"
                for action in _actions(cell) if action["name"] == name]
        unique = list({json.dumps(tab, sort_keys=True, ensure_ascii=False): tab for tab in tabs}.values())
        out: dict[str, dict] = {}
        for tab_name, reply in [(tab[0], self._run(*tab)) for tab in unique] or [(name, screen)]:
            if not isinstance(reply, dict) or not isinstance(reply.get("view"), list):
                raise _unreadable(tab_name, reply, "no screen")
            for cell in _records(reply):
                view = next((a for a in _actions(cell) if _VIEW_RE.fullmatch(a["name"])), None)
                ident = str(((view or {}).get("params") or {}).get("documentID") or "").strip()
                if not re.fullmatch(r"\d{1,20}", ident) or ident in out or _CONSENT_RE.search(_title(cell)):
                    continue
                out[ident] = _document_entry(ident, cell, view)
        return list(out.values())

    def orders(self, person: dict) -> list[dict]:
        """Each document under «Документи», every sub-tab, as one order.

        The list takes no person (``@PatientID is not a parameter``): it is
        the active medical card's.  Another person's card is made active for
        the read -- their documents and each file's address collected -- and
        the card that was active is put back, as the app's own switcher does.
        A person the clinic offers no way to switch to is refused rather than
        handed the active card's documents."""
        name, params, screen = self._screen()
        cards = self._cards((name, params, screen))
        target = next((card for card in cards if card["person"]["id"] == person.get("id")), None)
        if (cards and target is None) or (not cards and not person.get("main", True)):
            raise LabSyncError(ERROR_UNMAPPED)
        if target is None or target["active"]:
            return self._read(name, params, screen)
        back = next((card for card in cards if card["active"]), None) \
            or next(card for card in cards if card["person"]["main"])
        self._select(target)
        try:
            found = self._read(name, params, self._run(name, params))
            for order in found:
                order["url"] = self._url(order)  # while this card is the active one
            return found
        finally:
            self._select(back)

    def rows(self, order: dict, _person: dict) -> list[dict]:
        return order.get("rows") or []

    def _url(self, order: dict) -> str:
        """The document's file on the clinic server, from its screen."""
        view = order.get("view") or {"name": "spzIBWDocumentView",
                                     "params": {"documentID": order["order_id"], "presentationName": "пац"}}
        screen = self._run(*_proc(view))
        views = (screen.get("view") if isinstance(screen, dict) else None) or []
        urls = [str((item.get("settings") or {}).get("iosUrl") or "") for item in views if isinstance(item, dict)]
        urls += [str((action.get("params") or {}).get("url") or "")
                 for cell in _records(screen) for action in _actions(cell) if action["name"] in _URL_ACTIONS]
        url = next((u for u in urls if u.startswith(self.base_url + "/api/document?")), None)
        if not url:
            raise _unreadable("spzIBWDocumentView", screen, "no document URL", "labsync.error_pdf")
        return url

    def pdfs(self, order: dict, _person: dict) -> list[bytes]:
        """The document's own PDF, opened with a plain GET as the app does."""
        url = order.get("url") or self._url(order)
        if not url.startswith(self.base_url + "/api/document?"):
            raise LabSyncError("labsync.error_pdf")
        pdf, _ = common.call("GET", url, headers={}, want="pdf")
        return [pdf]


def _document_entry(ident: str, cell: dict, view: dict | None) -> dict:
    day = _when(cell)
    return {
        "order_id": ident,
        "remote_ref": None,
        "ordered_at": day,
        "dates": [iso_day(day)] if day else [],
        "lab_status": None,
        "ready": 0,
        "total": 0,
        "complete": True,  # a document the clinic files is a finished one
        "unavailable": None,
        # ponytail: values come from the PDF only; the screens carry none.
        "rows": [],
        "packet": _title(cell),
        "filename_hint": f"{iso_day(day)} {_title(cell)}" if day and _title(cell) else "",
        "view": view,
    }


def clinic(key: str, name: str, vendor: str, installation: str):
    """One clinic on Doctor Eleks: ``vendor`` is the name the PDF classifier
    gives its reports (ingest/classifier.py), so old uploads are recognised."""
    return types.SimpleNamespace(
        KEY=key, NAME=name, VENDOR=vendor, DEFAULT_URL=DEFAULT_URL, SIGN_IN=SIGN_IN, MESSAGES=FAMILY,
        INSTALLATION=installation, normalize_phone=normalize_phone,
        Client=functools.partial(Client, installation=installation),
        start_sign_in=functools.partial(start_sign_in, installation=installation),
        verify_code=functools.partial(verify_code, installation=installation),
    )


CLINICS = {c.KEY: c for c in (
    clinic("paraskeva", "St. Paraskeva Medical Center", "St. Paraskeva Medical Center",
           "8CF86A8D-E826-44C6-9985-9D8A5F31C7EB"),
    clinic("veselka", "Veselka", "Veselka", "7d4e1338-2149-48f9-9f7f-8a9f920ab4d6"),
)}

__all__ = ["CLINICS", "DOCUMENTS_MENU", "Client", "clinic", "start_sign_in", "verify_code"]
