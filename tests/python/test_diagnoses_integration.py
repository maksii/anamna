"""Diagnoses wired into the application shell: the navigation link, the dashboard
tile, the record search, and the English metric cards the possible-diagnosis
matrix reads while the page itself is shown in Ukrainian.

The rows are inserted directly, so these tests depend on the shell and not on
the diagnosis pages themselves.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from anamna import icd10, security
from anamna.db import connect, migrate, utc_now
from anamna.i18n import MESSAGES, activate_locale, reset_locale, t_plural
from anamna.ingest.concepts import stable_concept_id
from anamna.ingest.pipeline import seed_concepts
from anamna.security import create_user
from anamna.web import app as web
from anamna.web.app import create_app

from test_web_profile import login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

LDL_ID = stable_concept_id("LDL cholesterol")


@pytest.fixture(autouse=True)
def clear_throttles():
    security._attempts.clear()
    yield
    security._attempts.clear()


@dataclass
class World:
    settings: object
    alpha: str
    patient: str


@pytest.fixture
def world(tmp_path) -> World:
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
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
    return World(settings, alpha, patient)


@pytest.fixture
def owner(world) -> TestClient:
    client = TestClient(create_app(world.settings))
    login(client, "alpha@example.test")
    return client


def add_diagnosis(world: World, *, code: str = "", name: str = "", status: str = "active",
                  certainty: str = "confirmed") -> str:
    diagnosis_id = str(uuid.uuid4())
    now = utc_now()
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnoses(id, owner_user_id, patient_id, code, name, status, certainty,
                                     created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (diagnosis_id, world.alpha, world.patient, code, name, status, certainty, now, now),
        )
        connection.commit()
    return diagnosis_id


def add_possible(world: World, rule_id: str = "lipid_mixed", code: str = "E78.2") -> str:
    suspicion_id = str(uuid.uuid4())
    now = utc_now()
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO diagnosis_suspicions(id, owner_user_id, rule_id, code, state, evidence_json,
                                                first_seen_at, last_seen_at, state_changed_at)
               VALUES (?, ?, ?, ?, 'open', '[]', ?, ?, ?)""",
            (suspicion_id, world.alpha, rule_id, code, now, now, now),
        )
        connection.commit()
    return suspicion_id


def test_navigation_links_to_diagnoses_in_both_locales(owner):
    english = owner.get("/")
    assert english.status_code == 200
    assert 'href="/diagnoses"' in english.text
    assert "Diagnoses" in english.text

    owner.cookies.set("anamna_lang", "uk")
    ukrainian = owner.get("/")
    assert 'href="/diagnoses"' in ukrainian.text
    assert "Діагнози" in ukrainian.text


def test_dashboard_tile_shows_the_empty_note_for_the_owner(world, owner):
    page = owner.get("/").text
    assert MESSAGES["dx.tile.label"]["en"] in page
    assert MESSAGES["dx.tile.note_empty"]["en"] in page


def test_dashboard_tile_names_a_current_diagnosis(world, owner):
    add_diagnosis(world, name="Hypothyroidism")
    with connect(world.settings) as connection:
        tile = web._diagnosis_tile(connection, world.alpha, owner=True)
    assert tile is not None
    assert tile["value"] == "1"
    assert tile["note"] == "Hypothyroidism"
    assert tile["tone"] == "neutral"
    assert "Hypothyroidism" in owner.get("/").text


def test_dashboard_tile_counts_the_open_possible_diagnosis_in_the_plural_note(world):
    add_possible(world)
    with connect(world.settings) as connection:
        tile = web._diagnosis_tile(connection, world.alpha, owner=True)
    assert tile is not None
    assert tile["note"] == t_plural("dx.tile.note_possible", 1)
    assert tile["tone"] == "due"
    assert tile["value"] == "0"


def test_record_search_finds_a_diagnosis_by_code_and_by_its_ukrainian_title(world):
    diagnosis_id = add_diagnosis(world, code="E78.2")
    title = icd10.name("E78.2", "uk")
    assert title, "the catalogue must hold a Ukrainian title for E78.2"
    word = max(re.findall(r"\w+", title), key=len)
    with connect(world.settings) as connection:
        by_title = web._record_search(connection, world.alpha, word, 0)
        by_code = web._record_search(connection, world.alpha, "E78.2", 0)
    for found in (by_title, by_code):
        group = next(group for group in found if group["key"] == "diagnoses")
        assert group["rows"][0]["url"] == f"/diagnoses/{diagnosis_id}"
        assert group["rows"][0]["subtitle"] == MESSAGES["dx.status.active"]["en"]


def test_matrix_cards_stay_english_after_display_cards_in_the_same_request(world):
    token = activate_locale("uk")
    request_cache: dict[str, object] = {}
    cache_token = web._request_cache.set(request_cache)
    try:
        with connect(world.settings) as connection:
            display = web._display_cards(connection, world.alpha)
            in_request = web._matrix_cards(connection, world.alpha)
            again = web._matrix_cards(connection, world.alpha)
        assert web._request_cache.get() is request_cache, "matrix_cards must restore the request cache"
    finally:
        web._request_cache.reset(cache_token)
        reset_locale(token)

    with connect(world.settings) as connection:
        fresh_english = web._matrix_cards(connection, world.alpha)

    names = [card["name"] for card in in_request]
    assert names == [card["name"] for card in fresh_english]
    assert names == [card["name"] for card in again]
    localized = {card["id"]: card["name"] for card in display}
    assert any(localized[card["id"]] != card["name"] for card in in_request if card["id"] in localized)
