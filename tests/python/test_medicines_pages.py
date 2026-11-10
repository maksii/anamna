"""The Medicines pages: the list, the form, the entry page, the AI reference card
and the lookup, end to end through the routes.

The AI research and the medicine-name lookup are replaced at their seams, and
the network is refused, so nothing here leaves the machine.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import ai, drugref, factor_candidates, factor_jobs, factor_research, security
from anamna.db import connect, migrate, utc_now
from anamna.i18n import MESSAGES
from anamna.ingest.concepts import stable_concept_id
from anamna.ingest.pipeline import ensure_vendor, seed_concepts
from anamna.ingest.text import search_key
from anamna.security import create_access_token, create_user
from anamna.web import factors_view
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "anamna" / "web" / "templates"
LDL_ID = stable_concept_id("LDL cholesterol")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    security._attempts.clear()
    yield
    security._attempts.clear()


@pytest.fixture(autouse=True)
def fresh_jobs():
    factor_jobs.reset()
    drugref.reset_state()
    yield
    factor_jobs.reset()
    drugref.reset_state()


@dataclass
class World:
    settings: object
    alpha: str
    bravo: str
    document: str


@pytest.fixture
def world(tmp_path) -> World:
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    bravo = create_user(settings, "bravo@example.test", "Bravo", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_patient(settings, bravo, "Bravo Patient")
    document = seed_document(settings, alpha, patient, "Alpha lipid panel", "alpha-lipid.txt")
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               VALUES ('obs-ldl', ?, ?, ?, 1, ?, 'LDL', 'numeric', 4.2, 'mmol/L', '2025-02-13',
                       'extracted', 'test', 1.0, 'LDL 4.2', 'test', ?)""",
            (alpha, patient, document, LDL_ID, utc_now()),
        )
        connection.commit()
    return World(settings, alpha, bravo, document)


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


def entry_fields(**overrides) -> dict:
    data = {
        "kind": "medicine", "name": "Диокор", "strength": "80 мг", "dose": "1 таблетка",
        "schedule": "щоранку", "status": "current", "started_on": "2025-01-10", "ended_on": "",
        "reason": "Тиск", "prescriber": "Лікар", "notes": "Переношу добре",
        "substance": "валсартан", "atc_code": "C09CA03",
        "reference_name": "Диокор", "reference_code": "8311",
    }
    data.update(overrides)
    return data


def create_entry(world: World, owner: TestClient, **fields):
    token = csrf(world, owner)
    return owner.post("/medicines", data={**entry_fields(**fields), "csrf_token": token}, follow_redirects=False)


def factor_id_of(response) -> str:
    return re.search(r"/medicines/([^?#/]+)", response.headers["location"]).group(1)


def act(world: World, owner: TestClient, factor_id: str, **fields):
    token = csrf(world, owner)
    return owner.post(f"/medicines/{factor_id}", data={**fields, "csrf_token": token}, follow_redirects=False)


def row_of(world: World, factor_id: str):
    with connect(world.settings) as connection:
        return connection.execute("SELECT * FROM factors WHERE id = ?", (factor_id,)).fetchone()


def effects_of(world: World, factor_id: str) -> list:
    with connect(world.settings) as connection:
        return connection.execute(
            "SELECT * FROM factor_effects WHERE factor_id = ? ORDER BY created_at, id", (factor_id,)
        ).fetchall()


def assert_no_missing_keys(page: str) -> None:
    """A missing key renders as the key itself; any `med.` token that is not a catalogue key is one."""
    found = set(re.findall(r"\bmed\.[a-z_]+(?:\.[a-z_]+)*", page))
    missing = {key for key in found if key not in MESSAGES}
    assert not missing, missing


def suggestion(concept_id: str | None = None) -> dict:
    quote = "Дорослим призначають 80 мг один раз на добу."
    return {
        "created_at": utc_now(),
        "model": "test-model",
        "language": "uk",
        "source": {
            "name": "tabletki.ua",
            "url": "https://tabletki.ua/uk/Диокор/8311/",
            "shown_for": "Диокор 80 мг",
        },
        "atc_codes": ["C09CA03"],
        "fields": {
            "purpose": {"text": "Таблетки для зниження тиску.", "quote": quote},
            "usual_dose": {"text": "80 мг раз на добу.", "quote": quote},
            "interactions": {"text": "Калій-зберігаючі діуретики.", "quote": ""},
        },
        "effects": [
            {"concept_id": concept_id, "label": "LDL cholesterol", "direction": "lowers",
             "note": "Трохи.", "quote": ""},
        ],
        "regimen": {"dose_amount": 1, "dose_unit": "tablet", "repeat": "daily", "every": 1,
                    "per_day": 2, "quote": quote},
    }


def stub_research(monkeypatch, *, reply=None, error: str | None = None) -> list[dict]:
    """Replaces the AI research; returns the list each call's draft is appended to."""
    seen: list[dict] = []

    def research(settings, connection, factor, *, locale):
        seen.append(factor)
        if error:
            raise ai.AIUnavailable(error)
        return reply if reply is not None else suggestion(LDL_ID)

    monkeypatch.setattr(factor_research, "research", research)
    return seen


def ai_on(monkeypatch, on: bool) -> None:
    monkeypatch.setattr(ai, "ai_active", lambda settings, task=None: on)


