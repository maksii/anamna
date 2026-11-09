"""Doctor Eleks clinics (St. Paraskeva, Veselka): phone + texted-code sign-in,
choosing among several accounts, token renewal, the people on an account, and
reading results — against synthetic replies shaped like what the Android apps
send and receive (see labsync/doctoreleks.py).  HTTP is stubbed at
``labsync.common._http``; every call is a POST to /api/v or /api/va, routed
here by the procedure name in its body."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.ingest.classifier import classify_document
from anamna.labsync import LabSyncError, common, doctoreleks

from test_labsync import csrf, make, seed_doc, stub_intake

URL = "http://127.0.0.1:9"
PARASKEVA = doctoreleks.CLINICS["paraskeva"]
TENANT = PARASKEVA.INSTALLATION
SESSION = "5f1d2c3b-0000-4000-8000-000000000001"
ACCESS, ACCESS2 = "synthetic-access-token-0001", "synthetic-access-token-0002"
REFRESH, REFRESH2 = "synthetic-refresh-0001", "synthetic-refresh-0002"
SERVER_SECRET = "server-issued-secret-0001"
USER_ROW = {"statusCode": 200, "statusMessage": "", "userLogin": "u100", "userPassword": SERVER_SECRET,
            "token": "otp-bound-token-0001", "refreshToken": REFRESH}
TWO_USERS = [{"patientID": 100, "patientName": "Тестовий Тест Тестович"},
             {"patientID": 101, "patientName": "Тестова Дитина Тестівна"}]
DETAILS = {"value": {"user": {"login": "u100"}, "patientList": [
    {"patientID": 101, "patientName": "Тестова Дитина Тестівна", "isMain": False, "birthDate": "19.06.2020",
     "sex": "female", "phone": "+380000000009"},
    {"patientID": 100, "patientName": "Тестовий Тест Тестович", "isMain": True, "birthDate": "1990-03-14",
     "sex": "male"},
], "patientSecurityList": [], "userBadge": []}}
SPEC = {"list": "spzSyntheticResults", "detail": "spzSyntheticResultDetails", "detail_param": "DocumentID",
        "patient_param": "PatientID",
        "order": {"id": "documentID", "date": "date", "name": "caption", "status": "statusName",
                  "complete": "isReady", "document": "documentID"},
        "row": {"test": "name", "value": "value", "unit": "unit", "norm": "norm", "flag": "isAbnormal"}}
RESULTS_LIST = {"value": [
    {"documentID": 9001, "date": "2022-03-17T08:10:00", "caption": "Загальний аналіз крові",
     "statusName": "Готово", "isReady": 1},
    {"documentID": 9002, "date": "2025-11-05T09:00:00", "caption": "Феритин", "statusName": "В роботі",
     "isReady": 0},
]}
RESULT_9001 = {"value": [
    {"name": "Гемоглобін", "value": "151.000000", "unit": "г/л", "norm": "130.000000 - 170.000000",
     "isAbnormal": 0},
    {"name": "Лейкоцити", "value": "11.2", "unit": "10^9/л", "norm": "4 - 9", "isAbnormal": 1},
    {"name": "Колір", "value": "жовтий", "unit": None, "norm": None, "isAbnormal": None},
]}
PDF = b"%PDF-1.4 synthetic"
PDF_2 = b"%PDF-1.4 synthetic cardiology"


def ok(reply):
    return lambda request, headers: reply


def install(monkeypatch, procedures: dict, seen: list | None = None, token: object = None) -> list:
    """``procedures``: procedure name → reply (JSON-able, int status, or
    callable(request, headers)); ``token``: the /api/token reply."""
    seen = [] if seen is None else seen

    def http(method, url, *, headers, body=None, timeout=0, limit=0):
        path = "/" + url.split("/", 3)[3]
        if method == "GET":
            seen.append(("GET", url, headers))
            reply = procedures.get(url, 404)
            return (reply, [], b"") if isinstance(reply, int) else (200, [], reply)
        if path == "/api/token":
            seen.append(("token", dict(urllib.parse.parse_qsl(body.decode())), headers))
            reply = token if token is not None else 400
        else:
            request = json.loads(body.decode())
            seen.append((path, request, headers))
            reply = procedures.get(request["name"], 404)
            if callable(reply):
                reply = reply(request, headers)
        if isinstance(reply, int):
            return reply, [], b""
        return 200, [], json.dumps(reply).encode()

    monkeypatch.setattr(common, "_http", http)
    return seen


def params(request: dict) -> dict:
    return {item["name"]: item["value"] for item in request["params"]}


TOKEN = {"access_token": ACCESS, "token_type": "bearer", "expires_in": 86399,
         ".issued": "Thu, 06 Nov 2026 10:00:00 GMT", ".expires": "Fri, 07 Nov 2100 10:00:00 GMT"}


def test_both_clinics_are_one_family_and_match_the_names_their_reports_carry():
    veselka = doctoreleks.CLINICS["veselka"]
    assert {PARASKEVA.KEY, veselka.KEY} <= set(labsync.PROVIDERS)
    assert PARASKEVA.INSTALLATION != veselka.INSTALLATION
    assert PARASKEVA.DEFAULT_URL == veselka.DEFAULT_URL == "https://portal-doctor.eleks.com"
    assert labsync.signs_in("paraskeva") and not labsync.signs_in("synevo")
    # The vendor a sync looks documents up by is exactly what the classifier
    # gives these clinics' PDFs.
    for module, text in ((PARASKEVA, "Медцентр Св. Параскеви\nЗагальний аналіз крові"),
                         (veselka, "ТзОВ «Повноділ»\nЗагальний аналіз крові")):
        found = classify_document("r.pdf", "application/pdf", [{"native_text": text, "page_number": 1}])
        assert found.vendor == module.VENDOR


def test_phone_then_code_signs_in_as_the_app_and_keeps_no_password(monkeypatch):
    seen = install(monkeypatch, {"spiAnonymousAuthorizeByPhone": lambda request, headers: {"value": [
        {"statusCode": 200, "statusMessage": "", "sessionGUID": SESSION}] if "OTPCode" not in params(request)
        else [USER_ROW]}}, token=TOKEN)
    state = {"device_id": "00000000-0000-4000-8000-000000000001", "trusted": None}
    sent = PARASKEVA.start_sign_in(URL, "067 000 00 01", "", state)
    path, request, headers = seen[0]
    assert path == "/api/va" and "Authorization" not in headers
    assert request == {"name": "spiAnonymousAuthorizeByPhone", "installationId": TENANT,
                       "params": [{"name": "Phone", "value": "+380670000001"}]}
    assert sent["challenge"]["token"] == SESSION and sent["challenge"]["code_length"] == 6
    assert "0670000001" not in sent["challenge"]["phone_masked"]

    creds = PARASKEVA.verify_code(URL, sent["challenge"], "123 456", state, sent["phone"])
    assert params(seen[1][1]) == {"Phone": "+380670000001", "OTPCode": "123456", "SessionGUID": SESSION}
    kind, form, headers = seen[2]
    assert kind == "token" and headers["Content-Type"].startswith("application/x-www-form-urlencoded")
    assert form == {"grant_type": "password", "username": f"u100@@@{TENANT}", "password": SERVER_SECRET,
                    "token": "otp-bound-token-0001"}
    assert creds["secret"] == ACCESS and creds["expires_at"] is None
    kept = json.loads(creds["refresh_secret"])
    assert kept == {"refresh": REFRESH, "login": "u100", "expires": "2100-11-07T10:00:00+00:00",
                    "device_id": state["device_id"]}
    assert SERVER_SECRET not in json.dumps(creds)


def test_unknown_number_and_wrong_code_say_what_to_do(monkeypatch):
    install(monkeypatch, {"spiAnonymousAuthorizeByPhone": {"value": [
        {"statusCode": 404, "statusMessage": "Користувача не знайдено", "sessionGUID": None}]}})
    with pytest.raises(LabSyncError) as caught:
        PARASKEVA.start_sign_in(URL, "0670000001", "", {"device_id": "d"})
    assert caught.value.key == "labsync.sms_error_phone"
    install(monkeypatch, {"spiAnonymousAuthorizeByPhone": {"value": [{"statusCode": 401, "statusMessage": "x"}]}})
    with pytest.raises(LabSyncError) as caught:
        PARASKEVA.verify_code(URL, {"token": SESSION}, "123456", {"device_id": "d"}, "+380670000001")
    assert caught.value.key == "labsync.password_error_code"
    with pytest.raises(LabSyncError) as caught:
        PARASKEVA.verify_code(URL, {"token": SESSION}, "12", {"device_id": "d"}, "+380670000001")
    assert caught.value.key == "labsync.password_error_code"


def test_a_number_with_several_accounts_asks_which_one_then_signs_in_as_it(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("paraskeva",))

    def authorize(request, headers):
        values = params(request)
        if "OTPCode" not in values:
            return {"value": [{"statusCode": 200, "sessionGUID": SESSION}]}
        return {"value": [USER_ROW] if values.get("PatientID") == 101 else TWO_USERS}

    seen = install(monkeypatch, {"spiAnonymousAuthorizeByPhone": authorize}, token=TOKEN)
    assert labsync.save_credentials(settings, user_id, "paraskeva",
                                    {"phone": "0670000001"}) == "labsync.password_code_sent"
    assert labsync.save_credentials(settings, user_id, "paraskeva",
                                    {"code": "123456"}) == "labsync.sms_choose_person"
    pending = labsync.pending_code(user_id, "paraskeva")
    # "raw" is the id as the server typed it: sent back untouched, as the app does.
    assert pending["users"] == [{"id": "100", "raw": 100, "name": "Тестовий Тест Тестович"},
                                {"id": "101", "raw": 101, "name": "Тестова Дитина Тестівна"}]
    assert labsync.account(settings, user_id, "paraskeva") is None
    with pytest.raises(LabSyncError) as caught:
        labsync.save_credentials(settings, user_id, "paraskeva", {"patient": "999"})
    assert caught.value.key == "labsync.sms_error_person"
    assert labsync.save_credentials(settings, user_id, "paraskeva", {"patient": "101"}) == "labsync.saved_credentials"
    assert params(seen[-2][1]) == {"Phone": "+380670000001", "OTPCode": "123456", "SessionGUID": SESSION,
                                   "PatientID": 101}
    row = labsync.account(settings, user_id, "paraskeva")
    assert row["secret"] == ACCESS and SERVER_SECRET not in json.dumps(dict(row))
    assert labsync.pending_code(user_id, "paraskeva") is None


def test_the_people_on_the_account_and_token_renewal(monkeypatch):
    stale = json.dumps({"refresh": REFRESH, "login": "u100", "expires": "2000-01-01T00:00:00+00:00",
                        "device_id": "dev-1"})
    seen = install(monkeypatch, {
        "spiAnonymousTokenRefresh": {"value": [{"expires": "2100-01-01T00:00:00", "login": "u100",
                                                "accessToken": ACCESS2, "refreshToken": REFRESH2}]},
        "spiUserPatientDetails": lambda request, headers: DETAILS if ACCESS2 in headers["Authorization"] else 401,
    })
    client = PARASKEVA.Client(URL, ACCESS, "+380670000001", stale)
    people, expires = client.check()
    # The access token's time was up: renewed first, as the app does.
    assert seen[0][0] == "/api/va" and params(seen[0][1]) == {"RefreshToken": REFRESH}
    path, request, headers = seen[1]
    assert path == "/api/v" and headers["Authorization"] == f"Bearer {ACCESS2}"
    # Veselka's server refuses DeviceIdentifier on this procedure (2026-11-06).
    assert params(request) == {"Login": "u100", "DeviceInfoJson": None}
    assert client.secret == ACCESS2 and json.loads(client.refresh_secret)["refresh"] == REFRESH2
    assert expires is None
    assert [(p["id"], p["lastname"], p["firstname"], p["middlename"], p["birthday"], p["sex"], p["family_member_id"])
            for p in people] == [("p100", "Тестовий", "Тест", "Тестович", "1990-03-14", "male", 100),
                                 ("p101", "Тестова", "Дитина", "Тестівна", "2020-06-19", "female", 101)]
    assert all("phone" not in person for person in people)

    # A refused access token is renewed once; a refused renewal ends the session.
    fresh = json.dumps({"refresh": REFRESH, "login": "u100", "expires": "2100-01-01T00:00:00+00:00"})
    install(monkeypatch, {"spiUserPatientDetails": 401, "spiAnonymousTokenRefresh": 400})
    with pytest.raises(LabSyncError) as caught:
        PARASKEVA.Client(URL, ACCESS, "", fresh).check()
    assert caught.value.key == "labsync.error_auth"


@pytest.mark.parametrize("renewal", [
    # Veselka's server, live 2026-11-09: the procedure does not exist there.
    "Could not find stored procedure 'spiAnonymousTokenRefresh'.",
    # St. Paraskeva, a renewal token it no longer knows: a status row, no token.
    {"value": [{"statusCode": 401, "statusMessage": "!!"}]},
])
def test_a_clinic_that_cannot_renew_asks_for_a_new_sign_in(monkeypatch, renewal):
    stale = json.dumps({"refresh": REFRESH, "login": "u100", "expires": "2000-01-01T00:00:00+00:00"})
    seen = install(monkeypatch, {"spiAnonymousTokenRefresh": renewal, "spiUserPatientDetails": DETAILS})
    client = doctoreleks.CLINICS["veselka"].Client(URL, ACCESS, "", stale)
    with pytest.raises(LabSyncError) as caught:
        client.check()
    # "Sign in again", not "the clinic sent something unreadable" on every sync.
    assert caught.value.key == "labsync.error_auth"
    assert [entry[1]["name"] for entry in seen] == ["spiAnonymousTokenRefresh"]
    assert client.secret == ACCESS and json.loads(client.refresh_secret)["refresh"] == REFRESH


MENU = {"menu": [
    {"name": "Profile", "caption": "Профіль", "action": [{"name": "spzIBWPatientProfile", "params": {}}]},
    {"name": "Document", "caption": "Документи", "action": [{"name": "spzIBWDocumentList", "params": {}}]},
], "setting": {}, "header": {}, "backgroundActionList": []}


def tab(text: str, **values) -> dict:
    return {"text1": text, "cellTemplate": "CTTab",
            "action": [{"name": "spzIBWDocumentList", "params": values, "route": {"replace": "true"}}]}


def document(ident: str, title: str, *, stamp: str | None = None, printed: str = "") -> dict:
    """A list cell as both clinics send it: St. Paraskeva adds ``orderValue``,
    Veselka prints only the day in ``text1``."""
    cell = {"text1": printed, "text2": title, "text3": "Лікар Т. Т.", "cellTemplate": "CTListItem",
            "action": [{"name": "spzIBWDocumentView", "params": {"documentID": ident, "presentationName": "пац"}}]}
    return {**cell, "orderValue": stamp} if stamp else cell


TABS = [tab("Консультації", mode="Document", documentRoleRef="Веб доступ - Консультації"),
        tab("Лабораторія", mode="Document", documentRoleRef="Веб доступ - Лабораторія"),
        tab("Файли", mode="Files")]


def screen(*cells) -> dict:
    return {"view": [{"name": "TabContainer", "type": "HorizontalContainer", "data": TABS},
                     {"name": "List", "type": "List", "data": list(cells)}], "viewTemplate": None}


TAB_REPLIES = {
    "Веб доступ - Консультації": screen(
        document("2000161", "Консультація лікаря-кардіолога", printed="09.08.2026"),
        document("2000975", ".Форма № 003-6/о Інформована добровільна згода пацієнта", printed="09.08.2026")),
    "Веб доступ - Лабораторія": screen(
        document("4000786", "Загальний аналіз крові", stamp="2022-03-17T10:16:00.123", printed="17.03.2022, 10:16"),
        document("2000161", "Консультація лікаря-кардіолога", printed="09.08.2026")),  # listed twice: one order
    "Files": screen({"text1": "Завантажити ПДФ документ", "cellTemplate": "CTListItem",
                     "action": [{"name": "selectPdfFromDevice", "params": {}}]}, {"cellTemplate": "CTSpace"}),
}


def document_list(request, headers):
    values = params(request)
    return TAB_REPLIES[values.get("DocumentRoleRef") or values.get("Mode") or "Веб доступ - Консультації"]


def document_view(ident: str, url: str) -> dict:
    return {"view": [
        {"name": "NavigationBar", "type": "NavigationBar", "data": [
            {"icon3": "MaterialIcons:share", "cellTemplate": "CTIcon",
             "action": [{"name": "shareRemoteFile", "params": {"title": "Share Doc", "url": url}}]}]},
        {"name": "DocumentViewer", "type": "WebView", "data": [],
         "settings": {"documentId": ident, "presentationName": "пац", "iosUrl": url}},
    ], "viewTemplate": None}


def file_url(ident: str) -> str:
    return f"{URL}/api/document?request=ZG9j{ident}&installationID={TENANT}"


FILES = {"4000786": PDF, "2000161": PDF_2}
SIGNED_IN = json.dumps({"refresh": REFRESH, "login": "100110", "expires": "2100-01-01T00:00:00+00:00",
                        "device_id": "dev-1"})


def documents_flow() -> dict:
    return {"spzIBWApplicationDetails": MENU, "spzIBWDocumentList": document_list,
            "spzIBWDocumentView": lambda request, headers: document_view(
                params(request)["DocumentID"], file_url(params(request)["DocumentID"])),
            **{file_url(ident): body for ident, body in FILES.items()}}


def test_documents_follow_the_server_menu_through_every_tab(monkeypatch):
    """Live, both clinics, 2026-11-06: the menu names the documents screen
    (each clinic its own procedure), its tabs are calls of that procedure,
    and a document is a cell whose action opens ``spzIBWDocumentView``."""
    seen = install(monkeypatch, documents_flow())
    client = PARASKEVA.Client(URL, ACCESS, "", SIGNED_IN)
    orders = client.orders({"id": "u1", "main": True})
    assert [(o["order_id"], o["ordered_at"], o["dates"], o["packet"], o["complete"], o["rows"]) for o in orders] == [
        ("2000161", "2026-08-09", ["2026-08-09"], "Консультація лікаря-кардіолога", True, []),
        ("4000786", "2022-03-17 10:16", ["2022-03-17"], "Загальний аналіз крові", True, []),
    ]  # the blank consent form, the upload button and the second listing are not documents
    calls = [(request["name"], params(request)) for _, request, _ in seen]
    assert calls[0] == ("spzIBWApplicationDetails", {"Login": "100110", "DeviceIdentifier": "dev-1"})
    # Each tab's params as actionXml writes them (the reply lowers their first letter).
    assert ("spzIBWDocumentList", {"Login": "100110", "Mode": "Document",
                                   "DocumentRoleRef": "Веб доступ - Лабораторія"}) in calls
    assert ("spzIBWDocumentList", {"Login": "100110", "Mode": "Files"}) in calls
    assert client.rows(orders[1], {}) == []

    seen.clear()
    assert client.pdfs(orders[1], {"id": "u1"}) == [PDF]
    view, fetch = seen
    assert params(view[1]) == {"Login": "100110", "DocumentID": "4000786", "PresentationName": "пац"}
    assert fetch[0] == "GET" and "Authorization" not in fetch[2]  # the app opens the file with a plain GET


def test_a_document_url_off_the_clinic_server_or_a_missing_menu_is_refused(monkeypatch, caplog):
    flow = {**documents_flow(), "spzIBWDocumentView": document_view("1", "https://elsewhere.example/a.pdf")}
    install(monkeypatch, flow)
    client = PARASKEVA.Client(URL, ACCESS, "", SIGNED_IN)
    with pytest.raises(LabSyncError) as caught:
        client.pdfs({"order_id": "1"}, {})
    assert caught.value.key == "labsync.error_pdf"
    install(monkeypatch, {"spzIBWApplicationDetails": {"menu": [{"name": "Profile", "action": []}]}})
    with pytest.raises(LabSyncError) as caught, caplog.at_level("WARNING"):
        client.orders({"id": "u1", "main": True})
    assert caught.value.key == "labsync.doctoreleks_error_unmapped" in labsync.ERROR_KEYS
    assert "no documents menu" in caplog.text


def test_a_family_member_without_a_card_switcher_is_refused_rather_than_given_the_holders_documents(monkeypatch):
    """The list takes no person (``@PatientID is not a parameter``): it is the active card's."""
    seen = install(monkeypatch, documents_flow())
    with pytest.raises(LabSyncError) as caught:
        PARASKEVA.Client(URL, ACCESS, "", SIGNED_IN).orders({"id": "p101", "main": False})
    assert caught.value.key == "labsync.doctoreleks_error_unmapped"
    assert not any(request["name"] in ("spzIBWDocumentView", "spiSelectedPatientSave")
                   for _, request, _ in seen if isinstance(request, dict))


