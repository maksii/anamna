"""The Diagnoses pages: the record, the form, the detail page, possible and found diagnoses.

The matching of possible diagnoses is replaced at its seam (its rules are tested in
test_diagnosis_matrix.py and the refresh job in test_diagnoses_job.py), and the AI
switch is set by hand, so nothing here reaches a model.
"""

from __future__ import annotations

import re
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from anamna import ai, diagnosis_matrix, factor_jobs, icd10, security
from anamna.db import connect, migrate, utc_now
from anamna.i18n import MESSAGES
from anamna.security import create_access_token, create_user
from anamna.web import diagnoses_routes
from anamna.web.app import create_app
from anamna.web.changes import verdict_state

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    security._attempts.clear()
    factor_jobs.reset()
    # The matching is replaced at its seam: test_diagnosis_matrix.py and test_diagnoses_job.py cover it.
    monkeypatch.setattr(diagnosis_matrix, "refresh", lambda *args, **kwargs: {"opened": 0, "cleared": 0})
    yield
    security._attempts.clear()
    factor_jobs.reset()


@dataclass
class World:
    settings: object
    alpha: str
    bravo: str
    patient: str
    document: str


@pytest.fixture
def world(tmp_path) -> World:
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    bravo = create_user(settings, "bravo@example.test", "Bravo", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_patient(settings, bravo, "Bravo Patient")
    document = seed_document(settings, alpha, patient, "Alpha consultation", "alpha-dx-consult.txt")
    return World(settings, alpha, bravo, patient, document)


@pytest.fixture
def clients(world):
    """Opens clients that stay signed in for the length of the test."""
    with ExitStack() as stack:
        def open_as(email: str) -> TestClient:
            client = stack.enter_context(TestClient(create_app(world.settings)))
            login(client, email)
            return client

        yield open_as


def csrf(world: World, client: TestClient) -> str:
    return csrf_for(world.settings, client)


def rows(world: World, sql: str, args: tuple = ()) -> list:
    with connect(world.settings) as connection:
        return connection.execute(sql, args).fetchall()


def diagnosis_fields(**overrides) -> dict:
    data = {
        "code": "E78.2", "name": "", "status": "active", "certainty": "confirmed",
        "diagnosed_on": "2024-03-01", "resolved_on": "", "dates_approximate": "", "clinician": "Dr Test",
        "document_id": "", "notes": "", "suspicion_id": "",
    }
    data.update(overrides)
    return data


def post_new(world: World, client: TestClient, **fields):
    return client.post("/diagnoses/new", data={**diagnosis_fields(**fields), "csrf_token": csrf(world, client)},
                       follow_redirects=False)


def diagnosis_id_for(world: World, code: str, *, name: str = "") -> str:
    row = rows(world, "SELECT id FROM diagnoses WHERE owner_user_id = ? AND code = ? AND name = ?",
               (world.alpha, code, name))
    return row[0]["id"]


def add_suspicion(world: World, *, rule_id: str = "lipid_mixed", code: str = "E78.2") -> str:
    """An open possible diagnosis, as the matrix would have raised it from the person's results."""
    suspicion_id = f"susp-{rule_id}"
    evidence = (
        '[{"metric": "LDL cholesterol", "metric_id": "ldl-cholesterol", "url": "/metrics/ldl-cholesterol",'
        ' "value": 5.5, "unit": "mmol/L", "date": "2025-02-13",'
        ' "band": "Above the European laboratory flagging cut-point", "source_id": "s",'
        ' "source_name": "Source", "source_url": "https://example.test/source"}]'
    )
    now = utc_now()
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnosis_suspicions(
                   id, owner_user_id, rule_id, code, state, evidence_json,
                   first_seen_at, last_seen_at, state_changed_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (suspicion_id, world.alpha, rule_id, code, evidence, now, now, now),
        )
        connection.commit()
    return suspicion_id


def suspicion_state(world: World, suspicion_id: str) -> str:
    return rows(world, "SELECT state FROM diagnosis_suspicions WHERE id = ?", (suspicion_id,))[0]["state"]


def add_candidate(world: World, code: str, name: str) -> None:
    """A diagnosis the reader found in the owner's consultation, not yet offered or decided."""
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnosis_candidates(
                   id, owner_user_id, document_id, method, code, code_printed, name, name_key,
                   certainty, timing, event_date, date_exact, quote, state, created_at)
               VALUES (?, ?, ?, 'code', ?, 1, ?, ?, 'confirmed', 'now', '2025-01-15', 1, ?, 'new', ?)""",
            (f"cand-{code}", world.alpha, world.document, code, name, name.casefold(),
             f"{code} {name}", utc_now()),
        )
        connection.commit()


def candidate_state(world: World, code: str) -> str:
    return rows(world, "SELECT state FROM diagnosis_candidates WHERE code = ?", (code,))[0]["state"]


def add_factor(world: World, *, name: str = "Valsartan 80 mg", atc: str = "C09CA03") -> str:
    """A medicine on the owner's Medicines page, as the page saves it."""
    factor_id = str(uuid.uuid4())
    now = utc_now()
    with connect(world.settings) as connection:
        connection.execute(
            "INSERT INTO factors(id, owner_user_id, patient_id, kind, name, atc_code, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (factor_id, world.alpha, world.patient, "medicine", name, atc, "current", now, now),
        )
        connection.commit()
    return factor_id


def add_text_candidate(world: World, name: str, certainty: str = "confirmed") -> None:
    """A statement of a conclusion the reader took word for word; the document prints no ICD-10 code."""
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnosis_candidates(
                   id, owner_user_id, document_id, method, code, code_printed, name, name_key,
                   certainty, timing, event_date, date_exact, quote, state, created_at)
               VALUES (?, ?, ?, 'text', '', 0, ?, ?, ?, 'now', '2025-01-15', 1, ?, 'new', ?)""",
            (str(uuid.uuid4()), world.alpha, world.document, name, name.casefold(), certainty, name, utc_now()),
        )
        connection.commit()


def found_row(page: str, name: str) -> str:
    """The one row of the found list that names the diagnosis, cut at its closing tag."""
    part = next(piece for piece in page.split('class="dx-found"')[1:] if name in piece)
    return part[: part.index("</li>")]


def heading_text(page: str) -> str:
    """The text of the page's first heading, tags removed."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.DOTALL)
    assert match is not None
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())


