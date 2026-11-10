"""Expert Hospital: phone + password sign-in, texted code, token
refresh, and reading analyses — all against synthetic replies shaped like the
models decompiled from the Android app (see labsync/expert.py).  HTTP is
stubbed at ``labsync.common._http``, as for the other labs."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.labsync import LabSyncError, common, expert

from test_labsync import csrf, make, router, stub_intake

URL = "http://127.0.0.1:9"
PASSWORD = "synthetic-pass-1"
# JWT-shaped; the refresh token's payload carries exp 4102444800 (2100-01-01).
ACCESS = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.YWNjZXNzLXNpZ25hdHVyZQ"
ACCESS2 = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIyIn0.YWNjZXNzLXNpZ25hdHVyZTI"
REFRESH = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIiwiZXhwIjo0MTAyNDQ0ODAwfQ.cmVmcmVzaA"
REFRESH2 = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIyIiwiZXhwIjo0MTAyNDQ0ODAwfQ.cmVmcmVzaDI"
TOKENS = {"access_token": ACCESS, "refresh_token": REFRESH, "token_type": "bearer", "user_id": 7,
          "phone": "+380000000001", "trusted_device_token": "trusted-device-token-0001",
          "needs_profile_completion": False}
CHALLENGE = {"two_factor_required": True, "method": "sms", "challenge_token": "challenge-token-0001",
             "phone_masked": "+380*****0001", "expires_in": 300, "code_length": 6}
PROFILE = {"profile": {"id": 41, "user_id": 7, "first_name": "Test", "last_name": "Person", "middle_name": None,
                       "dob": "1990-03-14", "gender": "male", "is_linked_to_medeir": True, "qr_code": "x",
                       "medeir_patient_id": 5, "address": "nowhere"},
           "phone": "+380000000001", "email": "a@example.test", "family_members_count": 2}
FAMILY = {"items": [
    {"id": 12, "profile_id": 99, "first_name": "Kid", "last_name": "Person", "dob": "19.06.2020",
     "gender": "female", "relationship_type": "child", "is_linked_to_medeir": True},
    {"id": 13, "profile_id": 98, "first_name": "New", "last_name": "Person", "dob": None,
     "gender": None, "relationship_type": "spouse", "is_linked_to_medeir": False},
], "total": 2}
ANALYSES = {"items": [
    {"id": 501, "name": "Загальний аналіз крові", "category": "lab", "status": "Готово", "status_code": "done",
     "date": "2025-09-16T08:10:00", "result_date": "2025-09-16T14:00:00", "has_file": True,
     "has_abnormal_results": True},
    {"id": 502, "name": "Феритин", "status": "В роботі", "date": "2025-11-05T09:00:00", "has_file": False},
], "total": 2, "skip": 0, "limit": 50, "has_more": False}
ANALYSIS_501 = {**ANALYSES["items"][0], "indicators": [
    {"id": 1, "name": "Гемоглобін", "value": "151", "unit": "г/л", "reference_min": "130",
     "reference_max": "170", "reference_text": None, "is_abnormal": False, "note": None},
    {"id": 2, "name": "Лейкоцити", "value": "11.2", "unit": "10^9/л", "reference_min": None,
     "reference_max": "9.0", "reference_text": None, "is_abnormal": True},
    {"id": 3, "name": "ШОЕ", "value": "4", "unit": "мм/год", "reference_min": "2", "reference_max": None,
     "is_abnormal": False},
    {"id": 4, "name": "Колір", "value": "жовтий", "unit": None, "reference_text": "світло-жовтий, жовтий",
     "is_abnormal": False},
]}


def body(raw: bytes | None) -> dict:
    return json.loads(raw.decode()) if raw else {}


#: A person with no visit documents: the two lists beside analyses, empty.
NO_DOCUMENTS = {("GET", f"/api/v1/medical/{kind}"): {"items": [], "total": 0, "has_more": False}
                for kind in ("conclusions", "research")}


def install(monkeypatch, routes: dict, seen: list | None = None) -> list:
    seen = [] if seen is None else seen
    monkeypatch.setattr(common, "_http", router({**NO_DOCUMENTS, **routes}, seen))
    return seen


def capture(store: list, reply):
    def handler(raw, headers):
        store.append((body(raw), headers))
        return reply(raw, headers) if callable(reply) else reply
    return handler


def test_phone_is_normalised_the_way_the_app_sends_it():
    for typed in ("671234567", "0671234567", "+38 (067) 123 45 67", "380671234567", "+380 67 123 45 67"):
        assert expert.normalize_phone(typed) == "+380671234567"
    for bad in ("", "12345", "+48 601 234 567", "06712345678"):
        with pytest.raises(LabSyncError) as caught:
            expert.normalize_phone(bad)
        assert caught.value.key == "labsync.password_error_phone"


def test_sign_in_sends_the_app_fields_and_keeps_only_tokens(monkeypatch):
    sent: list = []
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, TOKENS)})
    state = {"device_id": "00000000-0000-4000-8000-000000000001", "trusted": None}
    creds = expert.start_sign_in(URL, "67 000 00 01", PASSWORD, state)
    payload, headers = sent[0]
    assert payload == {"phone": "+380670000001", "password": PASSWORD, "device_id": state["device_id"],
                       "device_name": "Anamna", "platform": "android", "trusted_device_token": None}
    assert "Authorization" not in headers
    assert creds["secret"] == ACCESS and creds["phone"] == "+380670000001"
    assert creds["expires_at"].startswith("2100-01-01")
    kept = json.loads(creds["refresh_secret"])
    assert kept == {"refresh": REFRESH, "device_id": state["device_id"], "trusted": "trusted-device-token-0001"}
    assert PASSWORD not in json.dumps(creds)


def test_wrong_password_wrong_code_and_throttling_say_what_to_do(monkeypatch):
    install(monkeypatch, {("POST", "/api/v1/auth/login"): 401, ("POST", "/api/v1/auth/2fa/verify"): 400})
    state = {"device_id": "00000000-0000-4000-8000-000000000001"}
    with pytest.raises(LabSyncError) as caught:
        expert.start_sign_in(URL, "0670000001", PASSWORD, state)
    assert caught.value.key == "labsync.password_error_invalid"
    with pytest.raises(LabSyncError) as caught:
        expert.verify_code(URL, {"token": "challenge-token-0001"}, "123456", state, "+380670000001")
    assert caught.value.key == "labsync.password_error_code"
    install(monkeypatch, {("POST", "/api/v1/auth/login"): 429})
    with pytest.raises(LabSyncError) as caught:
        expert.start_sign_in(URL, "0670000001", PASSWORD, state)
    assert caught.value.key == "labsync.password_error_throttled"


def test_texted_code_flow_stores_tokens_never_the_password(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("expert",))
    sent: list = []
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, CHALLENGE),
                          ("POST", "/api/v1/auth/2fa/verify"): capture(sent, TOKENS)})
    assert labsync.save_credentials(settings, user_id, "expert",
                                    {"phone": "0670000001", "password": PASSWORD}) == "labsync.password_code_sent"
    assert labsync.pending_code(user_id, "expert") == {"phone_masked": "+380*****0001", "code_length": 6}
    assert labsync.account(settings, user_id, "expert") is None  # nothing stored before the code
    assert labsync.save_credentials(settings, user_id, "expert", {"code": "123 456"}) == "labsync.saved_credentials"
    verify = sent[1][0]
    assert verify["challenge_token"] == "challenge-token-0001" and verify["code"] == "123456"
    assert verify["device_id"] == sent[0][0]["device_id"] and verify["fcm_token"] is None
    row = labsync.account(settings, user_id, "expert")
    assert row["secret"] == ACCESS and row["phone"] == "+380670000001"
    assert json.loads(row["refresh_secret"])["refresh"] == REFRESH
    assert PASSWORD not in json.dumps(dict(row))
    assert labsync.pending_code(user_id, "expert") is None
    with pytest.raises(LabSyncError) as caught:  # a code with no step waiting
        labsync.save_credentials(settings, user_id, "expert", {"code": "123456"})
    assert caught.value.key == "labsync.password_error_code_expired"

    # Forgetting drops the tokens and the trusted-device token, but keeps the
    # device id, so the lab still knows the device; the next sign-in sends no
    # trusted-device token and the lab asks for its code again.
    labsync.forget(settings, user_id, "expert")
    row = labsync.account(settings, user_id, "expert")
    assert row["secret"] == "" and json.loads(row["refresh_secret"]) == {"device_id": sent[0][0]["device_id"]}
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, TOKENS)})
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    assert sent[-1][0]["trusted_device_token"] is None
    assert sent[-1][0]["device_id"] == sent[0][0]["device_id"]


def test_an_expired_access_token_is_refreshed_once_and_the_new_pair_kept(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("expert",))
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS})
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    refreshed: list = []

    def profile(raw, headers):
        return PROFILE if headers["Authorization"] == f"Bearer {ACCESS2}" else 401

    install(monkeypatch, {
        ("GET", "/api/v1/profile"): profile,
        ("GET", "/api/v1/profile/family"): lambda raw, headers: FAMILY if ACCESS2 in headers["Authorization"] else 401,
        ("POST", "/api/v1/auth/refresh"): capture(refreshed, {"access_token": ACCESS2, "refresh_token": REFRESH2,
                                                              "token_type": "bearer"}),
    })
    people = labsync.check_account(settings, user_id, "expert")
    assert refreshed[0][0] == {"refresh_token": REFRESH}
    row = labsync.account(settings, user_id, "expert")
    assert row["secret"] == ACCESS2 and json.loads(row["refresh_secret"])["refresh"] == REFRESH2
    assert [(p["id"], p["birthday"], p["sex"]) for p in people] == [
        ("p41", "1990-03-14", "male"), ("f12", "2020-06-19", "female"), ("f13", "", "")]
    assert all("phone" not in person and "qr_code" not in person for person in people)

    # The lab ends the session: the refresh is refused and the person is told to reconnect.
    install(monkeypatch, {("GET", "/api/v1/profile"): 401, ("POST", "/api/v1/auth/refresh"): 401})
    with pytest.raises(LabSyncError) as caught:
        labsync.check_account(settings, user_id, "expert")
    assert caught.value.key == "labsync.error_auth"


def test_a_profile_the_hospital_has_not_linked_gets_its_own_explanation(monkeypatch):
    install(monkeypatch, {("GET", "/api/v1/profile"): 403})
    with pytest.raises(LabSyncError) as caught:
        expert.Client(URL, ACCESS, "", json.dumps({"refresh": REFRESH})).check()
    assert caught.value.key == "labsync.expert_error_forbidden"


def test_analyses_become_orders_and_indicators_become_lab_rows(monkeypatch):
    seen = install(monkeypatch, {
        ("GET", "/api/v1/medical/analyses"): ANALYSES,
        ("GET", "/api/v1/medical/analyses/501"): ANALYSIS_501,
        ("GET", "/api/v1/medical/analyses/501/file"): b"%PDF-1.4 synthetic\n%%EOF",
    })
    client = expert.Client(URL, ACCESS, "", "")
    kid = {"id": "f12", "family_member_id": 12}
    orders = client.orders(kid)
    assert seen[0][1] == "/api/v1/medical/analyses?family_member_id=12"
    first, second = orders
    assert (first["order_id"], first["complete"], first["dates"], first["ordered_at"]) == (
        "501", True, ["2025-09-16"], "2025-09-16 08:10")
    assert second["complete"] is False and second["lab_status"] == "В роботі"
    rows = client.rows(first, kid)
    assert seen[-1][1] == "/api/v1/medical/analyses/501?family_member_id=12"
    assert (first["ready"], first["total"]) == (4, 4)
    by_name = {row["test"]: row for row in rows}
    assert by_name["Гемоглобін"]["norm"] == ["130 - 170"] and by_name["Гемоглобін"]["state"] == "normal"
    assert by_name["Лейкоцити"]["norm"] == ["≤ 9"] and by_name["Лейкоцити"]["state"] == "critical"
    assert by_name["ШОЕ"]["norm"] == ["≥ 2"]
    assert by_name["Колір"]["norm"] == ["світло-жовтий, жовтий"] and by_name["Колір"]["units"] == ""
    assert all(row["packet"] == "Загальний аналіз крові" for row in rows)
    assert client.pdfs(first, {"id": "p41", "family_member_id": None}) == [b"%PDF-1.4 synthetic\n%%EOF"]
    assert seen[-1][1] == "/api/v1/medical/analyses/501/file"
    # ``is_linked_to_medeir: false`` is no gate: a live account said so and
    # still listed its analyses, so every person is asked.
    client.orders({"id": "f13", "family_member_id": 13})
    assert [path for _, path, _ in seen[-3:]] == [
        f"/api/v1/medical/{kind}?family_member_id=13" for kind in ("analyses", "conclusions", "research")]


def test_sync_imports_a_finished_analysis_and_waits_for_the_rest(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("expert",))
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS,
                          ("GET", "/api/v1/profile"): PROFILE, ("GET", "/api/v1/profile/family"): FAMILY})
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    labsync.check_account(settings, user_id, "expert")
    labsync.link_person(settings, user_id, "expert", "p41", "self", confirmed=False)
    calls = stub_intake(monkeypatch, settings, user_id, {
        "expert-501.pdf": {"vendor": "Expert Hospital", "order": None, "day": "2025-09-16",
                            "values": [("Гемоглобін", 151.0, "г/л", "within_vendor_range"),
                                       ("Лейкоцити", 11.2, "10^9/л", "high")]},
    })
    install(monkeypatch, {
        ("GET", "/api/v1/medical/analyses"): ANALYSES,
        ("GET", "/api/v1/medical/analyses/501"): ANALYSIS_501,
        ("GET", "/api/v1/medical/analyses/502"): {**ANALYSES["items"][1], "indicators": []},
        ("GET", "/api/v1/medical/analyses/501/file"): b"%PDF-1.4 synthetic\n%%EOF",
    })
    summary = labsync.sync(settings, user_id, "expert", inline=True)
    assert calls == ["expert-501.pdf"]
    assert (summary["imported"], summary["pending"], summary["failed"]) == (1, 1, 0)
    with connect(settings) as connection:
        states = dict(connection.execute(
            "SELECT order_id, state FROM lab_orders WHERE provider='expert'").fetchall())
    assert states == {"501": "imported", "502": "pending"}
    assert summary["crosscheck"]["match"] >= 2
    again = labsync.sync(settings, user_id, "expert", inline=True)
    assert calls == ["expert-501.pdf"] and again["imported"] == 0


def test_profile_offers_phone_and_password_then_the_code_in_both_languages(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("expert",))
    page = client.get("/profile?tab=connections").text
    card = page[page.index('id="lab-expert"'):]
    assert 'name="password" type="password"' in card and 'autocomplete="current-password"' in card
    assert "only to the lab&#39;s own server (http://127.0.0.1:9)" in card
    assert "Developer tools" not in card  # nothing to copy from a browser
    form = {"phone": "067 000 00 01", "password": PASSWORD}
    assert client.post("/profile/lab/expert/credentials", data=form, follow_redirects=False).status_code == 403
    install(monkeypatch, {("POST", "/api/v1/auth/login"): CHALLENGE, ("POST", "/api/v1/auth/2fa/verify"): TOKENS,
                          ("GET", "/api/v1/profile"): PROFILE, ("GET", "/api/v1/profile/family"): FAMILY})
    sent = client.post("/profile/lab/expert/credentials", data={**form, "csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert "lab_msg=labsync.password_code_sent" in sent.headers["location"]
    page = client.get(sent.headers["location"]).text
    assert 'autocomplete="one-time-code"' in page and "+380*****0001" in page and PASSWORD not in page
    client.cookies.set("anamna_lang", "uk")
    assert "Введіть код, який лабораторія надіслала на +380*****0001." in client.get("/profile?tab=connections").text
    done = client.post("/profile/lab/expert/credentials", data={"code": "123456", "csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert "lab_msg=labsync.saved_checked" in done.headers["location"]  # signed in, then asked who is on the account
    page = client.get(done.headers["location"]).text
    assert "Kid" in page and ACCESS not in page and REFRESH not in page
    with connect(settings) as connection:
        audit = [row[0] for row in connection.execute("SELECT details_json FROM audit_events")]
    assert not any(PASSWORD in str(item) or ACCESS in str(item) for item in audit)


def test_admin_lists_expert_with_its_sign_in_note_and_a_new_address_forgets_tokens(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("expert",))
    page = client.get("/admin/lab-connections").text
    # The per-provider sign-in note was removed with the admin page's help text.
    assert 'id="lab-admin-expert"' in page and "Mobile-app sign-in" not in page
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/admin/lab-connections").text
    assert 'id="lab-admin-expert"' in page and "Вхід як у мобільному застосунку" not in page
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS})
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    moved = labsync.save_provider_settings(settings, "expert", enabled=True, url="https://example.test")
    row = labsync.account(settings, user_id, "expert")
    assert moved == 1 and row["secret"] == "" and row["refresh_secret"] == ""


def test_padded_numbers_lose_their_zeros_and_a_finished_analysis_without_a_pdf_is_named():
    assert expert._trim("5.380000") == "5.38" and expert._trim("Від 0.000000 до 2.590000") == "Від 0 до 2.59"
    assert expert._trim("1.05") == "1.05" and expert._trim("1000264") == "1000264"
    rows = expert.Client._rows({"name": "Ліпідограма", "indicators": [
        {"id": 1, "name": "Тригліцериди", "value": "1.020000", "unit": "ммоль/л",
         "reference_text": "Від 0.000000 до 1.700000", "is_abnormal": False}]})
    assert (rows[0]["result"], rows[0]["norm"]) == ("1.02", ["Від 0 до 1.7"])


def test_a_finished_analysis_without_a_pdf_is_unavailable_not_pending(monkeypatch):
    install(monkeypatch, {("GET", "/api/v1/medical/analyses"): {"items": [
        {"id": 7, "name": "Група крові", "status": "Внесено результати", "status_code": "ResultSubmitted",
         "date": "2025-09-16T00:00:00", "result_date": "2025-09-16T09:18:59", "has_file": False, "indicators": []},
        {"id": 8, "name": "Біопсія", "status": "Новий", "status_code": "New", "date": None, "result_date": None,
         "has_file": False, "indicators": []}], "total": 2, "has_more": False}})
    finished, new = expert.Client(URL, ACCESS, "", "").orders({"id": "p41", "family_member_id": None})
    assert finished["complete"] and finished["unavailable"] == "labsync.unavailable_nofile"
    assert not new["complete"]


# --- a visit's own documents: conclusions and examinations ----------------------

# Shapes as the live service answered (2026-11-09): a conclusion's list entry
# names it, the doctor and the day; its text is on the conclusion itself, and
# its file, when there is one, is a Word document.  An examination's report is
# a scan or a PDF; ``/files`` may list the app's own inline HTML view.
CONCLUSIONS = {"items": [
    {"id": 900, "name": "Консультація гастроентеролога", "date": "2025-10-01T00:00:00", "doctor_name": "Лікар Г.",
     "speciality": "Гастроентеролог", "has_file": True,
     "files": [{"file_id": 1, "source": "remote", "name": "Консультація 1.docx", "size": 10, "mime_type": None},
               {"file_id": 2, "source": "remote", "name": "знімок.jpg", "size": 10, "mime_type": "image/jpeg"}]},
    {"id": 901, "name": "Консультація терапевта", "date": "2025-10-02T00:00:00", "has_file": False},
    {"id": 902, "name": "Консультація кардіолога", "date": "2022-10-01T00:00:00", "has_file": False},
], "total": 3, "skip": 0, "limit": 20, "has_more": False}
CONCLUSION_900 = {**CONCLUSIONS["items"][0], "complaints": "на здуття", "diagnosis": "Функціональна диспепсія",
                  "recommendations": "Дієта\nКонтроль через 3 міс"}
CONCLUSION_901 = {**CONCLUSIONS["items"][1], "examination": "Стан задовільний", "diagnosis_codes": ["K30"],
                  "medications": [{"id": 901, "name": "Дексалгін саше", "quantity_in_recipe": "21 саше",
                                   "take_from": "01.01.2024", "take_to": "07.01.2024",
                                   "reception_quantity": "1.0000 саше", "reception_frequency": "3 раз в 1 День (дні)",
                                   "recommendation": None}]}
RESEARCH = {"items": [
    {"id": 900, "research_type": "УЗД гілок дуги аорти", "date": "2025-10-01", "has_file": True, "status": "Новий"},
    {"id": 901, "research_type": "Комп'ютерна рентгенографія", "body_part": "Рентгенографія ОГК (одна проекція)",
     "date": "2025-10-03", "has_file": False, "status": "Додано висновок",
     "conclusion": "Легеневі поля прозорі.\r\nЕД = 0.02 мЗв"},
    {"id": 902, "research_type": "Комп'ютерна рентгенографія", "date": "2025-10-04", "has_file": False},
    {"id": 903, "research_type": "Комп'ютерна рентгенографія", "body_part": "Рентгенографія ОГК (дві проекції)",
     "date": "2025-10-05", "has_file": True, "conclusion": "Синуси вільні."},
], "total": 4, "skip": 0, "limit": 20, "has_more": False}
JPEG = b"\xff\xd8\xff\xe0 synthetic scan"
W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
     'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')


def word(*paragraphs: str) -> bytes:
    """A minimal .docx; its first paragraph sits in a text box stored twice."""
    boxed = (f"<w:p><mc:AlternateContent><mc:Choice><w:r><w:t>{paragraphs[0]}</w:t></w:r></mc:Choice>"
             f"<mc:Fallback><w:r><w:t>{paragraphs[0]}</w:t></w:r></mc:Fallback></mc:AlternateContent></w:p>")
    body = boxed + "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs[1:])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return out.getvalue()


BREATH_TEST = word("Пацієнт: Тест", "Дихальний тест на визначення надмірного бактерійного росту у кишківнику.",
                   "Висновок: Надмірного бактерійного росту не виявлено.")
VISIT_FILES = {
    ("GET", "/api/v1/medical/conclusions"): CONCLUSIONS,
    ("GET", "/api/v1/medical/research"): RESEARCH,
    ("GET", "/api/v1/medical/conclusions/900"): CONCLUSION_900,
    ("GET", "/api/v1/medical/conclusions/901"): CONCLUSION_901,
    ("GET", "/api/v1/medical/conclusions/902"): {**CONCLUSIONS["items"][2], "diagnosis": None, "files": []},
    ("GET", "/api/v1/medical/research/903/file"): JPEG,
    ("GET", "/api/v1/medical/conclusions/900/files/1"): BREATH_TEST,
    ("GET", "/api/v1/medical/conclusions/900/files/2"): JPEG,
    ("GET", "/api/v1/medical/research/900/file"): b"%PDF-1.4 ultrasound\n%%EOF",
}


def text_of(pdf: bytes, tmp_path: Path) -> str:
    from anamna.ingest.extract import extract_document

    path = tmp_path / "rendered.pdf"
    path.write_bytes(pdf)
    return "\n".join(str(page["native_text"]) for page in extract_document(path, run_ocr=False)["pages"])


def test_conclusions_and_examinations_are_listed_beside_analyses_for_every_person(monkeypatch, tmp_path: Path):
    """The first sync read ``/medical/analyses`` only: a visit's conclusion
    and its ultrasound never arrived.  All three lists are read, for the
    holder and each family member, and a conclusion and an examination that
    share an id with an analysis stay three different orders."""
    seen = install(monkeypatch, {
        ("GET", "/api/v1/medical/analyses"): {"items": [{**ANALYSES["items"][0], "id": 900}], "has_more": False},
        **VISIT_FILES,
    })
    client = expert.Client(URL, ACCESS, "", "")
    kid = {"id": "f12", "family_member_id": 12}
    orders = {order["order_id"]: order for order in client.orders(kid)}
    # A conclusion's text, and whether there is anything to file, is on the
    # conclusion itself: each is read while listing.
    assert [path for _, path, _ in seen] == [
        f"/api/v1/medical/{kind}?family_member_id=12" for kind in (
            "analyses", "conclusions", "conclusions/900", "conclusions/901", "conclusions/902", "research")]
    assert sorted(orders) == ["900", "c900", "c901", "c902", "r900", "r901", "r902", "r903"]
    visit, scan, xray = orders["c900"], orders["r900"], orders["r901"]
    assert (visit["dates"], visit["complete"], visit["unavailable"], visit["rows"]) == (
        ["2025-10-01"], True, None, [])
    assert visit["filename_hint"] == "2025-10-01 Консультація гастроентеролога"
    assert scan["filename_hint"] == "2025-10-01 УЗД гілок дуги аорти" and scan["lab_status"] == "Новий"
    # Named by what was examined; findings typed in, no file: still filed.
    assert xray["filename_hint"] == "2025-10-03 Рентгенографія ОГК (одна проекція)" and xray["unavailable"] is None
    # Neither a file nor a word written: nothing to file, and it says so.
    assert orders["r902"]["unavailable"] == orders["c902"]["unavailable"] == "labsync.unavailable_empty_record"
    assert orders["c901"]["unavailable"] is None
    assert (xray["hint_every_file"], visit["hint_every_file"]) == (True, False)
    assert client.rows(visit, kid) == []

    # The visit's own text, then each attachment: the Word file as a PDF of
    # its text (the text box once), the scan as it is.
    record, breath, photo = client.pdfs(visit, kid)
    assert [path for _, path, _ in seen[-2:]] == [
        "/api/v1/medical/conclusions/900/files/1?family_member_id=12",
        "/api/v1/medical/conclusions/900/files/2?family_member_id=12"]
    said = text_of(record, tmp_path)
    for line in ("Консультація гастроентеролога", "Лікарня «Експерт»", "Дата: 01.10.2025",
                 "Лікар: Лікар Г. (Гастроентеролог)", "Скарги:", "на здуття", "Діагноз:", "Функціональна диспепсія",
                 "Рекомендації:", "Контроль через 3 міс"):
        assert line in said
    # Where the text came from is said above the record: under the last
    # section it was read as one more recommendation.
    assert said.index("Складено Anamna") < said.index("Скарги:")
    converted = text_of(breath, tmp_path)
    assert converted.count("Пацієнт: Тест") == 1 and "Надмірного бактерійного росту не виявлено" in converted
    assert photo == JPEG
    # No file: the conclusion is its text alone.
    [only] = client.pdfs(orders["c901"], kid)
    said = text_of(only, tmp_path)
    # «Огляд:» is the heading a consultation's finding is read under when no
    # diagnosis is written; a prescription reads as one, without its record id.
    assert "Огляд:\nСтан задовільний" in said and "Код діагнозу:\nK30" in said
    # Where a long line wraps depends on the font the machine has, so the
    # prescription is compared with its soft line breaks folded away.
    assert ("Дексалгін саше: по 1 саше, 3 раз в 1 День (дні), 01.01.2024–07.01.2024, на курс 21 саше"
            in " ".join(said.split()) and "901 ·" not in said)
    assert client.pdfs(scan, {"id": "p41", "family_member_id": None}) == [b"%PDF-1.4 ultrasound\n%%EOF"]
    assert seen[-1][1] == "/api/v1/medical/research/900/file"
    assert "Легеневі поля прозорі." in text_of(client.pdfs(xray, kid)[0], tmp_path)
    # A radiograph is no report: the findings come first, the image beside them.
    report, radiograph = client.pdfs(orders["r903"], kid)
    assert "Синуси вільні." in text_of(report, tmp_path) and radiograph == JPEG
    # The record is the same bytes every time: a re-sync finds it already filed.
    assert client.pdfs(orders["c901"], kid) == [only]


def test_an_inline_view_and_an_unreadable_file_are_not_filed(monkeypatch):
    install(monkeypatch, {("GET", "/api/v1/medical/research/7/file"): b"<html>record</html>"})
    client = expert.Client(URL, ACCESS, "", "")
    order = {"order_id": "r7", "packet": "УЗД", "dates": ["2025-01-01"], "has_file": True,
             "files": [{"file_id": 0, "source": "inline", "name": "UZD.html", "mime_type": "text/html"}]}
    with pytest.raises(LabSyncError) as refused:
        client.pdfs(order, {"id": "p41", "family_member_id": None})
    assert refused.value.key == "labsync.error_pdf"


def test_a_long_list_is_paged_and_a_backend_that_ignores_skip_is_not_looped(monkeypatch):
    seen: list = []

    def paged(_raw, _headers):
        skip = int(seen[-1][1].partition("skip=")[2] or 0)
        return {"items": [{"id": 700 + skip, "name": "Огляд", "date": "2025-01-01", "has_file": True}],
                "has_more": skip < 2}

    def stuck(_raw, _headers):  # answers the first page whatever skip asks for
        return {"items": [{"id": 1, "name": "УЗД", "date": "2025-01-01", "has_file": True}], "has_more": True}

    install(monkeypatch, {("GET", "/api/v1/medical/analyses"): {"items": [], "has_more": False},
                          ("GET", "/api/v1/medical/conclusions"): paged,
                          **{("GET", f"/api/v1/medical/conclusions/{n}"): {"id": n} for n in (700, 701, 702)},
                          ("GET", "/api/v1/medical/research"): stuck}, seen)
    orders = expert.Client(URL, ACCESS, "", "").orders({"id": "p41", "family_member_id": None})
    assert [order["order_id"] for order in orders] == ["c700", "c701", "c702", "r1"]
    assert [path for _, path, _ in seen if "research" in path] == [
        "/api/v1/medical/research", "/api/v1/medical/research?skip=1"]


def test_sync_imports_a_visits_conclusion_and_examination_as_documents(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("expert",))
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS,
                          ("GET", "/api/v1/profile"): PROFILE, ("GET", "/api/v1/profile/family"): FAMILY})
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    labsync.check_account(settings, user_id, "expert")
    labsync.link_person(settings, user_id, "expert", "p41", "self", confirmed=False)
    # The clinic's name and day go with the visit's own record only; an
    # attachment is named by its own text.
    names = ["expert-c900 2025-10-01 Консультація гастроентеролога.pdf", "expert-c900-1.pdf", "expert-c900-2.jpg",
             "expert-c901 2025-10-02 Консультація терапевта.pdf",
             "expert-r900 2025-10-01 УЗД гілок дуги аорти.pdf",
             "expert-r901 2025-10-03 Рентгенографія ОГК (одна проекція).pdf",
             "expert-r903 2025-10-05 Рентгенографія ОГК (дві проекції).pdf",
             "expert-r903-1 2025-10-05 Рентгенографія ОГК (дві проекції).jpg"]
    calls = stub_intake(monkeypatch, settings, user_id, {
        name: {"vendor": "Expert Hospital", "order": None, "day": "2025-10-01",
               "values": [("Гемоглобін", 140.0 + index, "г/л", "within_vendor_range")]}
        for index, name in enumerate(names)})
    install(monkeypatch, {("GET", "/api/v1/medical/analyses"): {"items": [], "has_more": False}, **VISIT_FILES})
    summary = labsync.sync(settings, user_id, "expert", inline=True)
    assert sorted(calls) == sorted(names)
    assert (summary["imported"], summary["unavailable"], summary["failed"]) == (5, 2, 0)
    with connect(settings) as connection:
        states = dict(connection.execute("SELECT order_id, state FROM lab_orders WHERE provider='expert'"))
        verified = connection.execute(
            "SELECT COUNT(*) FROM observations WHERE owner_user_id=? AND verification_status='verified'",
            (user_id,)).fetchone()[0]
    assert states == {"c900": "imported", "c901": "imported", "c902": "unavailable", "r900": "imported",
                      "r901": "imported", "r902": "unavailable", "r903": "imported"}
    assert verified == 0  # read and queued for review, never verified by the sync
    again = labsync.sync(settings, user_id, "expert", inline=True)
    assert len(calls) == len(names) and again["imported"] == 0


def test_an_expert_visit_document_takes_its_name_day_and_clinic_from_the_file_name():
    from test_classifier import pdf_page

    from anamna.ingest.classifier import classify_document

    note = classify_document("expert-c900 2025-10-01 Консультація лікаря-гастроентеролога.pdf", "application/pdf",
                             [pdf_page("Скарги на біль в епігастрії\nРекомендовано контроль")])
    assert (note.vendor, note.clinical_type, note.title, note.report_date) == (
        "Expert Hospital", "consultation", "Консультація лікаря-гастроентеролога", "2025-10-01")
    scan = classify_document("expert-r900 2025-10-01 УЗД органів черевної порожнини.pdf", "application/pdf",
                             [pdf_page("Печінка не збільшена, контури рівні\nЖовчний міхур без змін")])
    assert (scan.vendor, scan.clinical_type, scan.report_date) == ("Expert Hospital", "ultrasound", "2025-10-01")


def test_a_record_the_clinic_stored_html_escaped_reads_as_typed():
    from anamna.labsync import visit_pdf

    assert visit_pdf.field_text("Ліки на ніч 30 днів--&gt; далі контроль") == "Ліки на ніч 30 днів--> далі контроль"
    assert visit_pdf.field_text([{"name": "Урсофальк", "recommendation": "2 міс --&gt; далі 1 капс"}]) == (
        "Урсофальк: 2 міс --> далі 1 капс")