SWITCHER = {"text1": "Тестовий Тест Тестович (активна мед-карта)", "cellTemplate": "CTListItem",
            "action2": [{"name": "spzIBWProfileSelectPopup", "viewMode": "popup",
                         "params": {"backActionXml": "^^^action%%%^^^name%%%spzIBWDocumentList^^^/name%%%"}}]}


def card(ident: str, name: str, born: str, group: str, image: str) -> dict:
    return {"image_1_1": image, "text_2_1": name, "text_2_2": born, "groupValue": group, "cellTemplate": "CTCard",
            "action": [{"name": "spzIBWPatientRoleSelectConfirm", "viewMode": "popup",
                        "params": {"backActionXml": "x", "patientID": ident}}]}


def switcher_flow(active: list, fail_reading: bool = False) -> dict:
    """St. Paraskeva, 2026-11-06: the documents screen's active-card row opens
    the card switcher; a card's confirmation screen saves the choice."""
    def documents(request, headers):
        if fail_reading and active[-1] == "101":
            return 500
        reply = document_list(request, headers)
        mine = active[-1] == "100"
        cells = reply["view"][1]["data"] if mine else [document("7001", "Загальний аналіз крові", printed="01.02.2024")]
        return {"view": [reply["view"][0], {"name": "Person", "type": "VerticalContainer", "data": [SWITCHER]},
                         {"name": "List", "type": "List", "data": cells}], "viewTemplate": None}

    def save(request, headers):
        active.append(str(params(request)["SelectedPatientID"]))
        return {"value": [{"Message": "ok"}]}

    def confirm(request, headers):
        ident = params(request)["PatientID"]
        return {"view": [{"name": "Bottom", "type": "List", "data": [
            {"text3": "Ви впевнені, що хочете вибрати цього пацієнта?", "cellTemplate": "CTText"},
            {"text1": "Так", "cellTemplate": "CTButton", "action": [
                {"name": "spiSelectedPatientSave", "params": {"selectedPatientID": ident, "platform": "mobile"}},
                {"name": "notify", "params": {"text": "{{Message}}"}}, {"name": "spzIBWDocumentList"}]},
            {"text1": "Ні", "cellTemplate": "CTButton", "action": [{"name": "spzIBWDocumentList", "params": {}}]},
        ]}]}

    def popup(request, headers):
        mark = {ident: " (активний)" if active[-1] == ident else "" for ident in ("100", "101")}
        return {"view": [{"name": "List", "type": "List", "data": [
            card("100", "Тестовий Тест Тестович" + mark["100"], "14.03.1990", "Власний профіль ", "res:male"),
            card("101", "Тестова Мама Тестівна" + mark["101"], "22.03.1958", "Перелік доступних профілів ",
                 "https://portal-doctor.eleks.com/api/file?thumbnail=1"),
        ]}]}

    return {**documents_flow(), "spzIBWDocumentList": documents, "spzIBWProfileSelectPopup": popup,
            "spzIBWPatientRoleSelectConfirm": confirm, "spiSelectedPatientSave": save,
            "spiUserPatientDetails": {"value": {"user": {"userLogin": "100110"}, "patientList": []}},
            file_url("7001"): PDF}