def page_title(page: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_the_record_is_listed_in_both_locales(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert post_new(world, alpha, code="E78.2", certainty="confirmed",
                    document_id=world.document).status_code == 303
    assert post_new(world, alpha, code="K11.2", certainty="provisional", diagnosed_on="2025-01-15",
                    notes="Working diagnosis").status_code == 303
    assert post_new(world, alpha, code="J06.9", diagnosed_on="2019-05-01").status_code == 303
    add_suspicion(world)
    add_candidate(world, "I10", "Essential hypertension")
    past_id = diagnosis_id_for(world, "J06.9")
    resolved = alpha.post(f"/diagnoses/{past_id}/status", data={"status": "resolved",
                                                                "csrf_token": csrf(world, alpha)},
                          follow_redirects=False)
    assert resolved.status_code == 303

    english = alpha.get("/diagnoses")
    assert english.status_code == 200
    assert "Mixed hyperlipidaemia" in english.text
    assert "Sialoadenitis" in english.text
    assert f"/documents/{world.document}" in english.text
    assert "/diagnoses/possible/susp-lipid_mixed" in english.text
    assert "Essential hypertension" in english.text

    alpha.cookies.set("anamna_lang", "uk")
    ukrainian = alpha.get("/diagnoses")
    assert ukrainian.status_code == 200
    assert "Змішана гіперліпідемія" in ukrainian.text
    assert "/diagnoses/possible/susp-lipid_mixed" in ukrainian.text


def test_a_possible_diagnosis_can_be_muted_and_restored(world, clients):
    alpha = clients("alpha@example.test")
    suspicion_id = add_suspicion(world)
    page = alpha.get("/diagnoses").text
    assert f"/diagnoses/possible/{suspicion_id}" in page

    muted = alpha.post(f"/diagnoses/possible/{suspicion_id}",
                       data={"action": "mute", "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert muted.status_code == 303
    assert muted.headers["location"] == "/diagnoses?saved=muted"
    assert suspicion_state(world, suspicion_id) == "muted"

    restored = alpha.post(f"/diagnoses/possible/{suspicion_id}",
                          data={"action": "restore", "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert restored.status_code == 303
    assert suspicion_state(world, suspicion_id) == "open"

    checked = alpha.post("/diagnoses/possible/check", data={"csrf_token": csrf(world, alpha)},
                         follow_redirects=False)
    assert checked.headers["location"] == "/diagnoses?saved=checked"
    assert alpha.post(f"/diagnoses/possible/{suspicion_id}", data={"action": "explode",
                                                                   "csrf_token": csrf(world, alpha)}).status_code == 400
    unknown = alpha.post("/diagnoses/possible/nothing-here", data={"action": "mute",
                                                                  "csrf_token": csrf(world, alpha)})
    assert unknown.status_code == 404


def test_a_possible_diagnosis_is_confirmed_into_the_record(world, clients):
    alpha = clients("alpha@example.test")
    suspicion_id = add_suspicion(world)

    form = alpha.get(f"/diagnoses/new?suspicion={suspicion_id}")
    assert form.status_code == 200
    assert 'value="E78.2"' in form.text
    assert suspicion_id in form.text

    response = post_new(world, alpha, suspicion_id=suspicion_id)
    assert response.status_code == 303
    assert response.headers["location"] == "/diagnoses?saved=added"
    assert suspicion_state(world, suspicion_id) == "confirmed"
    created = rows(world, "SELECT id, origin FROM diagnoses WHERE owner_user_id = ? AND code = 'E78.2'", (world.alpha,))
    assert [row["origin"] for row in created] == ["suspicion"]
    linked = rows(world, "SELECT diagnosis_id FROM diagnosis_suspicions WHERE id = ?", (suspicion_id,))
    assert linked[0]["diagnosis_id"] == created[0]["id"]


def test_an_invalid_code_is_refused_with_its_message(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    response = post_new(world, alpha, code="ZZ99")
    assert response.status_code == 400
    assert escape(MESSAGES["dx.error.code_unknown"]["en"]) in response.text
    assert rows(world, "SELECT id FROM diagnoses WHERE owner_user_id = ?", (world.alpha,)) == []


def test_a_diagnosis_is_created_edited_resolved_and_deleted(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert post_new(world, alpha, code="E78.2").headers["location"] == "/diagnoses?saved=added"
    diagnosis_id = diagnosis_id_for(world, "E78.2")

    detail = alpha.get(f"/diagnoses/{diagnosis_id}")
    assert detail.status_code == 200
    assert "Mixed hyperlipidaemia" in detail.text
    assert alpha.get(f"/diagnoses/{diagnosis_id}/edit").status_code == 200

    edited = alpha.post(f"/diagnoses/{diagnosis_id}/edit",
                        data={**diagnosis_fields(name="Mixed lipid disorder", code="E78.2"),
                              "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert edited.headers["location"] == f"/diagnoses/{diagnosis_id}?saved=saved"
    assert rows(world, "SELECT name FROM diagnoses WHERE id = ?", (diagnosis_id,))[0]["name"] == "Mixed lipid disorder"

    status = alpha.post(f"/diagnoses/{diagnosis_id}/status",
                        data={"status": "resolved", "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert status.headers["location"] == "/diagnoses?saved=status_changed"
    row = rows(world, "SELECT status, resolved_on FROM diagnoses WHERE id = ?", (diagnosis_id,))[0]
    assert row["status"] == "resolved"
    assert row["resolved_on"] == date.today().isoformat()

    deleted = alpha.post(f"/diagnoses/{diagnosis_id}/delete", data={"csrf_token": csrf(world, alpha)},
                         follow_redirects=False)
    assert deleted.headers["location"] == "/diagnoses?saved=deleted"
    assert rows(world, "SELECT id FROM diagnoses WHERE id = ?", (diagnosis_id,)) == []


def test_found_diagnoses_are_accepted_and_dismissed(world, clients):
    alpha = clients("alpha@example.test")
    add_candidate(world, "K11.2", "Sialoadenitis")
    add_candidate(world, "J06.9", "Acute upper respiratory infection")
    assert 'value="K11.2"' in alpha.get("/diagnoses").text

    none = alpha.post("/diagnoses/found", data={"action": "accept", "csrf_token": csrf(world, alpha)},
                      follow_redirects=False)
    assert none.headers["location"] == "/diagnoses?error=found_none"

    accepted = alpha.post("/diagnoses/found", data={"action": "accept", "key": ["K11.2"],
                                                    "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert accepted.headers["location"] == "/diagnoses?saved=found_added"
    assert candidate_state(world, "K11.2") == "accepted"
    origin = rows(world, "SELECT origin FROM diagnoses WHERE owner_user_id = ? AND code = 'K11.2'", (world.alpha,))
    assert [row["origin"] for row in origin] == ["document"]

    dismissed = alpha.post("/diagnoses/found", data={"action": "dismiss", "key": ["J06.9"],
                                                     "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert dismissed.headers["location"] == "/diagnoses?saved=found_dismissed"
    assert candidate_state(world, "J06.9") == "dismissed"


def test_the_codes_search_answers_json(world, clients):
    alpha = clients("alpha@example.test")
    answer = alpha.get("/diagnoses/codes?q=e78")
    assert answer.status_code == 200
    codes = [item["code"] for item in answer.json()]
    assert "E78.2" in codes
    assert all(code.startswith("E78") for code in codes)


def test_a_post_without_the_csrf_token_is_refused(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "E78.2")
    refused = alpha.post("/diagnoses/new", data=diagnosis_fields(csrf_token="x"), follow_redirects=False)
    assert refused.status_code == 403
    status = alpha.post(f"/diagnoses/{diagnosis_id}/status", data={"status": "resolved", "csrf_token": "x"})
    assert status.status_code == 403


def test_another_account_cannot_read_or_change_the_record(world, clients):
    alpha = clients("alpha@example.test")
    bravo = clients("bravo@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "E78.2")

    assert bravo.get(f"/diagnoses/{diagnosis_id}").status_code == 404
    assert bravo.post(f"/diagnoses/{diagnosis_id}/status", data={"status": "resolved",
                                                                 "csrf_token": csrf(world, bravo)}).status_code == 404
    assert bravo.post(f"/diagnoses/{diagnosis_id}/delete",
                      data={"csrf_token": csrf(world, bravo)}).status_code == 404
    assert rows(world, "SELECT status FROM diagnoses WHERE id = ?", (diagnosis_id,))[0]["status"] == "active"


def test_a_share_viewer_reads_the_record_and_cannot_write(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})

    page = bravo.get("/diagnoses")
    assert page.status_code == 200
    assert "Mixed hyperlipidaemia" in page.text
    assert bravo.post("/diagnoses/new", data={**diagnosis_fields(), "csrf_token": csrf(world, bravo)}).status_code == 403


def test_the_fixed_routes_are_not_taken_for_a_diagnosis_id(world, clients):
    alpha = clients("alpha@example.test")
    form = alpha.get("/diagnoses/new")
    assert form.status_code == 200
    assert "/diagnoses/new" in form.text


def test_the_scan_is_refused_while_ai_is_off(world, clients, monkeypatch):
    alpha = clients("alpha@example.test")
    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: False)
    answer = alpha.post("/diagnoses/found/scan", data={"csrf_token": csrf(world, alpha)})
    assert answer.json() == {"error": "disabled"}


def test_an_unknown_notice_is_not_echoed(world, clients):
    alpha = clients("alpha@example.test")
    page = alpha.get("/diagnoses?saved=<script>x</script>&error=../../etc")
    assert page.status_code == 200
    assert "<script>x</script>" not in page.text


def test_a_watched_metric_with_a_card_becomes_a_chip_and_one_without_is_left_out():
    card = {
        "name": "LDL cholesterol", "id": "ldl-cholesterol", "url": "/metrics/ldl-cholesterol",
        "value_text": "5.5", "unit": "mmol/L", "date_text": "13 Feb 2025",
        "verdict": {"interpretation": "high", "label": "High"},
    }
    page = diagnoses_routes._Page(None, "owner", "en", None, {"LDL cholesterol": "ldl-cholesterol"},
                                  {"ldl-cholesterol": card})
    chips = diagnoses_routes._watch(page, "E78.2")
    assert chips == [{
        "name": "LDL cholesterol", "url": "/metrics/ldl-cholesterol", "value_text": "5.5", "unit": "mmol/L",
        "date_text": "13 Feb 2025", "state": verdict_state(card["verdict"]), "verdict_label": "High",
    }]
    assert diagnoses_routes._watch(page, "J06.9") == []


def add_obesity_suspicion(world: World) -> str:
    """An open possible obesity diagnosis whose evidence names a curated band in English."""
    suspicion_id = "susp-obesity"
    evidence = (
        '[{"metric": "Body mass index", "metric_id": "body-mass-index", "url": "/metrics/body-mass-index",'
        ' "value": "32.1", "unit": "kg/m2", "date": "2025-02-13", "band": "Obesity class I",'
        ' "source_id": "s", "source_name": "Source", "source_url": "https://example.test/source"}]'
    )
    now = utc_now()
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnosis_suspicions(
                   id, owner_user_id, rule_id, code, state, evidence_json,
                   first_seen_at, last_seen_at, state_changed_at)
               VALUES (?, ?, 'obesity', 'E66', 'open', ?, ?, ?, ?)""",
            (suspicion_id, world.alpha, evidence, now, now, now),
        )
        connection.commit()
    return suspicion_id


def test_a_possible_band_label_is_shown_in_ukrainian(world, clients):
    alpha = clients("alpha@example.test")
    add_obesity_suspicion(world)
    with connect(world.settings) as connection:
        expected = diagnosis_matrix.band_text(connection, "Body mass index", "Obesity class I", "uk")
    assert expected != "Obesity class I"
    alpha.cookies.set("anamna_lang", "uk")
    page = alpha.get("/diagnoses")
    assert page.status_code == 200
    assert str(escape(expected)) in page.text
    assert "Obesity class I" not in page.text


def test_a_guest_reads_the_diagnoses_page_and_cannot_write(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "E78.2")
    add_suspicion(world)
    add_candidate(world, "K11.2", "Sialoadenitis")

    with TestClient(create_app(world.settings)) as guest_app:
        expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
        _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
        assert guest_app.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        guest_app.cookies.set("anamna_lang", "en")

        page = guest_app.get("/diagnoses")
        assert page.status_code == 200
        assert "Mixed hyperlipidaemia" in page.text
        for action in (
            f"/diagnoses/{diagnosis_id}/status",
            f"/diagnoses/{diagnosis_id}/delete",
            f"/diagnoses/{diagnosis_id}/edit",
            "/diagnoses/possible/susp-lipid_mixed",
            "/diagnoses/possible/check",
            "/diagnoses/new",
        ):
            assert f'action="{action}"' not in page.text

        detail = guest_app.get(f"/diagnoses/{diagnosis_id}")
        assert detail.status_code == 200
        assert f'action="/diagnoses/{diagnosis_id}/status"' not in detail.text
        assert f'action="/diagnoses/{diagnosis_id}/delete"' not in detail.text


def test_a_guest_sees_no_found_or_scan_form(world, clients, monkeypatch):
    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: True)
    add_candidate(world, "K11.2", "Sialoadenitis")
    with TestClient(create_app(world.settings)) as guest_app:
        expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
        _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
        assert guest_app.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        guest_app.cookies.set("anamna_lang", "en")
        page = guest_app.get("/diagnoses")
        assert 'action="/diagnoses/found"' not in page.text
        assert 'action="/diagnoses/found/scan"' not in page.text


def test_a_share_viewer_sees_no_post_form_in_the_page(world, clients, monkeypatch):
    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: True)
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    add_candidate(world, "K11.2", "Sialoadenitis")
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})

    page = bravo.get("/diagnoses")
    assert page.status_code == 200
    main = page.text[page.text.index("<main"):page.text.index("</main>")]
    assert "Mixed hyperlipidaemia" in main
    assert "Sialoadenitis" in main
    assert 'method="post"' not in main
    assert 'href="/diagnoses/new"' not in main


def test_a_guest_is_sent_back_from_the_form_and_refused_every_write(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    add_candidate(world, "K11.2", "Sialoadenitis")

    with TestClient(create_app(world.settings)) as guest_app:
        expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
        _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
        assert guest_app.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        guest_app.cookies.set("anamna_lang", "en")

        form = guest_app.get("/diagnoses/new", follow_redirects=False)
        assert form.status_code in (302, 303)
        assert form.headers["location"] == "/diagnoses"

        assert guest_app.post("/diagnoses/new", data={**diagnosis_fields(code="K11.2"), "csrf_token": "x"}).status_code == 403
        assert guest_app.post("/diagnoses/found", data={"action": "accept", "key": "K11.2", "csrf_token": "x"}).status_code == 403
        assert guest_app.post("/diagnoses/possible/check", data={"csrf_token": "x"}).status_code == 403

        answer = guest_app.get("/diagnoses/codes?q=e78")
        assert answer.status_code == 200
        assert "E78.2" in [item["code"] for item in answer.json()]

    assert rows(world, "SELECT code FROM diagnoses WHERE owner_user_id = ?", (world.alpha,))[0]["code"] == "E78.2"
    assert len(rows(world, "SELECT id FROM diagnoses WHERE owner_user_id = ?", (world.alpha,))) == 1
    assert candidate_state(world, "K11.2") == "new"


def test_a_coded_diagnosis_is_titled_in_the_reader_language_and_keeps_the_written_words(world, clients):
    alpha = clients("alpha@example.test")
    written = "Гіпертонічна хвороба"
    assert post_new(world, alpha, code="I11.9", name=written).status_code == 303
    diagnosis_id = diagnosis_id_for(world, "I11.9", name=written)
    english_title = str(escape(icd10.name("I11.9", "en")))
    ukrainian_title = str(escape(icd10.name("I11.9", "uk")))

    alpha.cookies.set("anamna_lang", "en")
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert english_title in heading_text(detail)
    assert written not in heading_text(detail)
    assert written not in page_title(detail)
    assert "As written:" in detail
    assert written in detail[detail.index("As written:"):]
    assert english_title in alpha.get("/diagnoses").text

    alpha.cookies.set("anamna_lang", "uk")
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert ukrainian_title in heading_text(detail)
    assert "Як записано:" in detail
    assert written in detail[detail.index("Як записано:"):]


def test_a_medicine_for_the_diagnosis_is_shown_on_its_detail_page_and_its_card(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="I11.9").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "I11.9")
    factor_id = add_factor(world)

    alpha.cookies.set("anamna_lang", "en")
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert "Valsartan 80 mg" in detail
    assert "Agents acting on the renin-angiotensin system" in detail
    assert f"/medicines/{factor_id}" in detail
    assert "Valsartan 80 mg" in alpha.get("/diagnoses").text

    alpha.cookies.set("anamna_lang", "uk")
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert str(escape(MESSAGES["dx.atc.c09"]["uk"])) in detail
    assert f"/medicines/{factor_id}" in detail


def test_a_medicine_is_removed_from_a_diagnosis_and_linked_back(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert post_new(world, alpha, code="I11.9").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "I11.9")
    factor_id = add_factor(world)
    path = f"/diagnoses/{diagnosis_id}/medicines"

    removed = alpha.post(path, data={"factor_id": factor_id, "action": "remove", "csrf_token": csrf(world, alpha)},
                         follow_redirects=False)
    assert removed.status_code == 303
    assert "saved=medicine_unlinked" in removed.headers["location"]
    notice = alpha.get(removed.headers["location"]).text
    assert str(escape(MESSAGES["dx.notice.medicine_unlinked"]["en"])) in notice
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert f"/medicines/{factor_id}" not in detail
    assert f'<option value="{factor_id}">' in detail

    linked = alpha.post(path, data={"factor_id": factor_id, "action": "add", "csrf_token": csrf(world, alpha)},
                        follow_redirects=False)
    assert linked.status_code == 303
    assert "saved=medicine_linked" in linked.headers["location"]
    detail = alpha.get(f"/diagnoses/{diagnosis_id}").text
    assert f"/medicines/{factor_id}" in detail
    assert "You linked this medicine" in detail
    assert f'<option value="{factor_id}">' not in detail


def test_a_medicine_link_that_cannot_be_made_is_refused_and_writes_nothing(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert post_new(world, alpha, code="I11.9").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "I11.9")
    factor_id = add_factor(world)
    path = f"/diagnoses/{diagnosis_id}/medicines"

    missing = alpha.post(path, data={"factor_id": "no-such-medicine", "action": "add",
                                     "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert missing.status_code == 303
    assert "error=medicine" in missing.headers["location"]
    assert str(escape(MESSAGES["dx.error.medicine"]["en"])) in alpha.get(missing.headers["location"]).text
    unknown_action = alpha.post(path, data={"factor_id": factor_id, "action": "explode",
                                            "csrf_token": csrf(world, alpha)}, follow_redirects=False)
    assert "error=medicine" in unknown_action.headers["location"]
    assert rows(world, "SELECT factor_id FROM diagnosis_medicines") == []

    unknown = alpha.post("/diagnoses/nothing-here/medicines",
                         data={"factor_id": factor_id, "action": "add", "csrf_token": csrf(world, alpha)})
    assert unknown.status_code == 404
    refused = alpha.post(path, data={"factor_id": factor_id, "action": "add", "csrf_token": "x"},
                         follow_redirects=False)
    assert refused.status_code == 403
    assert rows(world, "SELECT factor_id FROM diagnosis_medicines") == []


def test_a_share_viewer_and_a_guest_see_the_treatment_but_cannot_change_it(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="I11.9").status_code == 303
    diagnosis_id = diagnosis_id_for(world, "I11.9")
    factor_id = add_factor(world)
    path = f"/diagnoses/{diagnosis_id}/medicines"
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})

    page = bravo.get(f"/diagnoses/{diagnosis_id}").text
    assert f"/medicines/{factor_id}" in page
    assert f'action="{path}"' not in page
    refused = bravo.post(path, data={"factor_id": factor_id, "action": "remove", "csrf_token": csrf(world, bravo)})
    assert refused.status_code == 403

    with TestClient(create_app(world.settings)) as guest_app:
        expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
        _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
        assert guest_app.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        guest_app.cookies.set("anamna_lang", "en")
        page = guest_app.get(f"/diagnoses/{diagnosis_id}").text
        assert f"/medicines/{factor_id}" in page
        assert f'action="{path}"' not in page
        refused = guest_app.post(path, data={"factor_id": factor_id, "action": "remove", "csrf_token": "x"})
        assert refused.status_code == 403

    assert rows(world, "SELECT factor_id FROM diagnosis_medicines") == []


def test_a_text_candidate_says_the_document_prints_no_code(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    add_text_candidate(world, "Плантарний фасциїт")
    page = alpha.get("/diagnoses").text
    assert "Плантарний фасциїт" in page
    assert str(escape(MESSAGES["dx.found.text_badge"]["en"])) in page
    assert str(escape(MESSAGES["dx.found.no_code"]["en"])) in page


def test_a_text_candidate_carries_a_certainty_pill_only_when_it_is_provisional(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    add_text_candidate(world, "Плантарний фасциїт", certainty="confirmed")
    add_text_candidate(world, "Тендиніт ахілового сухожилля", certainty="provisional")
    page = alpha.get("/diagnoses").text
    confirmed = found_row(page, "Плантарний фасциїт")
    provisional = found_row(page, "Тендиніт ахілового сухожилля")
    assert str(escape(MESSAGES["dx.certainty.confirmed"]["en"])) not in confirmed
    assert str(escape(MESSAGES["dx.certainty.provisional"]["en"])) in provisional


def test_a_coded_candidate_shows_the_english_catalogue_title_first(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    add_candidate(world, "I11.9", "Гіпертонічна хвороба")
    page = alpha.get("/diagnoses").text
    assert str(escape(icd10.name("I11.9", "en"))) in page
    assert str(escape(icd10.name("I11.9", "uk"))) not in page
    assert "Гіпертонічна хвороба" in page[page.index(str(escape(icd10.name("I11.9", "en")))):]


def test_the_sources_are_named_in_the_reader_language(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert str(escape("Ministry of Health of Ukraine / National Health Service of Ukraine")) in alpha.get("/diagnoses").text
    alpha.cookies.set("anamna_lang", "uk")
    assert str(escape("Всесвітня організація охорони здоров'я")) in alpha.get("/diagnoses").text


def test_current_diagnoses_are_grouped_by_icd_chapter_with_the_uncoded_ones_last(world, clients):
    alpha = clients("alpha@example.test")
    alpha.cookies.set("anamna_lang", "en")
    assert post_new(world, alpha, code="", name="Lipoma of the back", diagnosed_on="2025-02-01").status_code == 303
    assert post_new(world, alpha, code="E78.2", diagnosed_on="2026-08-09").status_code == 303
    assert post_new(world, alpha, code="I10", diagnosed_on="2024-01-10").status_code == 303

    page = alpha.get("/diagnoses").text
    titles = re.findall(r'<h3 class="dx-group__title"[^>]*>(.*?)<span', page, re.DOTALL)

    assert [" ".join(title.split()) for title in titles] == [
        "Endocrine, nutritional and metabolic diseases",
        "Diseases of the circulatory system",
        "Without an ICD-10 code",
    ]
    lipoma = page[page.index("Lipoma of the back") - 600: page.index("Lipoma of the back")]
    assert 'data-dx-day="2025-02-01"' in lipoma and "data-dx-item" in lipoma


def test_the_header_is_compact_and_the_filter_waits_for_the_script(world, clients):
    alpha = clients("alpha@example.test")
    assert post_new(world, alpha, code="E78.2").status_code == 303
    alpha.cookies.set("anamna_lang", "uk")

    page = alpha.get("/diagnoses").text

    assert 'class="dx-lead"' not in page
    head = page[page.index('<section class="dx-head"'): page.index("</section>", page.index('<section class="dx-head"'))]
    assert 'class="dx-tiles"' in head and "/diagnoses/new" in head
    assert re.search(r'<div class="dx-filter" role="search" data-dx-filter hidden', page)
    assert 'data-shown="Показано: {shown} з {total}"' in page
    assert '<label for="dx-filter-q">Знайти діагноз</label>' in page


def test_a_card_folds_its_results_treatment_and_actions(world, clients):
    alpha = clients("alpha@example.test")
    add_factor(world)
    assert post_new(world, alpha, code="I10").status_code == 303
    alpha.cookies.set("anamna_lang", "en")

    page = alpha.get("/diagnoses").text
    start = page.index('class="dx-card ')
    card = page[start: page.index("</details>", start)]

    assert '<details class="dx-more">' in card and "<details class=\"dx-more\" open" not in card
    summary = card[card.index("<summary>"): card.index("</summary>")]
    assert "Treatment" in summary and "Actions" in summary
    assert card.index("<summary>") < card.index("Valsartan 80 mg") < card.index("Mark as resolved")
