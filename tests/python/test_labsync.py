"""Lab connections (Esculab, Synevo): sign-in, sync, linking and the cross-check.

Every fixture here is synthetic.  HTTP is stubbed at ``labsync.common._http``
— the one door every real call goes through — and the intake queue is
stubbed at ``labsync.intake.enqueue`` so a "downloaded PDF" becomes a
document with known observations; the real pipeline is exercised end to end
against a fake server, not here.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import labsync
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts
from anamna.labsync import common, esculab, synevo
from anamna.security import create_access_token, create_session, create_user
from anamna.web.app import create_app

from test_web_panels import PASSWORD, settings_for

# A JWT-shaped token whose payload is {"sub":"1","exp":4102444800} (2100-01-01).
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIiwiZXhwIjo0MTAyNDQ0ODAwfQ.c2lnbmF0dXJl"
PHONE = "+380000000001"
#: The 4-digit code Esculab's fake server texts.
CODE = "1234"
COOKIE = "synthetic-session-" + "a" * 40
#: An order date young enough that a part-done order still waits for the lab.
RECENT = date.today().isoformat() + " 08:00"


# --- fixtures ------------------------------------------------------------------


def make(tmp_path: Path, *, admin: bool = True, enable: tuple[str, ...] = ("esculab", "synevo")):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "lab@example.test", "Lab", PASSWORD)
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute("UPDATE users SET role=? WHERE id=?", ("admin" if admin else "user", user_id))
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Person', '1990-03-14', 'male', ?)""",
            (f"patient-{user_id}", user_id, utc_now()),
        )
    for key in enable:
        labsync.save_provider_settings(settings, key, enabled=True, url="http://127.0.0.1:9")
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return settings, user_id, client


def csrf(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute("SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]


def seed_doc(settings, user_id: str, *, vendor: str, order: str | None, day: str, values: list[tuple]) -> str:
    """A document as the pipeline would leave it: values are (name, number|text, unit, interpretation)."""
    document_id = str(uuid.uuid4())
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, vendor, None)
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, order_identifier, report_date, imported_at, status)
               VALUES (?, ?, ?, ?, 'r.pdf', 'r.pdf', 'application/pdf', 1, ?, 2, 't', 'laboratory',
                       'native_text', 1, ?, ?, ?, 'final')""",
            (document_id, user_id, f"patient-{user_id}", vendor_id, document_id, order, day, utc_now()),
        )
        for index, (name, value, unit, reading) in enumerate(values):
            concept_id, _ = ensure_concept(connection, name, vendor_id)
            numeric = value if isinstance(value, (int, float)) else None
            connection.execute(
                """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, value_text, unit_raw, observed_at,
                       vendor_interpretation, verification_status, extraction_method, confidence,
                       evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', 'test', 0.9, ?, 'test', ?)""",
                (f"{document_id}-{index}", user_id, f"patient-{user_id}", document_id, concept_id, name,
                 "numeric" if numeric is not None else "text", numeric, None if numeric is not None else value,
                 unit, day, reading, f"{name} {value} {unit}", utc_now()),
            )
    return document_id


def stub_intake(monkeypatch, settings, user_id: str, produced: dict[str, dict]):
    """``enqueue`` turns a downloaded file into a finished job whose document
    carries the observations listed for that filename."""
    calls: list[str] = []

    def enqueue(settings_, *, filename, source_path, owner_user_id=None, **_):
        calls.append(filename)
        spec = produced[filename]
        owner = owner_user_id or user_id
        document_id = seed_doc(settings, owner, **spec)
        job_id = str(uuid.uuid4())
        with connect(settings) as connection:
            connection.execute(
                """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename, source_path,
                       state, detail_key, document_id, created_at)
                   VALUES (?, ?, ?, 'b', 'document', ?, ?, 'done', 'intake.done_imported', ?, ?)""",
                (job_id, owner, f"patient-{owner}", filename, str(source_path), document_id, utc_now()),
            )
        Path(source_path).unlink(missing_ok=True)  # nothing of a test is left in sources/
        return job_id

    monkeypatch.setattr(labsync.intake, "enqueue", enqueue)
    monkeypatch.setattr(labsync.intake, "drain_now", lambda settings_: None)
    monkeypatch.setattr(labsync, "ORDER_DELAY_SECONDS", 0)
    return calls


def router(routes: dict, seen: list | None = None):
    """A stand-in for ``common._http``: ``(METHOD, path)`` → reply, where a
    reply is JSON-able, bytes, an int status, or a callable(body, headers)."""

    def http(method, url, *, headers, body=None, timeout=0, limit=0):
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
        if seen is not None:
            seen.append((method, path, headers))
        reply = routes.get((method, path.split("?")[0]))
        if reply is None:
            return 404, [], b""
        if callable(reply):
            reply = reply(body, headers)
        if isinstance(reply, int):
            return reply, [], b""
        if isinstance(reply, tuple):
            return reply
        return 200, [], reply if isinstance(reply, bytes) else json.dumps(reply).encode()

    return http


# --- reading rows ----------------------------------------------------------------


def test_norm_literal_mixes_quoted_and_bare_elements():
    assert common.parse_norm('{"< 3.8 низького ризику#%","Чоловіки: 130-170#%"}') == [
        "< 3.8 низького ризику", "Чоловіки: 130-170"]
    assert common.parse_norm("{3.1-19.9#%}") == ["3.1-19.9"]
    assert common.parse_norm("{NULL}") == []
    assert common.parse_norm('{" #%"}') == []
    assert common.parse_norm('{"При лікуванні: 2.0-3.5#%",0.81-1.22#%}') == ["При лікуванні: 2.0-3.5", "0.81-1.22"]
    assert common.parse_norm('{"with \\"quote\\"#%"}') == ['with "quote"']


def test_units_lose_their_html_and_a_dash_is_no_unit():
    assert common.clean_unit("10<sup>9</sup>/л") == "10^9/л"
    assert common.clean_unit("10<sup>9</sup>клітин/л ") == "10^9клітин/л"
    assert common.clean_unit("-") == ""
    assert common.clean_unit("мкмоль/л&nbsp;") == "мкмоль/л"


def test_names_fold_homoglyphs_and_spacing_but_keep_discriminating_tails():
    cyrillic = "Середній вміст гемоглобіну в еритроциті (МСН)"
    latin = "Середній вміст гемоглобіну в еритроциті (MCH)"
    assert common.name_key(cyrillic) == common.name_key(latin)
    assert common.name_key("відношення(МНВ/INR)") == common.name_key("відношення (МНВ/INR)")
    assert common.name_key("Ширина розподілу (RDW-SD)") != common.name_key("Ширина розподілу (RDW-CV)")
    assert common.loose_name_key("Аналіз крові: ШОЕ (ESR)") == common.loose_name_key("ШОЕ")


def test_results_parse_comma_decimals_and_comparators():
    assert common.parse_result("3.29") == (None, 3.29)
    assert common.parse_result("<0,5") == ("<", 0.5)
    assert common.parse_result("≥ 10") == (">=", 10.0)
    assert common.parse_result("негативний") == (None, None)


def test_synevo_credentials_accept_the_cookie_alone_or_with_its_name():
    assert synevo.parse_credentials({"token": f"next-auth.session-token={COOKIE}; other=1"})["secret"] == COOKIE
    with pytest.raises(common.LabSyncError):
        synevo.parse_credentials({"token": "short"})


def test_base_url_must_be_an_https_origin():
    assert common.url_is_acceptable("https://esculab.com")
    assert common.url_is_acceptable("http://127.0.0.1:8215")
    for bad in ("http://esculab.com", "https://user:pw@esculab.com", "https://esculab.com/api", "ftp://x", "https://x?q=1"):
        assert not common.url_is_acceptable(bad), bad


# --- the cross-check -------------------------------------------------------------