def test_family_cards_are_the_people_and_each_is_read_with_its_card_made_active(monkeypatch):
    active = ["100"]
    seen = install(monkeypatch, switcher_flow(active))
    client = PARASKEVA.Client(URL, ACCESS, "", SIGNED_IN)
    people, _ = client.check()
    assert [(p["id"], p["main"], p["lastname"], p["firstname"], p["middlename"], p["birthday"], p["sex"])
            for p in people] == [("p100", True, "Тестовий", "Тест", "Тестович", "1990-03-14", "male"),
                                 ("p101", False, "Тестова", "Мама", "Тестівна", "1958-03-22", None)]
    assert active == ["100"]  # listing the people switches nothing

    # The active card's own documents: read in place, nothing switched.
    assert [o["order_id"] for o in client.orders(people[0])] == ["2000161", "4000786"] and active == ["100"]

    seen.clear()
    mother = client.orders(people[1])
    assert [(o["order_id"], o["dates"], o["url"]) for o in mother] == [("7001", ["2024-02-01"], file_url("7001"))]
    assert active == ["100", "101", "100"]  # switched for the read, then put back
    saves = [params(request) for _, request, _ in seen if isinstance(request, dict)
             and request.get("name") == "spiSelectedPatientSave"]
    assert saves == [{"Login": "100110", "SelectedPatientID": "101", "Platform": "mobile"},
                     {"Login": "100110", "SelectedPatientID": "100", "Platform": "mobile"}]
    # The file was located while her card was active; fetching it switches nothing.
    assert client.pdfs(mother[0], people[1]) == [PDF] and active == ["100", "101", "100"]