def wait_for(owner: TestClient, job: str) -> dict:
    factor_jobs.join(job)
    return owner.get(f"/medicines/suggest/{job}").json()


def count_entries(world: World) -> int:
    with connect(world.settings) as connection:
        return connection.execute("SELECT COUNT(*) FROM factors WHERE owner_user_id = ?", (world.alpha,)).fetchone()[0]


def test_empty_page_renders_in_both_locales_with_the_add_link(world, clients):
    owner = clients("alpha@example.test")
    english = owner.get("/medicines")
    assert english.status_code == 200
    assert "/medicines/new" in english.text
    assert "Add an entry" in english.text
    assert_no_missing_keys(english.text)

    owner.cookies.set("anamna_lang", "uk")
    ukrainian = owner.get("/medicines")
    assert ukrainian.status_code == 200
    assert "Ліки" in ukrainian.text
    assert "Додати запис" in ukrainian.text
    assert_no_missing_keys(ukrainian.text)


def test_create_with_every_field_lists_it_under_now_with_period_and_bar(world, clients):
    owner = clients("alpha@example.test")
    response = create_entry(world, owner, purpose="Знижує тиск", usual_dose="80 мг",
                            interactions="Калій", monitoring="Калій у крові", cautions="Вагітність",
                            notes="Переношу добре", reason="Тиск")
    assert response.status_code == 303
    assert response.headers["location"].endswith("?saved=created")
    factor_id = factor_id_of(response)

    row = row_of(world, factor_id)
    assert (row["name"], row["strength"], row["dose"], row["schedule"]) == ("Диокор", "80 мг", "1 таблетка", "щоранку")
    assert row["atc_code"] == "C09CA03" and row["reference_url"] == "https://tabletki.ua/uk/Диокор/8311/"
    assert row["started_on"] == "2025-01-10" and row["status"] == "current"

    listing = owner.get("/medicines")
    assert listing.status_code == 200
    assert 'id="med-group-current"' in listing.text
    assert "Диокор" in listing.text
    assert "since 10 Jan 2025" in listing.text
    assert 'class="an-med-track"' in listing.text
    assert_no_missing_keys(listing.text)


def test_a_validation_error_answers_400_with_the_form_and_its_message(world, clients):
    owner = clients("alpha@example.test")
    response = create_entry(world, owner, name="")
    assert response.status_code == 400
    assert "Give it a name." in response.text
    assert "location" not in response.headers

    reversed_dates = create_entry(world, owner, started_on="2025-05-01", ended_on="2025-01-01")
    assert reversed_dates.status_code == 400
    assert "The end date is before the start date." in reversed_dates.text


def test_new_form_offers_the_dose_and_schedule_pickers(world, clients):
    owner = clients("alpha@example.test")
    page = owner.get("/medicines/new").text
    for name in ("dose_amount", "dose_unit", "repeat", "weekday", "day_part", "per_day", "meal"):
        assert f'name="{name}"' in page, name
    assert_no_missing_keys(page)


def test_create_stores_the_dose_and_schedule_and_the_entry_shows_them(world, clients):
    owner = clients("alpha@example.test")
    response = create_entry(
        world, owner, dose_amount="1", dose_unit="tablet", repeat="daily", per_day="2",
        day_part=["morning", "evening"], meal="after",
    )
    assert response.status_code == 303
    factor_id = factor_id_of(response)
    assert response.headers["location"] == f"/medicines/{factor_id}?saved=created"

    row = row_of(world, factor_id)
    assert row["dose_amount"] == 1 and row["dose_unit"] == "tablet"
    assert json.loads(row["schedule_json"]) == {
        "repeat": "daily", "every": 1, "weekdays": [], "per_day": 2,
        "times": ["morning", "evening"], "clock": [], "meal": "after",
    }
    page = owner.get(f"/medicines/{factor_id}").text
    assert "1 tablet" in page
    assert "2 times a day" in page


def test_a_refused_create_keeps_what_was_typed_and_saves_nothing(world, clients):
    owner = clients("alpha@example.test")
    before = count_entries(world)
    response = create_entry(world, owner, name="", reason="Тиск для проби", dose_amount="2", dose_unit="capsule")
    assert response.status_code == 400
    assert "Give it a name." in response.text
    assert "Тиск для проби" in response.text
    assert 'value="capsule" selected' in response.text
    assert count_entries(world) == before


def test_warfarin_entry_shows_the_inr_note(world, clients):
    owner = clients("alpha@example.test")
    response = create_entry(world, owner, name="Варфарин", atc_code="B01AA03", reference_name="", reference_code="")
    page = owner.get(f"/medicines/{factor_id_of(response)}")
    assert page.status_code == 200
    assert "vitamin K antagonist" in page.text
    assert "INR" in page.text