def row(test, result, units="", state="normal", resulttype="digital"):
    return common.lab_row(test=test, result=result, units=units, state=state, resulttype=resulttype)


def obs(name, value, unit=None, interp="within_vendor_range", oid=None):
    return {"id": oid or name, "document_id": "d", "page_number": 1, "raw_name": name,
            "value_numeric": value if isinstance(value, float) else None,
            "value_text": value if isinstance(value, str) else None, "comparator": None, "unit_raw": unit,
            "verification_status": "extracted", "vendor_interpretation": interp, "evidence_text": ""}


def test_cross_check_classifies_every_row_and_observation():
    rows = [
        row("Гемоглобін (HGB)", "151", "г/л"),
        row("Лейкоцити (WBC)", "6.02", "10<sup>9</sup>/л"),
        row("Середній вміст гемоглобіну (МСН)", "30.2", "пг"),
        row("Тромбоцити (PLT)", "307", "10<sup>9</sup>/л"),
        row("Глюкоза", "5.6", "ммоль/л", state="critical"),
        row("Ширина розподілу (RDW-SD)", "36.6", "фл"),
        row("Ширина розподілу (RDW-CV)", "12.1", "%"),
        row("Посів", '{"a":1}', resulttype="json"),
        row("Примітки", "-"),
        row("Примітки (зак)", "Токсигенна зернистість окремих нейтрофілів."),
        row("Копрограма", "a_1.pdf", resulttype="file"),
    ]
    observations = [
        obs("Гемоглобін (HGB)", 151.0, "г/л"),
        obs("Лейкоцити (WBC)", 6.02, "10^9/л"),
        obs("Середній вміст гемоглобіну (MCH)", 30.2, "пг"),
        obs("Тромбоцити (PLT)", 370.0, "10^9/л"),
        obs("Глюкоза", 5.6, "мг/дл"),
        obs("Ширина розподілу (RDW-CV)", 12.1, "%"),
        obs("Сміття", 1.0),
    ]
    result = labsync.cross_check(rows, observations)
    by_name = {(item["lab"] or {}).get("test") or item["obs"]["name"]: item for item in result["items"]}
    assert by_name["Гемоглобін (HGB)"]["cls"] == "match"
    assert by_name["Лейкоцити (WBC)"]["cls"] == "match"  # HTML unit folded through canonical_unit
    assert by_name["Середній вміст гемоглобіну (МСН)"]["cls"] == "match"  # Cyrillic homoglyph
    assert by_name["Тромбоцити (PLT)"]["cls"] == "value_mismatch"
    assert by_name["Глюкоза"]["cls"] == "unit_mismatch"
    assert by_name["Глюкоза"]["flag"] == "lab_out_ours_in"
    # The RDW-SD row must not borrow the RDW-CV observation.
    assert by_name["Ширина розподілу (RDW-SD)"]["cls"] == "missing"
    assert by_name["Ширина розподілу (RDW-CV)"]["cls"] == "match"
    assert by_name["Посів"]["cls"] == "info" and by_name["Примітки"]["cls"] == "info"
    # A remark and an attached file are not values the PDF could be missing.
    assert by_name["Примітки (зак)"]["cls"] == "info" and by_name["Копрограма"]["cls"] == "info"
    assert by_name["Сміття"]["cls"] == "extra"
    assert result["counts"] == {"match": 4, "value_mismatch": 1, "unit_mismatch": 1, "name_mismatch": 0,
                                "missing": 1, "extra": 1, "info": 4, "flag": 1, "reference_differs": 0}


def test_cross_check_pairs_cut_names_and_recognises_descriptive_blocks():
    rows = [
        row("Ліпопротеїди високої щільності (ЛПВЩ, HDL)", "1.33", "ммоль/л"),
        row("Еритроцити (RBC)", "5.13", "10^12 клітин/л"),
        row("Вірус паротиту, антитіла IgG", "4.7", "AI (Індекс антитіл)"),
        row("Резус-фактор", "позитивний(+) (positive)", "", resulttype="string"),
        row("Лейкоцити", "не виявлені", "Leu/µL", resulttype="string"),
        row("ВІЛ-тест", "результат готовий", "", resulttype="string"),
        row("Копрограма", json.dumps([{"parametr": "М'язові волокна", "item_name": "змінені"}], ensure_ascii=False),
            resulttype="flora"),
    ]
    observations = [
        obs("Ліпопротеїди високої щільності (ЛПВЩ", 1.33, "ммоль/л"),
        obs("Еритроцити (RBC)", 5.13, "10^12"),
        obs("Вірус паротиту, антитіла IgG", 4.7, "AI"),
        obs("Резус-фактор", "позитивний(+)"),
        obs("Лейкоцити", "не виявлені"),
        obs("М'язові волокна змінені (кал)", "поодиноко"),
    ]
    result = labsync.cross_check(rows, observations)
    classes = {(item["obs"] or {}).get("name") or item["lab"]["test"]: item["cls"] for item in result["items"]}
    assert classes["Ліпопротеїди високої щільності (ЛПВЩ"] == "name_mismatch"
    assert classes["Еритроцити (RBC)"] == classes["Вірус паротиту, антитіла IgG"] == "match"
    assert classes["Резус-фактор"] == classes["Лейкоцити"] == "match"
    assert classes["ВІЛ-тест"] == "info"
    assert classes["М'язові волокна змінені (кал)"] == "info"
    assert result["counts"]["extra"] == result["counts"]["missing"] == 0


# --- Esculab sync ------------------------------------------------------------------


def esculab_sign_in_routes(accepted=None):
    """The app's two sign-in calls: the phone texts :data:`CODE`; the code,
    with the same uuid and ``AccessPhone``, answers one entry per role."""
    sent: dict = {}
    accepted = accepted if accepted is not None else [
        {"clientType": "DOCTOR", "tokens": {"token": "doctor-" + TOKEN, "exist": True}},
        {"clientType": "PATIENT", "tokens": {"token": TOKEN, "exist": True}},
    ]

    def authorise(body, headers):
        data = json.loads(body)
        sent["uuid"] = data["uuid"]
        return {} if data["phone"] == PHONE and re.fullmatch(r"[0-9a-f-]{36}", data["uuid"]) else 400

    def accept(body, headers):
        if json.loads(body) != {"code": CODE, "uuid": sent.get("uuid")} or headers.get("AccessPhone") != PHONE:
            return 400
        return accepted

    return {("POST", "/api/auth/authorise"): authorise, ("POST", "/api/auth/application/accept"): accept}


def sign_in_esculab(settings, user_id):
    """Phone, then the texted code, as the profile's form sends them."""
    assert labsync.save_credentials(settings, user_id, "esculab", {"phone": PHONE}) == "labsync.password_code_sent"
    assert labsync.save_credentials(settings, user_id, "esculab", {"code": CODE}) == "labsync.saved_credentials"


def esculab_routes(orders: list[dict], rows: dict[str, list], *, persons=None):
    persons = persons or [
        {"id": 111, "firstname": "Test", "lastname": "Person", "fathername": "", "birthday": "1990-03-14",
         "sex": "M", "main": True, "password": "never-store", "login": "x", "phone": PHONE, "email": "x@y.test"},
        {"id": 222, "firstname": "Other", "lastname": "Person", "fathername": "", "birthday": "1990-01-01",
         "sex": "F", "main": False},
    ]

    def authorised(reply):
        return lambda body, headers: reply if headers.get("Authorization") == f"Bearer {TOKEN}" and headers.get("AccessPhone") == PHONE else 401

    routes = {
        **esculab_sign_in_routes(),
        ("POST", "/api/customers/findPatientSite"): authorised(persons),
        ("GET", "/api/customers/v2/orders"): authorised(orders),
    }
    for order_id, order_rows in rows.items():
        routes[("GET", f"/api/customers/getOrdersResult/{order_id}/111")] = authorised(order_rows)
        routes[("GET", f"/api/results/getResults/111/{order_id}")] = authorised(b"%PDF-1.4 synthetic " + order_id.encode())
    return routes