def test_a_failed_family_read_still_puts_the_active_card_back(monkeypatch):
    active = ["100"]
    install(monkeypatch, switcher_flow(active, fail_reading=True))
    client = PARASKEVA.Client(URL, ACCESS, "", SIGNED_IN)
    with pytest.raises(LabSyncError):
        client.orders({"id": "p101", "main": False})
    assert active == ["100", "101", "100"]


def test_sync_imports_each_pdf_once_and_links_one_uploaded_by_hand(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("paraskeva",))
    flow = {"spiAnonymousAuthorizeByPhone": lambda request, headers: {"value": [
        {"statusCode": 200, "sessionGUID": SESSION}] if "OTPCode" not in params(request) else [USER_ROW]},
        "spiUserPatientDetails": DETAILS}
    install(monkeypatch, flow, token=TOKEN)
    labsync.save_credentials(settings, user_id, "paraskeva", {"phone": "0670000001"})
    labsync.save_credentials(settings, user_id, "paraskeva", {"code": "123456"})
    people = labsync.check_account(settings, user_id, "paraskeva")
    assert [(p["id"], p["main"]) for p in people] == [("p100", True), ("p101", False)]
    labsync.link_person(settings, user_id, "paraskeva", "p100", "self", confirmed=False)
    # The cardiology report was uploaded by hand before: the very same file.
    uploaded = seed_doc(settings, user_id, vendor="St. Paraskeva Medical Center", order=None, day="2026-08-09",
                        values=[])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET sha256=? WHERE id=?", (hashlib.sha256(PDF_2).hexdigest(), uploaded))
    calls = stub_intake(monkeypatch, settings, user_id, {
        "paraskeva-4000786 2022-03-17 Загальний аналіз крові.pdf": {"vendor": "St. Paraskeva Medical Center", "order": None, "day": "2022-03-17",
                                  "values": [("Гемоглобін", 152.0, "г/л", "within_vendor_range")]}})
    install(monkeypatch, {**flow, **documents_flow()})
    summary = labsync.sync(settings, user_id, "paraskeva", inline=True)
    assert calls == ["paraskeva-4000786 2022-03-17 Загальний аналіз крові.pdf"]
    assert (summary["imported"], summary["linked"], summary["failed"]) == (1, 1, 0)
    with connect(settings) as connection:
        states = dict(connection.execute(
            "SELECT order_id, state FROM lab_orders WHERE provider='paraskeva'").fetchall())
        linked = connection.execute("SELECT document_id FROM lab_orders WHERE order_id='2000161'").fetchone()[0]
    assert states == {"4000786": "imported", "2000161": "linked"} and linked == uploaded
    again = labsync.sync(settings, user_id, "paraskeva", inline=True)
    assert again["already"] == 2 and calls == ["paraskeva-4000786 2022-03-17 Загальний аналіз крові.pdf"]