def test_detail_shows_effects_linked_to_the_chart_and_the_reference_link(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    act(world, owner, factor_id, action="effect_add", label="LDL cholesterol", direction="raises", note="")
    page = owner.get(f"/medicines/{factor_id}")
    assert page.status_code == 200
    assert f'href="/metrics/{LDL_ID}"' in page.text
    info = re.search(r'<a\s[^>]*data-med-info[^>]*>(.*?)</a>', page.text, re.S)
    assert info is not None
    assert f'href="/medicines/{factor_id}/instruction"' in info.group(0)
    assert info.group(1).strip() == "Instruction for use"
    assert "https://tabletki.ua/uk/Диокор/8311/" in page.text
    assert_no_missing_keys(page.text)


INSTRUCTION = {
    "url": "https://tabletki.ua/uk/Диокор/8311/",
    "sections": [["Склад", "валсартан, гідрохлоротіазид"],
                 ["Спосіб застосування", "Дорослим призначають 80 мг один раз на добу."]],
    "atc": ["C09DA03"],
    "shown_for": "Диокор 80 мг",
    "fetched_at": "2026-11-01T10:00:00+00:00",
    "details": {
        "via": "api",
        "facts": [["substance", ["валсартан", "гідрохлоротіазид"]], ["form", ["таблетки"]]],
        "warnings": [["Вагітні", "forbidden", "заборонено"], ["Діабетики", "caution", "Під наглядом лікаря"]],
    },
}


def use_instruction(monkeypatch, reference: dict | None = INSTRUCTION) -> None:
    """The reference lookup answers with ``reference``; nothing reaches the site."""
    monkeypatch.setattr(drugref, "cached_instruction", lambda connection, name, code="", **_kw: reference)


def join_reference_jobs() -> None:
    for job_id in list(factor_jobs._JOBS):
        factor_jobs.join(job_id)


def test_the_instruction_page_shows_the_stored_instruction_and_its_facts(world, clients, monkeypatch):
    use_instruction(monkeypatch)
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    page = owner.get(f"/medicines/{factor_id}/instruction")
    assert page.status_code == 200
    assert 'id="med-instruction"' in page.text
    assert "Instruction for medical use" in page.text
    assert "Спосіб застосування" in page.text
    assert "Active substance" in page.text and "валсартан" in page.text
    assert "Вагітні" in page.text and "not allowed" in page.text
    assert "Під наглядом лікаря" in page.text
    assert_no_missing_keys(page.text)


def test_the_instruction_page_renders_the_sections_when_there_are_no_product_facts(world, clients, monkeypatch):
    use_instruction(monkeypatch, {**INSTRUCTION, "details": {}})
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    page = owner.get(f"/medicines/{factor_id}/instruction")
    assert page.status_code == 200
    assert 'id="med-instruction"' in page.text and "Спосіб застосування" in page.text
    assert "Active substance" not in page.text


def test_a_remark_that_opens_with_the_state_shows_only_what_it_adds(world, clients, monkeypatch):
    warnings = [["Водії", "caution", "з обережністю, можливо запаморочення і слабкість"],
                ["Діти", "caution", "з 6-ти років"], ["Вагітні", "forbidden", "заборонено"]]
    use_instruction(monkeypatch, {**INSTRUCTION, "details": {"warnings": warnings}})
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    page = owner.get(f"/medicines/{factor_id}/instruction")
    assert page.status_code == 200
    assert ('<strong>Водії</strong>: with caution <span class="muted">(можливо запаморочення і слабкість)</span>'
            in page.text)
    assert "з обережністю, можливо" not in page.text
    assert '<strong>Діти</strong>: with caution <span class="muted">(з 6-ти років)</span>' in page.text
    assert "<strong>Вагітні</strong>: not allowed</span>" in page.text


def test_the_instruction_page_is_404_without_a_reference_or_for_another_person(world, clients, monkeypatch):
    use_instruction(monkeypatch)
    alpha = clients("alpha@example.test")
    without = factor_id_of(create_entry(world, alpha, reference_name="", reference_code=""))
    assert alpha.get(f"/medicines/{without}/instruction").status_code == 404

    linked = factor_id_of(create_entry(world, alpha))
    bravo = clients("bravo@example.test")
    assert bravo.get(f"/medicines/{linked}/instruction").status_code == 404


def test_with_the_lookup_switched_off_the_page_reads_the_stored_copy_only(world, clients, monkeypatch):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    join_reference_jobs()  # the save's own lookup ends before the fake below is set
    with connect(world.settings) as connection:
        connection.execute(
            "INSERT INTO drug_references(source, url, shown_for, atc_codes, sections_json, fetched_at, details_json) "
            "VALUES ('tabletki', ?, 'Диокор 80 мг', 'C09DA03', ?, ?, '')",
            (INSTRUCTION["url"], json.dumps(INSTRUCTION["sections"], ensure_ascii=False), utc_now()),
        )
        drugref.set_enabled(connection, False)
        connection.commit()

    def must_not_look_up(*_args, **_kwargs):
        raise AssertionError("the lookup ran while it is switched off")

    monkeypatch.setattr(drugref, "cached_instruction", must_not_look_up)
    page = owner.get(f"/medicines/{factor_id}/instruction")
    assert page.status_code == 200
    assert "Спосіб застосування" in page.text


def test_a_share_viewer_reads_the_instruction_of_the_owners_entry(world, clients, monkeypatch):
    use_instruction(monkeypatch)
    alpha = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, alpha))
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})
    page = bravo.get(f"/medicines/{factor_id}/instruction")
    assert page.status_code == 200 and 'id="med-instruction"' in page.text


