"""Ekspert (Expert Hospital): phone + password sign-in, texted code, token
refresh, and reading analyses — all against synthetic replies shaped like the
models decompiled from the Android app (see labsync/ekspert.py).  HTTP is
stubbed at ``labsync.common._http``, as for the other labs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.labsync import LabSyncError, common, ekspert

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


def install(monkeypatch, routes: dict, seen: list | None = None) -> list:
    seen = [] if seen is None else seen
    monkeypatch.setattr(common, "_http", router(routes, seen))
    return seen


def capture(store: list, reply):
    def handler(raw, headers):
        store.append((body(raw), headers))
        return reply(raw, headers) if callable(reply) else reply
    return handler


def test_phone_is_normalised_the_way_the_app_sends_it():
    for typed in ("671234567", "0671234567", "+38 (067) 123 45 67", "380671234567", "+380 67 123 45 67"):
        assert ekspert.normalize_phone(typed) == "+380671234567"
    for bad in ("", "12345", "+48 601 234 567", "06712345678"):
        with pytest.raises(LabSyncError) as caught:
            ekspert.normalize_phone(bad)
        assert caught.value.key == "labsync.password_error_phone"


def test_sign_in_sends_the_app_fields_and_keeps_only_tokens(monkeypatch):
    sent: list = []
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, TOKENS)})
    state = {"device_id": "00000000-0000-4000-8000-000000000001", "trusted": None}
    creds = ekspert.start_sign_in(URL, "67 000 00 01", PASSWORD, state)
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
        ekspert.start_sign_in(URL, "0670000001", PASSWORD, state)
    assert caught.value.key == "labsync.password_error_invalid"
    with pytest.raises(LabSyncError) as caught:
        ekspert.verify_code(URL, {"token": "challenge-token-0001"}, "123456", state, "+380670000001")
    assert caught.value.key == "labsync.password_error_code"
    install(monkeypatch, {("POST", "/api/v1/auth/login"): 429})
    with pytest.raises(LabSyncError) as caught:
        ekspert.start_sign_in(URL, "0670000001", PASSWORD, state)
    assert caught.value.key == "labsync.password_error_throttled"


def test_texted_code_flow_stores_tokens_never_the_password(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("ekspert",))
    sent: list = []
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, CHALLENGE),
                          ("POST", "/api/v1/auth/2fa/verify"): capture(sent, TOKENS)})
    assert labsync.save_credentials(settings, user_id, "ekspert",
                                    {"phone": "0670000001", "password": PASSWORD}) == "labsync.password_code_sent"
    assert labsync.pending_code(user_id, "ekspert") == {"phone_masked": "+380*****0001", "code_length": 6}
    assert labsync.account(settings, user_id, "ekspert") is None  # nothing stored before the code
    assert labsync.save_credentials(settings, user_id, "ekspert", {"code": "123 456"}) == "labsync.saved_credentials"
    verify = sent[1][0]
    assert verify["challenge_token"] == "challenge-token-0001" and verify["code"] == "123456"
    assert verify["device_id"] == sent[0][0]["device_id"] and verify["fcm_token"] is None
    row = labsync.account(settings, user_id, "ekspert")
    assert row["secret"] == ACCESS and row["phone"] == "+380670000001"
    assert json.loads(row["refresh_secret"])["refresh"] == REFRESH
    assert PASSWORD not in json.dumps(dict(row))
    assert labsync.pending_code(user_id, "ekspert") is None
    with pytest.raises(LabSyncError) as caught:  # a code with no step waiting
        labsync.save_credentials(settings, user_id, "ekspert", {"code": "123456"})
    assert caught.value.key == "labsync.password_error_code_expired"

    # Forgetting drops the tokens but keeps the device, so the lab still
    # trusts it and the next sign-in sends the trusted-device token.
    labsync.forget(settings, user_id, "ekspert")
    row = labsync.account(settings, user_id, "ekspert")
    assert row["secret"] == "" and "refresh" not in json.loads(row["refresh_secret"])
    install(monkeypatch, {("POST", "/api/v1/auth/login"): capture(sent, TOKENS)})
    labsync.save_credentials(settings, user_id, "ekspert", {"phone": "0670000001", "password": PASSWORD})
    assert sent[-1][0]["trusted_device_token"] == "trusted-device-token-0001"
    assert sent[-1][0]["device_id"] == sent[0][0]["device_id"]


def test_an_expired_access_token_is_refreshed_once_and_the_new_pair_kept(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("ekspert",))
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS})
    labsync.save_credentials(settings, user_id, "ekspert", {"phone": "0670000001", "password": PASSWORD})
    refreshed: list = []

    def profile(raw, headers):
        return PROFILE if headers["Authorization"] == f"Bearer {ACCESS2}" else 401

    install(monkeypatch, {
        ("GET", "/api/v1/profile"): profile,
        ("GET", "/api/v1/profile/family"): lambda raw, headers: FAMILY if ACCESS2 in headers["Authorization"] else 401,
        ("POST", "/api/v1/auth/refresh"): capture(refreshed, {"access_token": ACCESS2, "refresh_token": REFRESH2,
                                                              "token_type": "bearer"}),
    })
    people = labsync.check_account(settings, user_id, "ekspert")
    assert refreshed[0][0] == {"refresh_token": REFRESH}
    row = labsync.account(settings, user_id, "ekspert")
    assert row["secret"] == ACCESS2 and json.loads(row["refresh_secret"])["refresh"] == REFRESH2
    assert [(p["id"], p["birthday"], p["sex"]) for p in people] == [
        ("p41", "1990-03-14", "male"), ("f12", "2020-06-19", "female"), ("f13", "", "")]
    assert all("phone" not in person and "qr_code" not in person for person in people)

    # The lab ends the session: the refresh is refused and the person is told to reconnect.
    install(monkeypatch, {("GET", "/api/v1/profile"): 401, ("POST", "/api/v1/auth/refresh"): 401})
    with pytest.raises(LabSyncError) as caught:
        labsync.check_account(settings, user_id, "ekspert")
    assert caught.value.key == "labsync.error_auth"


def test_a_profile_the_hospital_has_not_linked_gets_its_own_explanation(monkeypatch):
    install(monkeypatch, {("GET", "/api/v1/profile"): 403})
    with pytest.raises(LabSyncError) as caught:
        ekspert.Client(URL, ACCESS, "", json.dumps({"refresh": REFRESH})).check()
    assert caught.value.key == "labsync.ekspert_error_forbidden"


def test_analyses_become_orders_and_indicators_become_lab_rows(monkeypatch):
    seen = install(monkeypatch, {
        ("GET", "/api/v1/medical/analyses"): ANALYSES,
        ("GET", "/api/v1/medical/analyses/501"): ANALYSIS_501,
        ("GET", "/api/v1/medical/analyses/501/file"): b"%PDF-1.4 synthetic",
    })
    client = ekspert.Client(URL, ACCESS, "", "")
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
    assert client.pdfs(first, {"id": "p41", "family_member_id": None}) == [b"%PDF-1.4 synthetic"]
    assert seen[-1][1] == "/api/v1/medical/analyses/501/file"
    # ``is_linked_to_medeir: false`` is no gate: a live account said so and
    # still listed its analyses, so every person is asked.
    client.orders({"id": "f13", "family_member_id": 13})
    assert seen[-1][1] == "/api/v1/medical/analyses?family_member_id=13"


def test_sync_imports_a_finished_analysis_and_waits_for_the_rest(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path, enable=("ekspert",))
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS,
                          ("GET", "/api/v1/profile"): PROFILE, ("GET", "/api/v1/profile/family"): FAMILY})
    labsync.save_credentials(settings, user_id, "ekspert", {"phone": "0670000001", "password": PASSWORD})
    labsync.check_account(settings, user_id, "ekspert")
    labsync.link_person(settings, user_id, "ekspert", "p41", "self", confirmed=False)
    calls = stub_intake(monkeypatch, settings, user_id, {
        "ekspert-501.pdf": {"vendor": "Expert Hospital", "order": None, "day": "2025-09-16",
                            "values": [("Гемоглобін", 151.0, "г/л", "within_vendor_range"),
                                       ("Лейкоцити", 11.2, "10^9/л", "high")]},
    })
    install(monkeypatch, {
        ("GET", "/api/v1/medical/analyses"): ANALYSES,
        ("GET", "/api/v1/medical/analyses/501"): ANALYSIS_501,
        ("GET", "/api/v1/medical/analyses/502"): {**ANALYSES["items"][1], "indicators": []},
        ("GET", "/api/v1/medical/analyses/501/file"): b"%PDF-1.4 synthetic",
    })
    summary = labsync.sync(settings, user_id, "ekspert", inline=True)
    assert calls == ["ekspert-501.pdf"]
    assert (summary["imported"], summary["pending"], summary["failed"]) == (1, 1, 0)
    with connect(settings) as connection:
        states = dict(connection.execute(
            "SELECT order_id, state FROM lab_orders WHERE provider='ekspert'").fetchall())
    assert states == {"501": "imported", "502": "pending"}
    assert summary["crosscheck"]["match"] >= 2
    again = labsync.sync(settings, user_id, "ekspert", inline=True)
    assert calls == ["ekspert-501.pdf"] and again["imported"] == 0


def test_profile_offers_phone_and_password_then_the_code_in_both_languages(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("ekspert",))
    page = client.get("/profile?tab=connections").text
    card = page[page.index('id="lab-ekspert"'):]
    assert 'name="password" type="password"' in card and 'autocomplete="current-password"' in card
    assert "only to the lab&#39;s own server (http://127.0.0.1:9)" in card
    assert "Developer tools" not in card  # nothing to copy from a browser
    form = {"phone": "067 000 00 01", "password": PASSWORD}
    assert client.post("/profile/lab/ekspert/credentials", data=form, follow_redirects=False).status_code == 403
    install(monkeypatch, {("POST", "/api/v1/auth/login"): CHALLENGE, ("POST", "/api/v1/auth/2fa/verify"): TOKENS,
                          ("GET", "/api/v1/profile"): PROFILE, ("GET", "/api/v1/profile/family"): FAMILY})
    sent = client.post("/profile/lab/ekspert/credentials", data={**form, "csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert "lab_msg=labsync.password_code_sent" in sent.headers["location"]
    page = client.get(sent.headers["location"]).text
    assert 'autocomplete="one-time-code"' in page and "+380*****0001" in page and PASSWORD not in page
    client.cookies.set("anamna_lang", "uk")
    assert "Введіть код, який лабораторія надіслала на +380*****0001." in client.get("/profile?tab=connections").text
    done = client.post("/profile/lab/ekspert/credentials", data={"code": "123456", "csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert "lab_msg=labsync.saved_checked" in done.headers["location"]  # signed in, then asked who is on the account
    page = client.get(done.headers["location"]).text
    assert "Kid" in page and ACCESS not in page and REFRESH not in page
    with connect(settings) as connection:
        audit = [row[0] for row in connection.execute("SELECT details_json FROM audit_events")]
    assert not any(PASSWORD in str(item) or ACCESS in str(item) for item in audit)


def test_admin_lists_ekspert_with_its_sign_in_note_and_a_new_address_forgets_tokens(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("ekspert",))
    page = client.get("/admin/lab-connections").text
    # The per-provider sign-in note was removed with the admin page's help text.
    assert 'id="lab-admin-ekspert"' in page and "Mobile-app sign-in" not in page
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/admin/lab-connections").text
    assert 'id="lab-admin-ekspert"' in page and "Вхід як у мобільному застосунку" not in page
    install(monkeypatch, {("POST", "/api/v1/auth/login"): TOKENS})
    labsync.save_credentials(settings, user_id, "ekspert", {"phone": "0670000001", "password": PASSWORD})
    moved = labsync.save_provider_settings(settings, "ekspert", enabled=True, url="https://example.test")
    row = labsync.account(settings, user_id, "ekspert")
    assert moved == 1 and row["secret"] == "" and row["refresh_secret"] == ""


def test_padded_numbers_lose_their_zeros_and_a_finished_analysis_without_a_pdf_is_named():
    assert ekspert._trim("5.380000") == "5.38" and ekspert._trim("Від 0.000000 до 2.590000") == "Від 0 до 2.59"
    assert ekspert._trim("1.05") == "1.05" and ekspert._trim("1000264") == "1000264"
    rows = ekspert.Client._rows({"name": "Ліпідограма", "indicators": [
        {"id": 1, "name": "Тригліцериди", "value": "1.020000", "unit": "ммоль/л",
         "reference_text": "Від 0.000000 до 1.700000", "is_abnormal": False}]})
    assert (rows[0]["result"], rows[0]["norm"]) == ("1.02", ["Від 0 до 1.7"])


def test_a_finished_analysis_without_a_pdf_is_unavailable_not_pending(monkeypatch):
    install(monkeypatch, {("GET", "/api/v1/medical/analyses"): {"items": [
        {"id": 7, "name": "Група крові", "status": "Внесено результати", "status_code": "ResultSubmitted",
         "date": "2025-09-16T00:00:00", "result_date": "2025-09-16T09:18:59", "has_file": False, "indicators": []},
        {"id": 8, "name": "Біопсія", "status": "Новий", "status_code": "New", "date": None, "result_date": None,
         "has_file": False, "indicators": []}], "total": 2, "has_more": False}})
    finished, new = ekspert.Client(URL, ACCESS, "", "").orders({"id": "p41", "family_member_id": None})
    assert finished["complete"] and finished["unavailable"] == "labsync.unavailable_nofile"
    assert not new["complete"]