def test_a_person_the_account_no_longer_lists_frees_the_record_it_held(tmp_path: Path, monkeypatch):
    """Veselka, 2026-11-06: a sign-in under the wrong login listed a blank
    person, linked to the holder; signed in properly, the real person could
    not be given the holder's record.  A refreshed list drops a link with no
    history; a link with orders stays, so a reconnect never re-imports."""
    settings, user_id, _ = make(tmp_path, enable=("paraskeva",))
    flow = {"spiAnonymousAuthorizeByPhone": lambda request, headers: {"value": [
        {"statusCode": 200, "sessionGUID": SESSION}] if "OTPCode" not in params(request) else [USER_ROW]},
        "spiUserPatientDetails": DETAILS}
    install(monkeypatch, flow, token=TOKEN)
    labsync.save_credentials(settings, user_id, "paraskeva", {"phone": "0670000001"})
    labsync.save_credentials(settings, user_id, "paraskeva", {"code": "123456"})
    labsync.check_account(settings, user_id, "paraskeva")
    labsync.link_person(settings, user_id, "paraskeva", "p101", "self", confirmed=True)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO lab_orders(owner_user_id, account_user_id, provider, remote_person_id, order_id, state,
                   first_seen_at, last_synced_at) VALUES (?, ?, 'paraskeva', 'p101', '1', 'imported', 'x', 'x')""",
            (user_id, user_id))
        connection.execute(
            """INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json,
                   target_user_id, consent, created_at, updated_at)
               VALUES (?, 'paraskeva', 'u-blank', '{}', ?, 'owner', 'x', 'x')""", (user_id, user_id))
    only_main = {"value": {"user": {"login": "u100"}, "patientList": [DETAILS["value"]["patientList"][1]]}}
    install(monkeypatch, {**flow, "spiUserPatientDetails": only_main})
    assert [p["id"] for p in labsync.check_account(settings, user_id, "paraskeva")] == ["p100"]
    with connect(settings) as connection:
        kept = [row[0] for row in connection.execute(
            "SELECT remote_person_id FROM lab_person_links WHERE provider='paraskeva' ORDER BY 1")]
    assert kept == ["p101"]  # the blank person is gone; p101 left the account but has history


def test_profile_asks_for_phone_and_code_only_in_both_languages(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("paraskeva", "veselka"))
    page = client.get("/profile?tab=connections").text
    card = page[page.index('id="lab-paraskeva"'):page.index('id="lab-veselka"')]
    assert 'name="phone" type="tel"' in card and 'type="password"' not in card
    assert "the code the clinic texts to it" in card and "Text me a code" in card
    install(monkeypatch, {"spiAnonymousAuthorizeByPhone": lambda request, headers: {"value": [
        {"statusCode": 200, "sessionGUID": SESSION}] if "OTPCode" not in params(request) else TWO_USERS}})
    token = csrf(settings, user_id)
    sent = client.post("/profile/lab/paraskeva/credentials", data={"phone": "067 000 00 01", "csrf_token": token},
                       follow_redirects=False)
    assert "lab_msg=labsync.password_code_sent" in sent.headers["location"]
    assert 'autocomplete="one-time-code"' in client.get(sent.headers["location"]).text
    chosen = client.post("/profile/lab/paraskeva/credentials", data={"code": "123456", "csrf_token": token},
                         follow_redirects=False)
    assert "lab_msg=labsync.sms_choose_person" in chosen.headers["location"]
    page = client.get(chosen.headers["location"]).text
    assert 'type="radio" name="patient" value="101"' in page and "Тестова Дитина Тестівна" in page
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/profile?tab=connections").text
    assert "Веселка" in page and "Отримати код у SMS" in page
    assert "До цього номера в клініці прив’язано кілька облікових записів" not in page  # message only after the redirect
    assert "Підключити цей обліковий запис" in page


def test_admin_lists_both_clinics_off_with_the_texted_code_note(tmp_path: Path):
    settings, user_id, client = make(tmp_path, enable=())
    page = client.get("/admin/lab-connections").text
    for key in ("paraskeva", "veselka"):
        section = page[page.index(f'id="lab-admin-{key}"'):]
        section = section[:section.index("</section>")]
        assert ">off<" in section
        assert 'placeholder="https://portal-doctor.eleks.com"' in section
    assert labsync.active_providers(settings) == []
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/admin/lab-connections").text
    assert "Медичний центр Святої Параскеви" in page



def test_an_account_without_a_patient_list_is_its_own_person(monkeypatch):
    """Veselka, live 2026-11-06: patientList empty, the signed-in login is the person."""
    fresh = json.dumps({"refresh": REFRESH, "login": "u7", "expires": "2100-01-01T00:00:00+00:00", "device_id": "d"})
    install(monkeypatch, {**documents_flow(), "spiUserPatientDetails": {"value": {"user": {
        "userName": "", "userLogin": "u7", "userImage": "", "userBirthDate": "", "userPhoneNumber": ""},
        "patientList": [], "userAlias": []}}})  # and no card switcher on the documents screen
    people, _ = PARASKEVA.Client(URL, ACCESS, "+380670000001", fresh).check()
    assert len(people) == 1 and people[0]["id"].startswith("u") and people[0]["family_member_id"] is None


def test_a_sentence_from_the_server_is_logged_by_shape_and_reported(monkeypatch, caplog):
    """The server answers a bad call with text, not data; it must say what, with no values."""
    fresh = json.dumps({"refresh": REFRESH, "login": "u7", "expires": "2100-01-01T00:00:00+00:00", "device_id": "d"})
    install(monkeypatch, {"spiUserPatientDetails": "@Foo is not a parameter for procedure spiUserPatientDetails."})
    with pytest.raises(LabSyncError) as caught, caplog.at_level("WARNING"):
        PARASKEVA.Client(URL, ACCESS, "+380670000001", fresh).check()
    assert caught.value.key == "labsync.error_reply"
    assert "is not a parameter for procedure spiUserPatientDetails" in caplog.text


def test_a_chosen_person_without_a_renewal_token_still_signs_in(tmp_path: Path, monkeypatch):
    """St. Paraskeva, live 2026-11-06: after the person is chosen neither the row
    nor the token reply carries a renewal token, and the token reply names its
    own login.  The app signs in with that login and simply signs in again
    once the access token's time is up."""
    settings, user_id, _ = make(tmp_path, enable=("paraskeva",))
    chosen = {key: value for key, value in USER_ROW.items() if key != "refreshToken"}

    def authorize(request, headers):
        values = params(request)
        if "OTPCode" not in values:
            return {"value": [{"statusCode": 200, "sessionGUID": SESSION}]}
        return {"value": [chosen] if values.get("PatientID") == 101 else TWO_USERS}

    token = {**TOKEN, "login": "p101x"}
    token.pop("refresh_token", None)
    install(monkeypatch, {"spiAnonymousAuthorizeByPhone": authorize}, token=token)
    labsync.save_credentials(settings, user_id, "paraskeva", {"phone": "0670000001"})
    labsync.save_credentials(settings, user_id, "paraskeva", {"code": "123456"})
    assert labsync.save_credentials(settings, user_id, "paraskeva", {"patient": "101"}) == "labsync.saved_credentials"
    row = labsync.account(settings, user_id, "paraskeva")
    kept = json.loads(row["refresh_secret"])
    assert row["secret"] == ACCESS and kept["refresh"] == "" and kept["login"] == "p101x"
    assert row["secret_expires_at"], "without a renewal token the access expiry is when to sign in again"