def test_saving_a_linked_entry_stores_its_instruction_and_fills_what_it_lacks(world, clients, monkeypatch):
    def cache(connection, name, code="", **_kw):
        connection.execute(
            "INSERT OR REPLACE INTO drug_references(source, url, shown_for, atc_codes, sections_json, fetched_at, details_json) "
            "VALUES ('tabletki', ?, ?, 'C09DA03', ?, ?, ?)",
            (INSTRUCTION["url"], INSTRUCTION["shown_for"], json.dumps(INSTRUCTION["sections"], ensure_ascii=False),
             utc_now(), json.dumps(INSTRUCTION["details"], ensure_ascii=False)),
        )
        return INSTRUCTION

    monkeypatch.setattr(drugref, "cached_instruction", cache)
    owner = clients("alpha@example.test")
    empty = factor_id_of(create_entry(world, owner, substance="", atc_code=""))
    kept = factor_id_of(create_entry(world, owner, name="Диокор Плюс", substance="my words", atc_code="C09CA03"))
    assert "reference" in [job["kind"] for job in factor_jobs._JOBS.values()]
    join_reference_jobs()

    assert row_of(world, empty)["substance"] == "валсартан, гідрохлоротіазид"
    assert row_of(world, empty)["atc_code"] == "C09DA03"
    assert row_of(world, kept)["substance"] == "my words" and row_of(world, kept)["atc_code"] == "C09CA03"
    with connect(world.settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM drug_references").fetchone()[0] == 1


def test_edit_and_save_changes_the_entry(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    edit = owner.get(f"/medicines/{factor_id}/edit")
    assert edit.status_code == 200
    assert f'action="/medicines/{factor_id}"' in edit.text

    saved = act(world, owner, factor_id, action="save", kind="medicine", name="Диокор Плюс", status="current",
                started_on="2025-01-10")
    assert saved.status_code == 303
    assert saved.headers["location"] == f"/medicines/{factor_id}?saved=saved"
    assert row_of(world, factor_id)["name"] == "Диокор Плюс"
    assert "Диокор Плюс" in owner.get(f"/medicines/{factor_id}").text


def test_stop_marks_the_entry_finished_today(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    stopped = act(world, owner, factor_id, action="stop")
    assert stopped.headers["location"] == f"/medicines/{factor_id}?saved=stopped"
    row = row_of(world, factor_id)
    assert row["status"] == "past" and row["ended_on"] == date.today().isoformat()
    listing = owner.get("/medicines")
    assert 'id="med-group-past"' in listing.text
    assert 'id="med-group-current"' not in listing.text


def test_remove_deletes_the_entry_and_the_form_asks_first(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    edit = owner.get(f"/medicines/{factor_id}/edit")
    assert 'data-confirm="' in edit.text

    removed = act(world, owner, factor_id, action="remove")
    assert removed.headers["location"] == "/medicines?saved=removed"
    assert owner.get(f"/medicines/{factor_id}").status_code == 404
    assert row_of(world, factor_id) is None


def test_effect_by_a_concept_name_links_to_its_chart_and_free_text_does_not(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))

    added = act(world, owner, factor_id, action="effect_add", label="LDL cholesterol", direction="raises", note="Так")
    assert added.headers["location"] == f"/medicines/{factor_id}?saved=effect_added"
    free = act(world, owner, factor_id, action="effect_add", label="Тривожність", direction="changes", note="")
    assert free.headers["location"] == f"/medicines/{factor_id}?saved=effect_added"

    by_label = {effect["label"]: effect["concept_id"] for effect in effects_of(world, factor_id)}
    assert by_label == {"LDL cholesterol": LDL_ID, "Тривожність": None}

    page = owner.get(f"/medicines/{factor_id}").text
    assert page.count('href="/metrics/') == 1
    assert f'href="/metrics/{LDL_ID}"' in page


def test_effect_remove_takes_the_effect_off(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    act(world, owner, factor_id, action="effect_add", label="Тривожність", direction="changes", note="")
    effect_id = effects_of(world, factor_id)[0]["id"]

    removed = act(world, owner, factor_id, action="effect_remove", effect_id=effect_id)
    assert removed.headers["location"] == f"/medicines/{factor_id}?saved=effect_removed"
    assert effects_of(world, factor_id) == []


def test_create_marks_accepted_ai_text_and_effects_as_ai(world, clients):
    owner = clients("alpha@example.test")
    effects = [
        json.dumps({"concept_id": LDL_ID, "label": "LDL cholesterol", "direction": "lowers",
                    "note": "Трохи.", "quote": "80 мг"}, ensure_ascii=False),
        json.dumps({"concept_id": None, "label": "Тривожність", "direction": "changes",
                    "note": "", "quote": ""}, ensure_ascii=False),
    ]
    response = create_entry(world, owner, purpose="Знижує тиск", ai_fields="purpose", ai_effect=effects)
    factor_id = factor_id_of(response)
    assert row_of(world, factor_id)["ai_fields"] == "purpose"
    assert {effect["label"]: effect["origin"] for effect in effects_of(world, factor_id)} == {
        "LDL cholesterol": "ai", "Тривожність": "ai",
    }
    page = owner.get(f"/medicines/{factor_id}").text
    assert re.search(r"What it is and what it is for <span class=\"an-ai-tag\"", page)


def test_suggest_says_disabled_when_ai_is_off(world, clients, monkeypatch):
    ai_on(monkeypatch, False)
    owner = clients("alpha@example.test")
    response = owner.post("/medicines/suggest", data={**entry_fields(), "csrf_token": csrf(world, owner)})
    assert response.json() == {"error": "disabled"}


def test_suggest_runs_as_a_job_and_returns_the_suggestion(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    seen = stub_research(monkeypatch)
    owner = clients("alpha@example.test")
    response = owner.post("/medicines/suggest", data={**entry_fields(), "csrf_token": csrf(world, owner)})
    assert response.status_code == 200
    result = wait_for(owner, response.json()["job"])

    assert result["state"] == "done"
    view = result["suggestion"]
    assert set(view["fields"]) == {"purpose", "usual_dose", "interactions"}
    assert view["fields"]["purpose"]["text"] == "Таблетки для зниження тиску."
    assert view["effects"][0]["direction_label"] == "lowers"
    assert view["atc_code"] == "C09CA03"
    assert view["source"]["url"] == "https://tabletki.ua/uk/Диокор/8311/"
    assert view["regimen"]["text"].startswith("1 tablet")
    assert seen[0]["name"] == "Диокор" and seen[0]["id"] == ""


def test_suggest_leaves_out_an_effect_the_entry_already_has(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    stub_research(monkeypatch)
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    act(world, owner, factor_id, action="effect_add", label="LDL cholesterol", direction="raises", note="")

    response = owner.post("/medicines/suggest", data={
        **entry_fields(), "factor_id": factor_id, "csrf_token": csrf(world, owner),
    })
    result = wait_for(owner, response.json()["job"])
    assert result["state"] == "done"
    assert result["suggestion"]["effects"] == []


def test_a_failed_research_ends_failed_with_the_reason(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    stub_research(monkeypatch, error="budget")
    owner = clients("alpha@example.test")
    response = owner.post("/medicines/suggest", data={**entry_fields(), "csrf_token": csrf(world, owner)})
    assert wait_for(owner, response.json()["job"]) == {"state": "failed", "error": "budget"}


def test_an_unknown_job_or_another_users_job_reads_as_lost(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    stub_research(monkeypatch)
    alpha = clients("alpha@example.test")
    assert alpha.get("/medicines/suggest/unknown").json() == {"state": "failed", "error": "lost"}

    response = alpha.post("/medicines/suggest", data={**entry_fields(), "csrf_token": csrf(world, alpha)})
    job = response.json()["job"]
    factor_jobs.join(job)
    assert alpha.get(f"/medicines/suggest/{job}").json()["state"] == "done"

    bravo = clients("bravo@example.test")
    assert bravo.get(f"/medicines/suggest/{job}").json() == {"state": "failed", "error": "lost"}


def test_suggest_for_another_name_gets_its_own_job(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    release = threading.Event()

    def research(settings, connection, factor, *, locale):
        release.wait(5)
        answer = suggestion(LDL_ID)
        answer["fields"]["purpose"]["text"] = f"For {factor['name']}."
        return answer

    monkeypatch.setattr(factor_research, "research", research)
    owner = clients("alpha@example.test")
    token = csrf(world, owner)

    def ask(name: str) -> str:
        response = owner.post("/medicines/suggest", data={**entry_fields(name=name), "csrf_token": token})
        return response.json()["job"]

    try:
        alpha_job = ask("Alpha")
        beta_job = ask("Beta")
        assert beta_job != alpha_job
        assert ask("Alpha") == alpha_job
    finally:
        release.set()
    alpha_result = wait_for(owner, alpha_job)
    beta_result = wait_for(owner, beta_job)
    assert alpha_result["state"] == beta_result["state"] == "done"
    assert alpha_result["suggestion"]["fields"]["purpose"]["text"] == "For Alpha."
    assert beta_result["suggestion"]["fields"]["purpose"]["text"] == "For Beta."


def test_suggest_status_refuses_a_job_of_another_kind(world, clients):
    owner = clients("alpha@example.test")
    job = factor_jobs.start(world.alpha, lambda: {"read": 0, "found": 0}, kind="scan")
    factor_jobs.join(job)
    assert owner.get(f"/medicines/suggest/{job}").json() == {"state": "failed", "error": "lost"}


def test_suggest_needs_the_csrf_token_and_refuses_a_guest(world, clients, monkeypatch):
    ai_on(monkeypatch, True)
    stub_research(monkeypatch)
    owner = clients("alpha@example.test")
    assert owner.post("/medicines/suggest", data=entry_fields()).status_code == 403

    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
    with TestClient(create_app(world.settings)) as guest:
        assert guest.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        assert guest.post("/medicines/suggest", data={**entry_fields(), "csrf_token": "x"}).status_code == 403


def test_edit_with_suggest_one_autostarts_only_when_ai_is_on(world, clients, monkeypatch):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    ai_on(monkeypatch, True)
    assert "data-autostart" in owner.get(f"/medicines/{factor_id}/edit?suggest=1").text
    ai_on(monkeypatch, False)
    assert "data-autostart" not in owner.get(f"/medicines/{factor_id}/edit?suggest=1").text


def test_the_research_and_apply_actions_are_gone(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    assert act(world, owner, factor_id, action="research").status_code == 400
    assert act(world, owner, factor_id, action="apply", what="all").status_code == 400
    assert row_of(world, factor_id)["name"] == "Диокор"


def test_lookup_returns_items_and_says_when_it_is_off_or_unreachable(world, clients, monkeypatch):
    items = [{"kind": "trade_name", "code": "8311", "name": "Диокор", "reference_name": "Диокор", "maker": ""}]
    monkeypatch.setattr(drugref, "suggest", lambda text: [dict(item) for item in items])
    owner = clients("alpha@example.test")
    assert owner.get("/medicines/lookup", params={"q": "дио"}).json() == {"items": [{**items[0], "strength": ""}]}

    with connect(world.settings) as connection:
        drugref.set_enabled(connection, False)
        connection.commit()
    assert owner.get("/medicines/lookup", params={"q": "дио"}).json() == {"items": [], "error": "off"}

    with connect(world.settings) as connection:
        drugref.set_enabled(connection, True)
        connection.commit()

    def unreachable(text):
        raise drugref.DrugRefError("connection refused")

    monkeypatch.setattr(drugref, "suggest", unreachable)
    assert owner.get("/medicines/lookup", params={"q": "дио"}).json() == {"items": [], "error": "unavailable"}


def test_lookup_localizes_the_strength_and_says_when_the_site_asks_for_a_pause(world, clients, monkeypatch):
    item = {"kind": "trade_name", "code": "8311", "name": "Диокор", "reference_name": "Диокор", "maker": "",
            "strength": "160 мг", "unit": "мг"}
    monkeypatch.setattr(drugref, "suggest", lambda text: [dict(item)])
    owner = clients("alpha@example.test")
    found = owner.get("/medicines/lookup", params={"q": "дио"}).json()["items"][0]
    assert found["strength"] == "160 mg" and found["unit"] == "мг"

    owner.cookies.set("anamna_lang", "uk")
    assert owner.get("/medicines/lookup", params={"q": "дио"}).json()["items"][0]["strength"] == "160 мг"

    def paused(text):
        raise drugref.DrugRefPaused(300)

    monkeypatch.setattr(drugref, "suggest", paused)
    assert owner.get("/medicines/lookup", params={"q": "дио"}).json() == {
        "items": [], "error": "paused", "minutes": 5,
    }


def test_a_second_user_cannot_open_edit_or_post_to_the_first_users_entry(world, clients):
    alpha = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, alpha))
    bravo = clients("bravo@example.test")

    assert bravo.get(f"/medicines/{factor_id}").status_code == 404
    assert bravo.get(f"/medicines/{factor_id}/edit").status_code == 404
    assert act(world, bravo, factor_id, action="stop").status_code == 404
    assert act(world, bravo, factor_id, action="remove").status_code == 404
    assert row_of(world, factor_id)["status"] == "current"


def test_a_share_viewer_reads_the_owners_list_read_only(world, clients):
    alpha = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, alpha))
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})

    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})

    listing = bravo.get("/medicines")
    assert listing.status_code == 200
    assert "Диокор" in listing.text
    assert 'href="/medicines/new"' not in listing.text
    assert "Add an entry" not in listing.text

    assert bravo.get("/medicines/new", follow_redirects=False).headers["location"] == "/medicines"
    assert bravo.post("/medicines", data={**entry_fields(), "csrf_token": csrf(world, bravo)}).status_code == 403
    assert act(world, bravo, factor_id, action="stop").status_code == 403
    assert row_of(world, factor_id)["status"] == "current"


def test_a_guest_reads_the_list_and_cannot_write_or_look_up(world, clients):
    alpha = clients("alpha@example.test")
    create_entry(world, alpha)
    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
    with TestClient(create_app(world.settings)) as guest:
        assert guest.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        listing = guest.get("/medicines")
        assert listing.status_code == 200
        assert "Диокор" in listing.text
        assert guest.post("/medicines", data=entry_fields()).status_code == 403
        assert guest.get("/medicines/lookup", params={"q": "дио"}).status_code == 403


def test_the_medicine_templates_carry_no_inline_event_handlers():
    pattern = re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE)
    for name in ("medicines.html", "medicine_form.html", "medicine_detail.html", "_factors.html"):
        assert not pattern.search((TEMPLATES / name).read_text(encoding="utf-8")), name


def test_every_page_renders_in_both_locales_without_a_missing_key(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner, atc_code="B01AA03", name="Варфарин"))
    act(world, owner, factor_id, action="effect_add", label="LDL cholesterol", direction="raises", note="")
    pages = ("/medicines", "/medicines/new", f"/medicines/{factor_id}", f"/medicines/{factor_id}/edit")
    for locale in ("uk", "en"):
        owner.cookies.set("anamna_lang", locale)
        for url in pages:
            response = owner.get(url)
            assert response.status_code == 200, (locale, url)
            assert_no_missing_keys(response.text)