def order(order_id, *, ready, total, status="DONE", patient=111, dt="2026-01-10 08:00"):
    return {"orderId": order_id, "dt": dt, "ready": ready, "total": total, "patient": {"id": patient},
            "status": {"status": status}, "deleted": False, "services": []}


def es_row(test, result, units, idtest=1, packet="Пакет", resulttype="digital"):
    return {"test": test, "result": result, "units": units, "idtest": idtest, "packet": packet,
            "resulttype": resulttype, "state": "normal", "norm": "{1-2#%}", "material": "кров"}


def connect_esculab(settings, user_id, monkeypatch, routes):
    monkeypatch.setattr(common, "_http", router(routes))
    sign_in_esculab(settings, user_id)
    people = labsync.check_account(settings, user_id, "esculab")
    assert {"password", "login", "phone", "email"}.isdisjoint(people[0])
    labsync.link_person(settings, user_id, "esculab", "111", "self", confirmed=False)


def test_esculab_sync_imports_links_waits_and_is_idempotent(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    manual = seed_doc(settings, user_id, vendor="Esculab", order="9002", day="2025-05-01",
                      values=[("Креатинін", 68.3, "мкмоль/л", "within_vendor_range")])
    orders = [order(9001, ready=3, total=3), order(9002, ready=1, total=1, dt="2025-05-01 08:00"),
              order(9003, ready=1, total=2, status="PARTLY_DONE", dt=RECENT), order(9100, ready=1, total=1, patient=222)]
    rows = {
        "9001": [es_row("Гемоглобін (HGB)", "151", "г/л"), es_row("Лейкоцити (WBC)", "6.02", "10<sup>9</sup>/л"),
                 es_row("Середній вміст гемоглобіну в еритроциті (MCH)", "30.2", "пг"),
                 es_row("Службовий", "x", "-", idtest=406, packet="1516 службовий"),
                 es_row("Розділ", "", "", resulttype="none")],
        "9002": [es_row("Креатинін", "68.3", "мкмоль/л")],
        "9003": [es_row("Глюкоза", "5.1", "ммоль/л")],
    }
    connect_esculab(settings, user_id, monkeypatch, esculab_routes(orders, rows))
    calls = stub_intake(monkeypatch, settings, user_id, {
        "esculab-9001.pdf": {"vendor": "Esculab", "order": "9001", "day": "2026-01-10", "values": [
            ("Гемоглобін (HGB)", 151.0, "г/л", None), ("Лейкоцити (WBC)", 6.02, "10^9/л", None),
            ("Середній вміст гемоглобіну в еритроциті (МСН)", 30.2, "пг", None)]},
        "esculab-9003.pdf": {"vendor": "Esculab", "order": "9003", "day": "2026-01-10", "values": [
            ("Глюкоза", 5.1, "ммоль/л", None)]},
    })

    summary = labsync.sync(settings, user_id, "esculab", inline=True)
    assert summary["orders"] == 3  # the other person's order is not this record's
    assert (summary["imported"], summary["linked"], summary["pending"]) == (1, 1, 1)
    assert calls == ["esculab-9001.pdf"]  # the manual upload of 9002 was linked, not re-imported
    with connect(settings) as connection:
        tracked = {r["order_id"]: dict(r) for r in connection.execute("SELECT * FROM lab_orders")}
        assert connection.execute("SELECT COUNT(*) FROM documents WHERE order_identifier='9002'").fetchone()[0] == 1
    assert tracked["9002"]["state"] == "linked" and tracked["9002"]["document_id"] == manual
    assert tracked["9003"]["state"] == "pending"
    counts = json.loads(tracked["9001"]["crosscheck_json"])["counts"]
    assert counts["match"] == 3 and counts["info"] == 1 and counts["missing"] == 0  # service row filtered

    again = labsync.sync(settings, user_id, "esculab", inline=True)
    assert again["already"] == 2 and again["imported"] == again["linked"] == 0
    assert calls == ["esculab-9001.pdf"]

    orders[2] = order(9003, ready=2, total=2)
    later = labsync.sync(settings, user_id, "esculab", inline=True)
    assert later["imported"] == 1 and calls[-1] == "esculab-9003.pdf"


def test_a_refused_token_stops_the_sync_with_a_clear_reason(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([order(9001, ready=1, total=1)], {}))
    monkeypatch.setattr(common, "_http", router({("GET", "/api/customers/v2/orders"): 401}))
    with pytest.raises(common.LabSyncError) as caught:
        labsync.sync(settings, user_id, "esculab", inline=True)
    assert caught.value.key == "labsync.error_auth"
    assert labsync.account(settings, user_id, "esculab")["sync_detail_key"] == "labsync.error_auth"


def test_a_person_who_does_not_match_the_profile_needs_confirmation(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    sign_in_esculab(settings, user_id)
    labsync.check_account(settings, user_id, "esculab")
    with pytest.raises(common.LabSyncError) as caught:
        labsync.link_person(settings, user_id, "esculab", "222", "self", confirmed=False)
    assert caught.value.key == "labsync.error_confirm"
    linked = labsync.link_person(settings, user_id, "esculab", "222", "self", confirmed=True)
    assert linked["person"]["id"] == "222" and linked["consent"] == "owner"
    with connect(settings) as connection:
        assert connection.execute("SELECT mismatch_confirmed FROM lab_person_links").fetchone()[0] == 1
    # The list stays: every person on the lab account can be linked, one by one.
    assert labsync.account(settings, user_id, "esculab")["persons_json"] is not None


# --- Esculab sign-in (phone and a texted code, as the app) ------------------------

URL = "http://127.0.0.1:9"


def test_esculab_sign_in_texts_a_code_and_keeps_only_the_patient_token(monkeypatch):
    seen: list = []
    monkeypatch.setattr(common, "_http", router(esculab_sign_in_routes(), seen))
    sent = esculab.start_sign_in(URL, "+380 00 000 00 01", "", {"device_id": "ignored"})
    challenge = sent["challenge"]
    assert sent["phone"] == PHONE  # the form lab_accounts.phone and AccessPhone use
    assert challenge["code_length"] == 4 and 60 <= challenge["expires_in"] <= 900
    assert challenge["phone_masked"] == "+380" + "\u2022" * 7 + "01"
    method, path, headers = seen[0]
    assert (method, path) == ("POST", "/api/auth/authorise") and "Authorization" not in headers
    assert re.fullmatch(r"[0-9a-f-]{36}", challenge["token"])
    creds = esculab.verify_code(URL, challenge, " 12 34 ", {}, sent["phone"])
    assert creds == {"secret": TOKEN, "refresh_secret": "", "phone": PHONE,
                     "expires_at": "2100-01-01T00:00:00+00:00"}  # the PATIENT entry, expiry from the JWT
    assert seen[1][:2] == ("POST", "/api/auth/application/accept") and seen[1][2]["AccessPhone"] == PHONE
    # A fresh uuid per attempt, as the app makes one per sign-in.
    assert esculab.start_sign_in(URL, PHONE, "", {})["challenge"]["token"] != challenge["token"]


def test_esculab_reads_every_accept_reply_shape(monkeypatch):
    for reply in ({"tokens": [{"clientType": "PATIENT", "token": TOKEN, "exist": True}]},
                  [{"clientType": "patient", "tokens": {"token": TOKEN}}],
                  {"token": TOKEN, "exist": True, "phone": PHONE}):
        monkeypatch.setattr(common, "_http", router(esculab_sign_in_routes(reply)))
        sent = esculab.start_sign_in(URL, PHONE, "", {})
        assert esculab.verify_code(URL, sent["challenge"], CODE, {}, PHONE)["secret"] == TOKEN, reply


def test_esculab_sign_in_refusals_say_what_went_wrong(monkeypatch):
    def refused(reply, code=CODE):
        monkeypatch.setattr(common, "_http", router(esculab_sign_in_routes(reply)))
        sent = esculab.start_sign_in(URL, PHONE, "", {})
        with pytest.raises(common.LabSyncError) as caught:
            esculab.verify_code(URL, sent["challenge"], code, {}, PHONE)
        return caught.value.key

    assert refused(None, code="9999") == "labsync.password_error_code"  # the server's 400
    assert refused(None, code="12") == "labsync.password_error_code"  # not even sent
    assert refused({"status": 400, "error": "Bad Request", "message": "Error verifying code"}) \
        == "labsync.password_error_code"
    # A number Esculab knows only as a doctor, or with no patient profile yet.
    assert refused([{"clientType": "DOCTOR", "tokens": {"token": TOKEN}}]) == "labsync.esculab_error_no_patient"
    assert refused([{"clientType": "PATIENT", "tokens": {"token": TOKEN, "exist": False}}]) \
        == "labsync.esculab_error_no_patient"
    assert refused({"message": "User not found"}) == "labsync.esculab_error_no_patient"
    assert refused([{"clientType": "PATIENT", "tokens": {"token": "x"}}]) == "labsync.error_reply"
    for phone, key in (("call me", "labsync.password_error_phone"), ("+380000000002", "labsync.sms_error_phone")):
        monkeypatch.setattr(common, "_http", router(esculab_sign_in_routes()))
        with pytest.raises(common.LabSyncError) as caught:
            esculab.start_sign_in(URL, phone, "", {})
        assert caught.value.key == key
    monkeypatch.setattr(common, "_http", router({("POST", "/api/auth/authorise"): 429}))
    with pytest.raises(common.LabSyncError) as caught:
        esculab.start_sign_in(URL, PHONE, "", {})
    assert caught.value.key == "labsync.password_error_throttled"
    assert "labsync.esculab_error_no_patient" in labsync.ERROR_KEYS  # so the card shows it


def test_a_connection_stored_before_the_sms_sign_in_keeps_working(tmp_path: Path, monkeypatch):
    """A token pasted from the website was stored with no renewal secret; the
    signed-in calls are the same, so it checks and syncs as before."""
    settings, user_id, _ = make(tmp_path)
    labsync._store_credentials(settings, user_id, "esculab",
                               {"secret": TOKEN, "phone": PHONE, "expires_at": esculab.token_expiry(TOKEN)})
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    assert [person["id"] for person in labsync.check_account(settings, user_id, "esculab")] == ["111", "222"]
    assert labsync._client(settings, "esculab", TOKEN, PHONE).secret == TOKEN


# --- Synevo sync --------------------------------------------------------------------


def test_synevo_links_old_reports_by_content_downloads_new_ones_and_rolls_the_cookie(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    old = seed_doc(settings, user_id, vendor="Synevo", order="19", day="2016-07-19",
                   values=[("Гемоглобін", 150.0, "г/л", None), ("Еритроцити", 5.0, "10^12/л", None)])
    rolled = COOKIE.replace("a", "b")
    person = {"_id": "obj-1"}
    orders = [
        {"WebOrderId": "offline", "Barcode": "61000001", "OrderDate": "2016-07-19T09:00:00Z",
         "ExaminationDate": "2016-07-19T09:00:00Z", "StatusDescr": "Виконано", "Esoz": False,
         "Person": person, "Items": [{"IsReady": True}]},
        {"WebOrderId": "3300000001", "Barcode": "3600000001", "OrderDate": "2025-08-28T08:00:00Z",
         "ExaminationDate": "2025-08-28T08:00:00Z", "StatusDescr": "Виконано", "Esoz": False,
         "Person": person, "Items": [{"IsReady": True}]},
        {"WebOrderId": "3300000002", "Barcode": "3600000002", "OrderDate": "2025-09-01T08:00:00Z",
         "ExaminationDate": "2025-09-01T08:00:00Z", "StatusDescr": "Виконано", "Esoz": True,
         "Person": person, "Items": [{"IsReady": True}]},
    ]

    def result(barcode, web, name, value, unit):
        return {"Order": {"Barcode": barcode, "WebOrderId": web}, "Person": person, "ReadyAt": "2025-08-29T10:00:00Z",
                "Service": {"NameRegional": [{"Language": "uk", "Value": "Аналіз"}]},
                "Results": [{"Name": name, "Val": value, "Unit": unit, "InRange": True, "Range": "1 - 2\r\n3 - 4"}]}

    results = [result("61000001", "offline", "Аналіз крові: Гемоглобін", "150", "г/л"),
               result("61000001", "offline", "Еритроцити", "5.0", "10^12/л"),
               result("3600000001", "3300000001", "Глюкоза", "5.1", "ммоль/л"),
               result("3600000001", "3300000001", "Методи/Лабораторне обладнання:", "Аналізатор", None)]
    seen: list = []

    def session(body, headers):
        assert headers["Cookie"].startswith(f"next-auth.session-token={COOKIE}")
        return 200, [f"next-auth.session-token={rolled}; Path=/; HttpOnly"], json.dumps(
            # The real shape: Synevo leaves `user` empty in a live session.
            {"user": {}, "expires": "2100-01-01T00:00:00.000Z", "accessToken": "x", "clientId": "c"}).encode()

    def cookie_needed(reply):
        return lambda body, headers: reply if "next-auth.session-token=" in headers.get("Cookie", "") else 401

    routes = {
        ("GET", "/api/auth/session"): session,
        ("GET", "/api/cabinet/user-persons"): cookie_needed([{
            "ProfileId": "p1", "PersonId": "obj-1", "FirstName": "Test", "LastName": "Person",
            "BirthDate": "1990-03-14T00:00:00.000Z", "Gender": "M", "Phone": PHONE, "Email": "x@y.test"}]),
        ("POST", "/api/cabinet/get-orders"): cookie_needed({"pagesCount": 1, "items": orders}),
        ("POST", "/api/cabinet/get-results"): cookie_needed({"pagesCount": 1, "items": results}),
        ("POST", "/api/order/download-pdf"): cookie_needed(
            {"res": "ok", "results": {"main": "http://127.0.0.1:9/files/main.pdf", "extra": []}}),
        ("GET", "/files/main.pdf"): lambda body, headers: 401 if "Cookie" in headers else (200, [], b"%PDF-1.4 s"),
    }
    monkeypatch.setattr(common, "_http", router(routes, seen))
    calls = stub_intake(monkeypatch, settings, user_id, {
        "synevo-3600000001.pdf": {"vendor": "Synevo", "order": "3600000001", "day": "2025-08-28",
                                  "values": [("Глюкоза", 5.1, "ммоль/л", None)]},
    })
    labsync.save_credentials(settings, user_id, "synevo", {"token": COOKIE})
    people = labsync.check_account(settings, user_id, "synevo")
    assert people[0]["match_ids"] == ["p1", "obj-1"] and "Phone" not in people[0]
    assert labsync.account(settings, user_id, "synevo")["secret"] == rolled  # NextAuth rolled it
    labsync.link_person(settings, user_id, "synevo", "p1", "self", confirmed=False)

    summary = labsync.sync(settings, user_id, "synevo", inline=True)
    assert (summary["linked"], summary["imported"], summary["unavailable"]) == (1, 1, 1)
    assert calls == ["synevo-3600000001.pdf"]
    with connect(settings) as connection:
        tracked = {r["order_id"]: dict(r) for r in connection.execute("SELECT * FROM lab_orders")}
    assert tracked["61000001"]["document_id"] == old  # no number on it: linked by date and values
    assert json.loads(tracked["61000001"]["crosscheck_json"])["counts"]["match"] == 2
    assert tracked["3600000002"]["error_key"] == "labsync.unavailable_esoz"
    assert json.loads(tracked["3600000001"]["crosscheck_json"])["counts"]["info"] == 1


def test_synevo_refuses_a_file_link_to_another_host(monkeypatch):
    client = synevo.Client("https://www.synevo.ua", COOKIE)
    monkeypatch.setattr(common, "_http", router({("POST", "/api/order/download-pdf"): {
        "res": "ok", "results": {"main": "https://evil.example/x.pdf"}}}))
    with pytest.raises(common.LabSyncError) as caught:
        client.pdfs({"remote_ref": "1"}, {"id": "p1"})
    assert caught.value.key == "labsync.error_pdf"
    assert client._file_allowed("https://synevostatic.blob.core.windows.net/results/x.pdf?sig=1")


# --- web --------------------------------------------------------------------------------


def linked_document(settings, user_id, monkeypatch):
    document_id = seed_doc(settings, user_id, vendor="Esculab", order="9002", day="2025-05-01", values=[
        ("Креатинін", 68.3, "мкмоль/л", None), ("Сечовина", 5.0, "ммоль/л", None)])
    rows = {"9002": [es_row("Креатинін", "68.3", "мкмоль/л"), es_row("Сечовина", "5.5", "ммоль/л"),
                     es_row("Сечова кислота", "361", "мкмоль/л")]}
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([order(9002, ready=3, total=3)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    return document_id


def test_document_panel_verifies_only_matches_on_a_press_with_csrf(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    document_id = linked_document(settings, user_id, monkeypatch)
    page = client.get(f"/documents/{document_id}")
    assert 'id="lab-crosscheck"' in page.text
    assert "Mark the 1 value that matches the lab record as verified" in page.text
    assert 'action="/documents/' + document_id + '/observations"' in page.text  # prefilled add for the missing row
    ids = [f"{document_id}-0", f"{document_id}-1"]  # the second one does not match
    # The per-row mark sits on the matching card only.
    cards = {i: page.text.split(f'id="observation-{i}"', 1)[1].split("</article>", 1)[0] for i in ids}
    assert "matches lab record" in cards[ids[0]] and "matches lab record" not in cards[ids[1]]
    refused = client.post(f"/documents/{document_id}/lab-verify", data={"observation_ids": ids}, follow_redirects=False)
    assert refused.status_code == 403
    done = client.post(f"/documents/{document_id}/lab-verify",
                       data={"observation_ids": ids, "csrf_token": csrf(settings, user_id)}, follow_redirects=False)
    assert done.status_code == 303 and "lab_verified=1" in done.headers["location"]
    with connect(settings) as connection:
        states = dict(connection.execute(
            "SELECT id, verification_status FROM observations WHERE document_id=? "
            "AND extraction_method <> 'derived_ckd_epi_2021'", (document_id,)).fetchall())
        # Verifying the creatinine is what lets the record calculate its eGFR.
        assert [tuple(row) for row in connection.execute(
            "SELECT verification_status FROM observations WHERE document_id=? "
            "AND extraction_method = 'derived_ckd_epi_2021'", (document_id,))] == [("verified",)]
        audit = connection.execute(
            "SELECT details_json FROM audit_events WHERE action='observation_verify'").fetchall()
    assert states == {ids[0]: "verified", ids[1]: "extracted"}
    assert len(audit) == 1 and json.loads(audit[0][0])["via"] == "lab_crosscheck"
    assert "token_kind" not in json.loads(audit[0][0])  # a person's own press
    # The owner's agent credential verifying on their behalf says so in the trail.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='extracted' WHERE id=?", (ids[0],))
    assert labsync.verify_matches(settings, user_id, document_id, ids, "agent") == 1
    with connect(settings) as connection:
        latest = connection.execute("SELECT details_json FROM audit_events WHERE action='observation_verify' "
                                    "ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    assert json.loads(latest)["token_kind"] == "agent"
    # Nothing in the page or the audit trail carries the credential.
    assert TOKEN not in page.text and TOKEN not in json.dumps([tuple(r) for r in audit])


def test_profile_card_never_echoes_the_secret_and_routes_need_csrf(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    form = {"phone": "000 000 001"}
    assert client.post("/profile/lab/esculab/credentials", data=form, follow_redirects=False).status_code == 403
    card = client.get("/profile?tab=connections").text
    card = card[card.index('id="lab-esculab"'):card.index('id="lab-synevo"')]
    assert "as in the Esculab app" in card and "The number and the code go only to Esculab" in card
    assert 'name="phone"' in card and 'name="password"' not in card and 'name="token"' not in card
    assert "accessKey" not in card and "console" not in card  # no browser steps any more
    sent = client.post("/profile/lab/esculab/credentials", data={**form, "csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert "lab_msg=labsync.password_code_sent" in sent.headers["location"]
    card = client.get(sent.headers["location"]).text
    assert 'name="code"' in card and "+380" + "\u2022" * 7 + "01" in card and PHONE not in card
    wrong = client.post("/profile/lab/esculab/credentials", data={"code": "9999", "csrf_token": csrf(settings, user_id)},
                        follow_redirects=False)
    assert "lab_msg=labsync.password_error_code" in wrong.headers["location"]
    saved = client.post("/profile/lab/esculab/credentials", data={"code": CODE, "csrf_token": csrf(settings, user_id)},
                        follow_redirects=False)
    assert "lab_msg=labsync.saved_checked" in saved.headers["location"]  # signing in checks the account at once
    page = client.get(saved.headers["location"])
    assert TOKEN not in page.text
    assert "..." + TOKEN[-6:] in page.text and "1 Jan 2100" in page.text  # tail and expiry only
    checked = client.post("/profile/lab/esculab/check", data={"csrf_token": csrf(settings, user_id)}, follow_redirects=False)
    assert "saved_checked" in checked.headers["location"]
    page = client.get("/profile?tab=connections")
    assert re.search(r" -\s+matches", page.text) and re.search(r" -\s+differs, needs your confirmation", page.text)
    started: list = []
    monkeypatch.setattr(labsync, "start_sync", lambda s, uid, key: started.append(key))
    assert "error_no_patient" in client.post("/profile/lab/esculab/sync", data={"csrf_token": csrf(settings, user_id)},
                                             follow_redirects=False).headers["location"]
    linked = client.post("/profile/lab/esculab/link", data={"person_id": "111", "target": "self",
                                                            "csrf_token": csrf(settings, user_id)},
                         follow_redirects=False)
    assert "link_saved_self" in linked.headers["location"]
    assert started == ["esculab"]  # linking oneself syncs right away
    client.post("/profile/lab/esculab/sync", data={"csrf_token": csrf(settings, user_id)})
    assert started == ["esculab", "esculab"]
    with connect(settings) as connection:
        details = " ".join(r[0] for r in connection.execute("SELECT details_json FROM audit_events"))
    assert TOKEN not in details and PHONE not in details


def test_admin_off_hides_everything_and_a_new_address_forgets_credentials(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=())
    page = client.get("/profile?tab=connections")
    assert 'id="lab-esculab"' not in page.text
    assert client.post("/profile/lab/esculab/check", data={"csrf_token": csrf(settings, user_id)}).status_code == 404
    admin_page = client.get("/admin/lab-connections")
    assert admin_page.status_code == 200 and 'id="lab-admin-esculab"' in admin_page.text
    bad = client.post("/admin/lab-connections/esculab", data={"enabled": "1", "url": "http://esculab.com",
                                                                "csrf_token": csrf(settings, user_id)},
                      follow_redirects=False)
    assert "error=labsync.error_url" in bad.headers["location"]
    client.post("/admin/lab-connections/esculab", data={"enabled": "1", "url": "http://127.0.0.1:9",
                                                          "csrf_token": csrf(settings, user_id)})
    assert labsync.active(settings, "esculab")
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    sign_in_esculab(settings, user_id)
    assert 'id="lab-esculab"' in client.get("/profile?tab=connections").text
    moved = client.post("/admin/lab-connections/esculab", data={"enabled": "1", "url": "https://esculab.com",
                                                                 "csrf_token": csrf(settings, user_id)},
                        follow_redirects=False)
    assert "done=saved_forgot" in moved.headers["location"]
    assert labsync.account(settings, user_id, "esculab")["secret"] == ""


def test_admin_page_needs_an_administrator(tmp_path: Path):
    settings, user_id, client = make(tmp_path, admin=False)
    assert client.get("/admin/lab-connections").status_code == 403
    assert client.post("/admin/lab-connections/esculab",
                       data={"enabled": "1", "url": "https://esculab.com", "csrf_token": csrf(settings, user_id)}
                       ).status_code == 403


def test_a_guest_link_sees_no_connection_and_cannot_sync_or_verify(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    document_id = linked_document(settings, user_id, monkeypatch)
    _, secret = create_access_token(settings, user_id, "guest", "Doctor", expires_at="2100-01-01T00:00:00+00:00")
    with TestClient(create_app(settings)) as guest:
        guest.get(f"/t/{secret}")
        page = guest.get(f"/documents/{document_id}")
        assert page.status_code == 200 and 'id="lab-crosscheck"' not in page.text
        assert guest.post(f"/documents/{document_id}/lab-verify", data={"observation_ids": [f"{document_id}-0"]}).status_code == 403
        assert guest.post("/profile/lab/esculab/sync", data={}).status_code == 403
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations WHERE verification_status='verified'").fetchone()[0] == 0


def test_synevo_takes_a_live_session_with_an_empty_user(monkeypatch):
    """Synevo's /api/auth/session carries `user: {}` for a signed-in cabinet;
    only a bare {} means signed out."""
    client = synevo.Client("https://www.synevo.ua", COOKIE)
    persons = [{"ProfileId": "p1", "FirstName": "T", "LastName": "P", "BirthDate": "1990-03-14T00:00:00Z", "Gender": "M"}]
    monkeypatch.setattr(common, "_http", router({
        ("GET", "/api/auth/session"): {"user": {}, "expires": "2100-01-01T00:00:00.000Z", "accessToken": "x"},
        ("GET", "/api/cabinet/user-persons"): persons}))
    people, expires = client.check()
    assert [person["id"] for person in people] == ["p1"] and expires == "2100-01-01T00:00:00"
    monkeypatch.setattr(common, "_http", router({("GET", "/api/auth/session"): {}}))
    with pytest.raises(common.LabSyncError) as caught:
        client.check()
    assert caught.value.key == "labsync.error_auth"


def test_lab_steps_link_out_and_offer_copy_and_a_rejected_key_says_so(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    page = client.get("/profile?tab=connections").text
    assert 'href="http://127.0.0.1:9/personal-cabinet/my-results" target="_blank"' in page
    assert page.count('class="secondary an-lab-copy"') == 1  # Esculab signs in with a code, no steps to copy
    assert "<code>next-auth.session-token</code>" in page
    client.post("/profile/lab/synevo/credentials", data={"token": COOKIE, "csrf_token": csrf(settings, user_id)})
    rejected = client.get("/profile?tab=connections&lab=synevo&lab_msg=labsync.error_auth").text
    card = rejected[rejected.index('id="lab-synevo"'):]
    assert "key rejected" in card[:2000]


# --- one lab account, several people: the family inbox ------------------------------


def family_member(settings, owner_id: str, email: str, *, dob="1990-01-01", sex="female", share=True) -> str:
    """Another account with a profile; ``share`` makes it family (the holder
    shares their record with it)."""
    member = create_user(settings, email, email.split("@")[0], PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Family Person', ?, ?, ?)""",
            (f"patient-{member}", member, dob, sex, utc_now()),
        )
        if share:
            connection.execute(
                "INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), owner_id, email, member, utc_now()),
            )
    return member


def family_routes(orders, rows_111, rows_222):
    routes = esculab_routes(orders, rows_111)

    def authorised(reply):
        return lambda body, headers: reply if headers.get("Authorization") == f"Bearer {TOKEN}" else 401

    for order_id, order_rows in rows_222.items():
        routes[("GET", f"/api/customers/getOrdersResult/{order_id}/222")] = authorised(order_rows)
        routes[("GET", f"/api/results/getResults/222/{order_id}")] = authorised(b"%PDF-1.4 synthetic " + order_id.encode())
    return routes


def test_a_family_members_results_wait_for_their_acceptance(tmp_path: Path, monkeypatch):
    settings, holder, _ = make(tmp_path)
    member = family_member(settings, holder, "member@example.test")
    stranger = family_member(settings, holder, "stranger@example.test", share=False)
    orders = [order(9001, ready=1, total=1), order(9100, ready=1, total=1, patient=222),
              order(9101, ready=1, total=2, status="PARTLY_DONE", patient=222, dt=RECENT),
              order(9102, ready=1, total=1, patient=222)]
    rows_222 = {"9100": [es_row("Глюкоза", "5.1", "ммоль/л")], "9101": [es_row("Креатинін", "70", "мкмоль/л")],
                "9102": [es_row("Сечовина", "4.2", "ммоль/л")]}
    monkeypatch.setattr(common, "_http", router(family_routes(
        orders, {"9001": [es_row("Гемоглобін (HGB)", "151", "г/л")]}, rows_222)))
    sign_in_esculab(settings, holder)
    labsync.check_account(settings, holder, "esculab")
    kicked: list = []
    monkeypatch.setattr(labsync, "start_sync", lambda s, uid, key: kicked.append(uid))

    # Only family can receive.
    with pytest.raises(common.LabSyncError) as caught:
        labsync.link_person(settings, holder, "esculab", "222", stranger, confirmed=True)
    assert caught.value.key == "labsync.error_link_target"
    assert {c["id"] for c in labsync.link_candidates(settings, holder)} == {holder, member}
    labsync.link_person(settings, holder, "esculab", "111", "self", confirmed=False)
    linked = labsync.link_person(settings, holder, "esculab", "222", member, confirmed=False)  # DOB and sex agree
    assert linked["consent"] == "asked"

    calls = stub_intake(monkeypatch, settings, holder, {
        "esculab-9001.pdf": {"vendor": "Esculab", "order": "9001", "day": "2026-01-10",
                             "values": [("Гемоглобін (HGB)", 151.0, "г/л", None)]},
        "esculab-9100.pdf": {"vendor": "Esculab", "order": "9100", "day": "2026-01-10",
                             "values": [("Глюкоза", 5.1, "ммоль/л", None)]},
    })
    summary = labsync.sync(settings, holder, "esculab", inline=True)
    assert (summary["people"], summary["imported"], summary["awaiting"], summary["pending"]) == (2, 1, 2, 1)
    assert calls == ["esculab-9001.pdf"]  # nothing is downloaded for the member before they accept
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents WHERE owner_user_id=?", (member,)).fetchone()[0] == 0
    assert labsync.inbox_count(settings, {"id": member}) == 2
    entry = labsync.inbox(settings, {"id": member})[0]
    assert entry["holder"] == "Lab" and entry["consent"] == "asked" and entry["match"]["ok"]
    assert sorted(o["order_id"] for o in entry["awaiting"]) == ["9100", "9102"]
    assert any(row["test"] == "Глюкоза" for o in entry["awaiting"] for row in o["rows"])
    assert labsync.inbox(settings, {"id": holder}) == []  # the holder's own people are not an inbox
    card = labsync.profile_cards(settings, {"id": holder})[0]
    family = next(p for p in card["persons"] if p["id"] == "222")
    assert family["link"]["consent"] == "asked" and family["link"]["states"] == {"awaiting": 2, "pending": 1}
    assert [o["order_id"] for o in card["orders"]] == ["9001"]  # the holder's table is their own record

    # Somebody else cannot decide for the member.
    with pytest.raises(common.LabSyncError):
        labsync.decide_orders(settings, holder, "esculab", holder, "222", ["9100"], accept=True)
    assert labsync.decide_orders(settings, member, "esculab", holder, "222", ["9102"], accept=False) == 1
    assert labsync.decide_orders(settings, member, "esculab", holder, "222", ["9100"], accept=True) == 1
    assert kicked == [holder]  # accepting starts the holder's sync
    labsync.sync(settings, holder, "esculab", inline=True)
    assert calls == ["esculab-9001.pdf", "esculab-9100.pdf"]
    with connect(settings) as connection:
        states = dict(connection.execute(
            "SELECT order_id, state FROM lab_orders WHERE owner_user_id=?", (member,)).fetchall())
        declined_rows = connection.execute(
            "SELECT rows_json FROM lab_orders WHERE owner_user_id=? AND order_id='9102'", (member,)).fetchone()[0]
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE owner_user_id=? AND order_identifier='9100'", (member,)
        ).fetchone()[0] == 1
    assert states == {"9100": "imported", "9101": "pending", "9102": "declined"}
    assert declined_rows is None  # a declined result keeps nothing of its values

    # Stopping the link drops what waits, and the holder's runs skip that person.
    labsync.set_consent(settings, member, "esculab", holder, "222", "refused")
    again = labsync.sync(settings, holder, "esculab", inline=True)
    assert again["people"] == 1
    with connect(settings) as connection:
        left = dict(connection.execute(
            "SELECT order_id, state FROM lab_orders WHERE owner_user_id=?", (member,)).fetchall())
    assert left == {"9100": "imported", "9102": "declined"}

    # Unlinking keeps what the member accepted; linking again asks again.
    labsync.unlink_person(settings, holder, "esculab", "222")
    assert labsync.inbox(settings, {"id": member}) == []
    assert labsync.link_person(settings, holder, "esculab", "222", member, confirmed=False)["consent"] == "asked"


def test_two_lab_profiles_of_one_person_feed_one_record(tmp_path: Path, monkeypatch):
    """A lab keeps a second profile after a surname change: both are linked to
    the same record, each profile's orders arrive, and nothing arrives twice."""
    settings, holder, client = make(tmp_path)
    persons = [
        {"id": 111, "firstname": "Test", "lastname": "Person", "fathername": "", "birthday": "1990-03-14", "sex": "M",
         "main": True},
        {"id": 333, "firstname": "Test", "lastname": "Maiden", "fathername": "", "birthday": "1990-03-14", "sex": "M",
         "main": False},
    ]
    orders = [order(9001, ready=1, total=1), order(9301, ready=1, total=1, patient=333)]
    routes = esculab_routes(orders, {"9001": [es_row("Гемоглобін (HGB)", "151", "г/л")]}, persons=persons)
    routes[("GET", "/api/customers/getOrdersResult/9301/333")] = lambda body, headers: [es_row("Глюкоза", "5.1", "ммоль/л")]
    routes[("GET", "/api/results/getResults/333/9301")] = lambda body, headers: b"%PDF-1.4 synthetic 9301"
    monkeypatch.setattr(common, "_http", router(routes))
    sign_in_esculab(settings, holder)
    labsync.check_account(settings, holder, "esculab")

    labsync.link_person(settings, holder, "esculab", "111", "self", confirmed=False)
    card = labsync.profile_cards(settings, {"id": holder})[0]
    second = next(p for p in card["persons"] if p["id"] == "333")
    me = next(o for o in second["options"] if o["self"])
    assert me["also"] == ["Person Test"] and second["selected"] == "self" and second["lab_id"] == "333"
    assert labsync.link_person(settings, holder, "esculab", "333", "self", confirmed=False)["consent"] == "owner"

    calls = stub_intake(monkeypatch, settings, holder, {
        "esculab-9001.pdf": {"vendor": "Esculab", "order": "9001", "day": "2026-01-10",
                             "values": [("Гемоглобін (HGB)", 151.0, "г/л", None)]},
        "esculab-9301.pdf": {"vendor": "Esculab", "order": "9301", "day": "2026-01-10",
                             "values": [("Глюкоза", 5.1, "ммоль/л", None)]},
    })
    summary = labsync.sync(settings, holder, "esculab", inline=True)
    assert (summary["people"], summary["imported"]) == (2, 2)
    assert sorted(calls) == ["esculab-9001.pdf", "esculab-9301.pdf"]
    again = labsync.sync(settings, holder, "esculab", inline=True)
    assert (again["imported"], again["already"]) == (0, 2) and len(calls) == 2
    with connect(settings) as connection:
        assert dict(connection.execute(
            "SELECT order_id, remote_person_id FROM lab_orders WHERE owner_user_id=?", (holder,)).fetchall()) == {
            "9001": "111", "9301": "333"}
    page = client.get("/profile?tab=connections").text
    assert "lab ID 333" in page and "also receives Maiden Test" in page and "also receives Person Test" in page
    assert page.count("Goes to your record") == 2

    # Our own calculation beside the parsed values (eGFR from creatinine) is
    # not the lab's to confirm, so it never counts as "not in the lab record".
    with connect(settings) as connection:
        row = dict(connection.execute(
            "SELECT * FROM observations WHERE owner_user_id=? AND raw_name='Глюкоза'", (holder,)).fetchone())
        row.update(id="derived-egfr", raw_name="eGFR (CKD-EPI 2021)", extraction_method="derived_ckd_epi_2021")
        connection.execute(f"INSERT INTO observations({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                           tuple(row.values()))
    counts = {o["order_id"]: o["counts"] for o in labsync.profile_cards(settings, {"id": holder})[0]["orders"]}
    assert counts["9301"]["extra"] == 0 and counts["9301"]["match"] == 1


def test_the_inbox_routes_need_the_member_and_csrf(tmp_path: Path, monkeypatch):
    settings, holder, holder_client = make(tmp_path)
    member = family_member(settings, holder, "member@example.test")
    orders = [order(9100, ready=1, total=1, patient=222)]
    monkeypatch.setattr(common, "_http", router(family_routes(
        orders, {}, {"9100": [es_row("Глюкоза", "5.1", "ммоль/л")]})))
    sign_in_esculab(settings, holder)
    labsync.check_account(settings, holder, "esculab")
    kicked: list = []
    monkeypatch.setattr(labsync, "start_sync", lambda s, uid, key: kicked.append(uid))
    linked = holder_client.post("/profile/lab/esculab/link", data={
        "person_id": "222", "target": member, "csrf_token": csrf(settings, holder)}, follow_redirects=False)
    assert "link_saved_other" in linked.headers["location"] and kicked == [holder]
    stub_intake(monkeypatch, settings, holder, {})
    labsync.sync(settings, holder, "esculab", inline=True)

    client = TestClient(create_app(settings))
    token, _ = create_session(settings, member)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    home = client.get("/")
    assert "1 lab result shared by a family member is waiting for your decision." in home.text
    page = client.get("/profile?tab=connections")
    assert "Lab results shared with you" in page.text and "Глюкоза" in page.text and TOKEN not in page.text
    form = {"account": holder, "person_id": "222", "order_ids": "9100", "decision": "accept"}
    assert client.post("/profile/lab-inbox/esculab/decide", data=form, follow_redirects=False).status_code == 403
    done = client.post("/profile/lab-inbox/esculab/decide", data={**form, "csrf_token": csrf(settings, member)},
                       follow_redirects=False)
    assert "inbox_accepted" in done.headers["location"] and kicked == [holder, holder]
    always = client.post("/profile/lab-inbox/esculab/consent",
                         data={"account": holder, "person_id": "222", "consent": "accepted",
                               "csrf_token": csrf(settings, member)}, follow_redirects=False)
    assert "inbox_consent_saved" in always.headers["location"]
    with connect(settings) as connection:
        assert connection.execute("SELECT consent FROM lab_person_links").fetchone()[0] == "accepted"
        trail = [r[0] for r in connection.execute(
            "SELECT action FROM audit_events WHERE owner_user_id=? ORDER BY id", (member,))]
    assert "labsync_results_accepted" in trail and "labsync_link_consent" in trail
    assert "labsync_person_linked" in trail  # the member's own trail says who linked results to them
    client.cookies.set("anamna_lang", "uk")
    assert "Результати аналізів, якими з вами поділилися" in client.get("/profile?tab=connections").text


def test_the_migration_moves_an_existing_choice_into_a_link(tmp_path: Path):
    import sqlite3

    from anamna.db import MIGRATIONS_DIR
    from anamna.ingest.classifier import LAB_SYNC_FILENAME_RE
    from anamna.ingest.pipeline import stable_id

    settings = settings_for(tmp_path)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version >= 36:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (version,))
    connection.execute(
        """INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at)
           VALUES ('u1', 'a@example.test', 'A', x'00', x'00', 'x')""")
    connection.execute(
        """INSERT INTO lab_accounts(user_id, provider, secret, remote_person_id, remote_person_json,
               mismatch_confirmed, updated_at) VALUES ('u1', 'eskulab', 's', '111', '{"id": "111"}', 1, 'x')""")
    connection.execute("INSERT INTO vendors(id, canonical_name, created_at) "
                       "VALUES ('db590f97-b1bb-5631-9956-2db03e796b81', 'EskuLab', 'x')")
    connection.execute("INSERT INTO vendor_aliases(vendor_id, alias) "
                       "VALUES ('db590f97-b1bb-5631-9956-2db03e796b81', 'ESCULAB')")
    connection.execute(
        """INSERT INTO lab_orders(owner_user_id, provider, remote_person_id, order_id, state, first_seen_at,
               last_synced_at) VALUES ('u1', 'eskulab', '111', '9001', 'imported', 'x', 'x')""")
    connection.commit()
    connection.close()
    migrate(settings)
    with connect(settings) as connection:
        link = connection.execute("SELECT * FROM lab_person_links").fetchone()
        assert (link["target_user_id"], link["consent"], link["mismatch_confirmed"]) == ("u1", "owner", 1)
        assert connection.execute("SELECT account_user_id FROM lab_orders").fetchone()[0] == "u1"
        assert connection.execute("SELECT secret FROM lab_accounts").fetchone()[0] == "s"
        # 050: the keys and the vendor take the lab's own spelling; the vendor's id is the one its name derives.
        assert {r[0] for r in connection.execute(
            "SELECT provider FROM lab_accounts UNION SELECT provider FROM lab_orders")} == {"esculab"}
        assert connection.execute("SELECT v.id, v.canonical_name FROM vendor_aliases a JOIN vendors v "
                                  "ON v.id=a.vendor_id").fetchone()[:] == (stable_id("vendor", "Esculab"), "Esculab")
        # Files downloaded before the rename keep their old names on disk and still give the order id.
        assert [LAB_SYNC_FILENAME_RE.match(n).group(1) for n in ("eskulab-13368192", "ekspert-100169")] == [
            "13368192", "100169"]
        # A new provider needs no table rebuild any more.
        connection.execute("INSERT INTO lab_accounts(user_id, provider, updated_at) VALUES ('u1', 'newlab', 'x')")


# --- what a live Expert Hospital account showed (2026-11-06) ----------------------------------


def test_a_report_without_a_unit_agrees_with_the_labs_unit_and_glued_names_pair():
    result = labsync.cross_check(
        [row("АЛАТ(АЛТ)", "46", "од/л", state="critical"), row("Лейкоцити (WBC)", "0-1", "в п/з"),
         row("Вітамін D загальний", "32.122", "нг/мл")],
        [obs("АЛАТ(АЛТ)", 46.0, None, interp="high"), obs("Лейкоцити (WBC), в п/з", "0-1"),
         obs("Total 25-hydroxyvitamin D", 32.122, "ng/mL")],
    )
    by_name = {item["lab"]["test"]: item for item in result["items"]}
    alt = by_name["АЛАТ(АЛТ)"]
    assert alt["cls"] == "match" and alt["unit_from_lab"] and not alt["unit_differs"]
    assert by_name["Лейкоцити (WBC)"]["cls"] == "match"  # «, в п/з» glued to the name by the report
    # The only unpaired row and value agree on the number: one test, two names.
    assert by_name["Вітамін D загальний"]["cls"] == "name_mismatch"
    assert result["counts"]["extra"] == result["counts"]["missing"] == 0


def test_a_lone_leftover_with_a_different_value_stays_missing_and_extra():
    result = labsync.cross_check([row("Вітамін D загальний", "32.1", "нг/мл")],
                                 [obs("Total 25-hydroxyvitamin D", 40.0, "ng/mL")])
    assert (result["counts"]["missing"], result["counts"]["extra"]) == (1, 1)


def test_an_order_without_lab_values_has_no_cross_check(tmp_path: Path):
    settings, user_id, _ = make(tmp_path)
    with connect(settings) as connection:
        tracked = {"rows_json": "[]", "order_id": "1", "remote_ref": None, "document_id": None, "provider": "esculab"}
        assert labsync.check_order(connection, user_id, tracked) is None


def test_the_sync_links_the_exact_report_adopts_a_missing_unit_and_calls_a_known_pdf_linked(
        tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    liver = [("Білірубін загальний", 11.5, "мкмоль/л", None), ("АЛАТ(АЛТ)", 37.0, None, None),
             ("ГГТ", 33.0, None, None)]
    exact = seed_doc(settings, user_id, vendor="Esculab", order=None, day="2025-08-02", values=liver)
    # The bigger panel of the same morning holds the same values and one more.
    seed_doc(settings, user_id, vendor="Esculab", order=None, day="2025-08-02",
             values=[*liver, ("Білок загальний", 70.0, "г/л", None)])
    rows = {"9500": [es_row("Білірубін загальний", "11.5", "мкмоль/л"), es_row("АЛАТ(АЛТ)", "37", "од/л"),
                     es_row("ГГТ", "33", "од/л")]}
    orders = [order(9500, ready=3, total=3, dt="2025-08-02 08:00")]
    connect_esculab(settings, user_id, monkeypatch, esculab_routes(orders, rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    with connect(settings) as connection:
        tracked = connection.execute("SELECT state, document_id FROM lab_orders WHERE order_id='9500'").fetchone()
        units = dict(connection.execute(
            "SELECT raw_name, unit_raw FROM observations WHERE document_id=?", (exact,)).fetchall())
        audit = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='observation_unit_from_lab'").fetchone()[0]
    assert tuple(tracked) == ("linked", exact)
    assert units["АЛАТ(АЛТ)"] == "од/л" and units["ГГТ"] == "од/л" and units["Білірубін загальний"] == "мкмоль/л"
    assert audit == 2

    # A PDF the lab serves that is byte-for-byte one already uploaded is a link.
    pdf = b"%PDF-1.4 synthetic 9600"
    target = settings.source_dir / "known.pdf"
    target.write_bytes(pdf)
    from anamna.ingest.extract import file_sha256
    known = seed_doc(settings, user_id, vendor="Esculab", order=None, day="2025-09-01", values=[])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET sha256=? WHERE id=?", (file_sha256(target), known))
    target.unlink()
    orders.append(order(9600, ready=1, total=1, dt="2025-09-01 08:00"))
    routes = esculab_routes(orders, {**rows, "9600": [es_row("Глюкоза", "5.1", "ммоль/л")]})
    routes[("GET", "/api/results/getResults/111/9600")] = lambda body, headers: pdf
    monkeypatch.setattr(common, "_http", router(routes))
    summary = labsync.sync(settings, user_id, "esculab", inline=True)
    assert summary["linked"] == 1 and summary["imported"] == 0
    with connect(settings) as connection:
        assert tuple(connection.execute(
            "SELECT state, document_id FROM lab_orders WHERE order_id='9600'").fetchone()) == ("linked", known)