def test_a_clinic_re_export_of_a_hand_upload_is_linked_and_set_aside(tmp_path: Path, monkeypatch):
    """Veselka, 2026-11-06: the clinic's PDF of an ultrasound uploaded by hand
    is other bytes with the same words.  Once read, the pipeline relates the
    two as duplicates; the order then links the earlier upload and the new
    file becomes its copy, so the record does not show the report twice."""
    settings, user_id, _ = make(tmp_path, enable=("paraskeva",))
    flow = {"spiAnonymousAuthorizeByPhone": lambda request, headers: {"value": [
        {"statusCode": 200, "sessionGUID": SESSION}] if "OTPCode" not in params(request) else [USER_ROW]},
        "spiUserPatientDetails": DETAILS}
    install(monkeypatch, flow, token=TOKEN)
    labsync.save_credentials(settings, user_id, "paraskeva", {"phone": "0670000001"})
    labsync.save_credentials(settings, user_id, "paraskeva", {"code": "123456"})
    labsync.check_account(settings, user_id, "paraskeva")
    labsync.link_person(settings, user_id, "paraskeva", "p100", "self", confirmed=False)
    by_hand = seed_doc(settings, user_id, vendor="St. Paraskeva Medical Center", order=None, day="2026-08-09",
                       values=[])
    produced = {name: {"vendor": "St. Paraskeva Medical Center", "order": None, "day": day, "values": []}
                for name, day in (("paraskeva-2000161 2026-08-09 Консультація лікаря-кардіолога.pdf", "2026-08-09"),
                                  ("paraskeva-4000786 2022-03-17 Загальний аналіз крові.pdf", "2022-03-17"))}
    calls = stub_intake(monkeypatch, settings, user_id, produced)
    enqueue = labsync.intake.enqueue

    def read_as_the_pipeline_would(settings_, **kwargs):
        job_id = enqueue(settings_, **kwargs)
        if "2000161" in kwargs["filename"]:
            with connect(settings) as connection:
                new = connection.execute("SELECT document_id FROM upload_jobs WHERE id=?", (job_id,)).fetchone()[0]
                connection.execute("UPDATE documents SET imported_at='2999-01-01T00:00:00+00:00' WHERE id=?", (new,))
                connection.execute(
                    """INSERT INTO document_relations(source_document_id, target_document_id, relationship,
                           confidence, notes) VALUES (?, ?, 'duplicate', 0.9, 'auto:same_text')""", (new, by_hand))
        return job_id

    monkeypatch.setattr(labsync.intake, "enqueue", read_as_the_pipeline_would)
    install(monkeypatch, {**flow, **documents_flow()})
    summary = labsync.sync(settings, user_id, "paraskeva", inline=True)
    assert len(calls) == 2 and (summary["imported"], summary["linked"]) == (1, 1)
    with connect(settings) as connection:
        linked = connection.execute("SELECT document_id FROM lab_orders WHERE order_id='2000161'").fetchone()[0]
        copies = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE duplicate_of_document_id=?", (by_hand,)).fetchone()[0]
    assert linked == by_hand and copies == 1