def test_kind_filter_narrows_the_list_and_an_empty_filter_is_ignored(world, clients):
    owner = clients("alpha@example.test")
    create_entry(world, owner, name="Диокор")
    create_entry(world, owner, kind="illness", name="Застуда", atc_code="", reference_name="",
                 reference_code="", started_on="2025-03-01")
    narrowed = owner.get("/medicines", params={"kind": "illness"}).text
    assert "Застуда" in narrowed and "Диокор" not in narrowed
    unfiltered = owner.get("/medicines", params={"kind": "supplement"}).text
    assert "Диокор" in unfiltered and "Застуда" in unfiltered
    assert owner.get("/medicines", params={"kind": "nonsense"}).status_code == 200


def test_saving_an_invalid_edit_returns_to_the_edit_form(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    response = act(world, owner, factor_id, action="save", kind="medicine", name="", status="current")
    assert response.status_code == 400
    assert "Give it a name." in response.text
    assert row_of(world, factor_id)["name"] == "Диокор"


def test_a_save_with_the_end_before_the_start_changes_nothing(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    response = act(world, owner, factor_id, action="save", kind="medicine", name="Диокор Плюс",
                   status="current", started_on="2025-05-01", ended_on="2025-01-01")
    assert response.status_code == 400
    assert "The end date is before the start date." in response.text
    row = row_of(world, factor_id)
    assert row["name"] == "Диокор" and row["started_on"] == "2025-01-10"


def test_chart_periods_lists_the_entries_that_can_change_the_result(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    act(world, owner, factor_id, action="effect_add", label="LDL cholesterol", direction="raises", note="")
    other = factor_id_of(create_entry(world, owner, name="Аспірин", atc_code="", reference_name="",
                                      reference_code="", started_on="2024-06-01"))
    with connect(world.settings) as connection:
        periods = factors_view.chart_periods(connection, world.alpha, [LDL_ID], locale="en", today=date.today())
    assert [item["id"] for item in periods["related"]] == [factor_id]
    assert periods["related"][0]["title"] == "Диокор: since 10 Jan 2025, can raise this result"
    assert [item["id"] for item in periods["others"]] == [other]
    assert [item["id"] for item in periods["json"]] == [factor_id, other]


def test_duration_and_bar_are_computed_from_the_shared_scale():
    today = date(2026, 1, 1)
    long_row = {
        "started_on": "2023-10-15", "ended_on": None, "effective_status": "current", "is_point": False,
        "name": "Ліки", "dates_approximate": 0,
    }
    assert factors_view.duration_text(long_row, today, "en") == "2 years 2 months"
    assert factors_view.duration_text({**long_row, "started_on": "2026-02-01"}, today, "en") == ""

    axis = factors_view.scale([long_row], today, "en")
    assert axis["start"] == "2023-10-15"
    bar = factors_view._bar(long_row, axis, today, "en")
    assert bar["x0"] == 0 and bar["width"] == 1000 and bar["point"] is False


def test_a_scale_of_two_years_or_more_labels_four_moments_in_english():
    axis = factors_view.scale([{"started_on": "2023-01-01"}], date(2026, 11, 10), "en")
    # Evenly spaced moments: start, a third, two thirds, today.  The second one is April 2024.
    assert axis["ticks"] == ["Jan 2023", "Apr 2024", "Jul 2025", "today"]
    assert len(set(axis["ticks"])) == 4
    assert axis["start_text"] == "01 Jan 2023"


def test_a_scale_of_two_years_or_more_labels_four_moments_in_ukrainian():
    axis = factors_view.scale([{"started_on": "2023-01-01"}], date(2026, 11, 10), "uk")
    assert axis["ticks"] == ["січ. 2023", "квіт. 2024", "лип. 2025", "сьогодні"]
    assert axis["start_text"] == "01 січ. 2023"


def test_a_scale_of_ten_days_labels_two_moments_start_and_today():
    axis = factors_view.scale([{"started_on": "2026-10-31"}], date(2026, 11, 10), "en")
    assert axis["ticks"] == ["Oct 2026", "today"]


def test_a_scale_of_two_hundred_days_labels_three_moments():
    axis = factors_view.scale([{"started_on": "2026-04-24"}], date(2026, 11, 10), "en")
    assert axis["ticks"] == ["Apr 2026", "Aug 2026", "today"]


def test_a_tick_equal_to_the_one_before_it_is_dropped_but_today_stays():
    # Sixty days: the middle moment is 30 days in, still January, so it repeats the start.
    axis = factors_view.scale([{"started_on": "2026-01-01"}], date(2026, 3, 2), "en")
    assert axis["ticks"] == ["Jan 2026", "today"]


def test_form_template_keeps_block_elements_out_of_paragraphs():
    """A browser closes a <p> at a <blockquote> or <div>, so whatever followed
    lands outside the box the script looks in: the AI answer then fails."""
    import pathlib
    import re

    text = (pathlib.Path(__file__).parents[2] / "src/anamna/web/templates/medicine_form.html").read_text(encoding="utf-8")
    for paragraph in re.findall(r"<p\b[^>]*>(.*?)</p>", text, re.S):
        assert "<blockquote" not in paragraph and "<div" not in paragraph


def add_document(world: World, owner_id: str, doc_id: str, *, title: str, pages: list[str],
                 clinical_type: str = "consultation", report_date: str | None = "2025-02-13") -> str:
    """One document of ``owner_id`` with its pages and search row, stored the way the pipeline stores them."""
    with connect(world.settings) as connection:
        patient = connection.execute(
            "SELECT id FROM patients WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (owner_id,),
        ).fetchone()[0]
        vendor_id = ensure_vendor(connection, "Test Clinic", None)
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, imported_at, status, report_date
               ) VALUES (?, ?, ?, ?, ?, ?, 'text/plain', 1, ?, ?, ?, ?, 'native_text', 1, ?, 'final', ?)""",
            (
                doc_id, owner_id, patient, vendor_id, f"{doc_id}.txt", f"{doc_id}.txt", f"sha-{doc_id}",
                len(pages), title, clinical_type, utc_now(), report_date,
            ),
        )
        for number, text in enumerate(pages, start=1):
            connection.execute(
                """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, native_char_count)
                   VALUES (?, ?, ?, 'native_pdf_text', ?)""",
                (doc_id, number, text, len(text)),
            )
        content = "\n".join(pages)
        connection.execute(
            "INSERT INTO search_index(document_id, owner_user_id, content, content_folded) VALUES (?, ?, ?, ?)",
            (doc_id, owner_id, content, search_key(content)),
        )
        connection.commit()
    return doc_id


def test_document_search_returns_the_mention_with_its_snippet_and_labels(world, clients):
    owner = clients("alpha@example.test")
    add_document(world, world.alpha, "doc-diokor", title="Консультація кардіолога",
                 pages=["Призначено Діокор соло 160 мг один раз на добу."])
    response = owner.get("/medicines/documents", params={"name": "Діокор"})
    assert response.status_code == 200
    items = response.json()["items"]
    item = next(entry for entry in items if entry["id"] == "doc-diokor")
    assert item["mentions"] is True
    assert "Діокор" in item["snippet"]
    assert "Consultation" in item["title"]
    assert item["dated"] is True and "2025" in item["date_text"]
    assert item["type_label"]
    assert item["clinic"]


def test_document_search_by_a_title_word_never_returns_another_users_document(world, clients):
    add_document(world, world.alpha, "doc-cardio-alpha", title="Консультація кардіолога", pages=["Огляд."])
    add_document(world, world.bravo, "doc-cardio-bravo", title="Консультація кардіолога", pages=["Огляд."])
    alpha = clients("alpha@example.test")
    alpha_ids = [item["id"] for item in alpha.get("/medicines/documents", params={"q": "кардіолога"}).json()["items"]]
    assert "doc-cardio-alpha" in alpha_ids and "doc-cardio-bravo" not in alpha_ids

    bravo = clients("bravo@example.test")
    bravo_ids = [item["id"] for item in bravo.get("/medicines/documents", params={"q": "кардіолога"}).json()["items"]]
    assert "doc-cardio-bravo" in bravo_ids and "doc-cardio-alpha" not in bravo_ids


def test_guest_and_share_viewer_cannot_search_documents(world, clients):
    alpha = clients("alpha@example.test")
    add_document(world, world.alpha, "doc-share", title="Консультація", pages=["Діокор"])
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})
    assert bravo.get("/medicines/documents", params={"name": "Діокор"}).status_code == 403

    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
    with TestClient(create_app(world.settings)) as guest:
        assert guest.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        assert guest.get("/medicines/documents", params={"name": "Діокор"}).status_code == 403


def test_new_form_offers_documents_and_the_edit_form_shows_the_linked_one(world, clients):
    owner = clients("alpha@example.test")
    new_page = owner.get("/medicines/new").text
    assert "data-med-doc" in new_page
    assert "med-doc-linked" not in new_page

    factor_id = factor_id_of(create_entry(world, owner, document_id=world.document))
    edit = owner.get(f"/medicines/{factor_id}/edit").text
    assert 'id="med-doc-linked"' in edit
    linked = re.search(r'id="med-doc-linked"[^>]*>(.*?)</script>', edit, re.S).group(1)
    assert json.loads(linked)["id"] == world.document


def test_list_deletes_an_entry_from_its_card_and_returns_to_the_list(world, clients):
    owner = clients("alpha@example.test")
    first = factor_id_of(create_entry(world, owner, name="Диокор"))
    second = factor_id_of(create_entry(world, owner, name="Аспірин", atc_code="", reference_name="",
                                       reference_code=""))
    listing = owner.get("/medicines").text
    assert listing.count('name="action" value="remove"') == 2
    for factor_id in (first, second):
        assert f'action="/medicines/{factor_id}" method="post" data-confirm="' in listing

    removed = act(world, owner, first, action="remove")
    assert removed.status_code == 303
    assert removed.headers["location"] == "/medicines?saved=removed"
    assert row_of(world, first) is None
    assert row_of(world, second) is not None


def test_list_links_to_the_finder_only_when_a_consultation_exists(world, clients):
    owner = clients("alpha@example.test")
    create_entry(world, owner)
    assert "/medicines/found" not in owner.get("/medicines").text

    add_document(world, world.alpha, "doc-visit", title="Консультація", pages=["Огляд."])
    assert 'href="/medicines/found"' in owner.get("/medicines").text


def test_list_notes_the_candidates_waiting_for_review_only_when_there_are_some(world, clients, monkeypatch):
    owner = clients("alpha@example.test")
    create_entry(world, owner)
    monkeypatch.setattr(factor_candidates, "count", lambda connection, owner_id: 3)
    assert "an-med-found-note" in owner.get("/medicines").text

    monkeypatch.setattr(factor_candidates, "count", lambda connection, owner_id: 0)
    assert "an-med-found-note" not in owner.get("/medicines").text


def test_an_entry_with_six_effects_lists_all_of_them_under_the_disclosure(world, clients):
    owner = clients("alpha@example.test")
    factor_id = factor_id_of(create_entry(world, owner))
    labels = ["Нудота", "Сухий кашель", "Запаморочення", "Висип", "Сонливість", "Головний біль"]
    for label in labels:
        act(world, owner, factor_id, action="effect_add", label=label, direction="raises", note="")

    listing = owner.get("/medicines").text
    assert '<details class="an-med-fx">' in listing
    block = re.search(r'<ul class="an-med-fx__list".*?</ul>', listing, re.S)
    assert block is not None
    for label in labels:
        assert label in block.group(0), label
