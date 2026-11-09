"""/allergy: the allergy overview, its empty state, and the ALEX grading fix
on the allergy panel.

The fixture is a miniature ALEX record: two draws of birch Bet v 1 (history),
a positive peanut storage protein, a negative cat component, an extract and
total IgE, all printed with the ALEX cut-off (vendor upper 0.3).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import allergy
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_vendor, seed_concepts
from anamna.locales.messages_allergy import MESSAGES
from anamna.reference import seed_reference_library
from anamna.security import create_session, create_user
from anamna.web import app as web
from anamna.web.app import create_app

PASSWORD = "a-long-local-password"
ALEX_REF = "IgE < 0,3 негативна або сумнівна"

ROWS = [
    # concept id, printed name, value, comparator, unit, date, document
    ("bet-v-1", "Береза повисла Bet v 1 PR-10", 0.5, None, "kUA/L", "2025-08-28", "doc-2"),
    ("bet-v-1", "Береза повисла Bet v 1 PR-10", 0.2, None, "kUA/L", "2024-05-01", "doc-1"),
    ("ara-h-2", "Ara h 2 2S Albumin", 6.0, None, "kUA/L", "2025-08-28", "doc-2"),
    ("fel-d-1", "Кіт Fel d 1 Uteroglobin", 0.1, "<", "kUA/L", "2025-08-28", "doc-2"),
    ("cyn-d", "Цинодон пальчатий Cyn d", 0.11, None, "kUA/L", "2025-08-28", "doc-2"),
    ("total-immunoglobulin-e", "Загальний IgE", 39.0, None, "kU/L", "2025-08-28", "doc-2"),
]


def build(tmp_path: Path, *, with_results: bool = True, lang: str = "en") -> tuple[Settings, str, TestClient]:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    settings = Settings(database_path=tmp_path / "health.sqlite3", source_dir=sources,
                        secret_key="allergy-test-secret", session_days=1)
    migrate(settings)
    user_id = create_user(settings, "allergy@example.test", "Allergy", PASSWORD)
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""", (patient_id, user_id, utc_now()))
        if with_results:
            vendor_id = ensure_vendor(connection, "Synevo", None)
            for document_id, day in (("doc-1", "2024-05-01"), ("doc-2", "2025-08-28")):
                source = sources / f"{document_id}.pdf"
                source.write_text("report", encoding="utf-8")
                connection.execute(
                    """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                           mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                           classification_confidence, report_date, imported_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'application/pdf', 10, ?, 1, 'ALEX² - протестовані алергени',
                               'allergy', 'native_text', 1, ?, ?, 'final')""",
                    (document_id, user_id, patient_id, vendor_id, source.name, str(source), document_id, day, utc_now()))
            for index, (concept_id, name, value, comparator, unit, day, document_id) in enumerate(ROWS):
                connection.execute(
                    """INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, preferred_unit, created_at)
                       VALUES (?, ?, 'allergy', 'numeric', ?, '2026-01-01')""", (concept_id, name, unit))
                total = concept_id == "total-immunoglobulin-e"
                connection.execute(
                    """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                           raw_name, value_type, value_numeric, comparator, unit_raw, unit_canonical, observed_at,
                           vendor_reference_text, vendor_reference_high, vendor_reference_high_inclusive, vendor_interpretation, verification_status,
                           extraction_method, confidence, evidence_text, parser_version, created_at)
                       VALUES (?, ?, ?, ?, 1, ?, ?, 'numeric', ?, ?, ?, ?, ?, ?, ?, 0, 'within_vendor_range', 'verified',
                               'test', 0.99, ?, 'test', ?)""",
                    (f"obs-{index}", user_id, patient_id, document_id, concept_id, name, value, comparator, unit, unit,
                     day, "Дорослі: < 100 kU/l" if total else ALEX_REF, 100.0 if total else 0.3,
                     f"{name} {value}", utc_now()))
            seed_reference_library(connection)
    web.invalidate_catalog()
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", lang)
    return settings, user_id, client


def text_of(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def test_the_page_answers_what_was_found_and_grades_on_the_alex_scale(tmp_path: Path):
    _, _, client = build(tmp_path)
    response = client.get("/allergy")
    assert response.status_code == 200
    page = text_of(response.text)
    assert "Sensitisation found: 2 positive results" in page
    # Codes verbatim, the ALEX level for the value, never an ImmunoCAP class.
    assert "Bet v 1 PR-10" in page and "Ara h 2 2S Albumin" in page
    assert "High IgE level" in page and "Low IgE level" in page
    assert "Class 1" not in page
    # Grouped by source, the earlier draw kept under the latest one.
    assert "Tree pollen" in page and "Foods: legumes" in page
    assert "Earlier: 01 May 2024, 0.2 kUA/L" in page
    # Total IgE with the laboratory range, families that were tested, sources.
    assert "Total IgE" in page and "Reference: < 100 kU/L" in page
    assert "PR-10 proteins (birch type)" in page and "Seed storage proteins" in page
    assert "pubmed.ncbi.nlm.nih.gov/37186333" in response.text
    assert "dec.gov.ua" in response.text
    assert 'href="/plan-tests?special=1&amp;topic=allergy"' in response.text


@pytest.mark.parametrize("query, expected", [("cat", "Cat"), ("кіт", "Cat"), ("Bet v", "Birch"), ("pollen", "Birch")])
def test_was_i_tested_for_finds_a_source_in_either_language(tmp_path: Path, query: str, expected: str):
    _, _, client = build(tmp_path)
    page = text_of(client.get("/allergy", params={"q": query}).text)
    assert "match" in page and expected in page


def test_an_allergen_that_was_not_tested_says_so_and_offers_the_planner(tmp_path: Path):
    _, _, client = build(tmp_path)
    response = client.get("/allergy", params={"q": "zebra"})
    assert 'Nothing matching "zebra" is on your tests' in text_of(response.text)
    assert "Plan a test for it" in response.text


def test_a_record_without_allergy_results_explains_the_tests_and_links_the_planner(tmp_path: Path):
    _, _, client = build(tmp_path, with_results=False)
    response = client.get("/allergy")
    assert response.status_code == 200
    page = text_of(response.text)
    assert "No allergy tests in your record yet" in page
    assert "Multiplex arrays" in page and "Total IgE: all IgE antibodies together" in page
    assert 'href="/plan-tests?special=1&amp;topic=allergy"' in response.text


def test_the_page_reads_in_ukrainian(tmp_path: Path):
    _, _, client = build(tmp_path, lang="uk")
    page = text_of(client.get("/allergy").text)
    assert "Виявлено сенсибілізацію: 2 позитивні результати" in page
    assert "Пилок дерев" in page and "Високий рівень IgE" in page
    assert "Bet v 1 PR-10" in page  # WHO/IUIS codes are never translated


def test_the_allergy_panel_grades_alex_results_on_alex_levels_and_links_the_overview(tmp_path: Path):
    _, _, client = build(tmp_path)
    response = client.get("/panels/allergy")
    assert response.status_code == 200
    page = text_of(response.text)
    assert 'href="/allergy"' in response.text
    assert "ALEX levels" in page and "High IgE level" in page
    assert "Class 0 · not detected" not in page and "Class 1 · low" not in page


@pytest.mark.parametrize("name, source, component", [
    ("Сеча собаки (вкл. Can f 5) Can f_male urine", "can_f", False),
    ("Can f_Fd1 Uteroglobin", "can_f", True),
    ("Фундук Cor a 1.0401 PR-10", "cor_a", True),
    ("Cor a 1.0103 PR-10", "cor_a_pollen", True),
    ("Рис Ory s", "ory_s", False),
    ("Кролятина Ory_meat", "ory_meat", False),
    ("Коноплі звичайні (посівні) Can s", "can_s", False),
    ("Помідор Sola l", "sola_l", False),
    ("Картопля Sol t", "sol_t", False),
    ("Вогняна мураха Sol spp.", "sol_spp", False),
    ("Подорожник ланцетолистий", "pla_l", False),
    ("Гірчиця Sin", "sin_a", False),
    ("Bos d 6 Serum Albumin", "bos_d_meat", True),
    ("Gal d 5 Serum Albumin", "gal_d_yolk", True),
])
def test_printed_names_resolve_to_their_allergen_source(name: str, source: str, component: bool):
    parsed = allergy.parse_name(name)
    assert parsed["source"] == source
    assert parsed["component"] is component
    # Every code the laboratory printed stays in the shown text.
    for code in re.findall(r"[A-Z][a-z]{1,3} [a-z]{1,4}(?: \d+(?:\.\d+)?)?", name):
        assert code in parsed["code_text"]


def test_alex_levels_follow_the_report_legend():
    legend = allergy.alex_legend()
    assert [allergy.level_of(value, legend)["class"] for value in (0.1, 0.3, 0.99, 1, 5, 14.9, 15, 80)] == [
        0, 1, 1, 2, 3, 3, 4, 4]


def test_every_source_family_and_group_speaks_both_languages():
    keys = ([f"allergen.{source}" for source in allergy.SOURCE_GROUP]
            + [f"allergy.page.group.{group}" for group in allergy.GROUPS]
            + [f"allergy.family.{key}.{part}" for key in allergy.FAMILIES for part in ("name", "what", "means")])
    for key in keys:
        assert MESSAGES[key]["en"] and MESSAGES[key]["uk"], key
    for family in allergy.FAMILIES.values():
        assert all(source in allergy.CITATIONS for source in family["sources"])
    regions = {allergy.CITATIONS[source]["region"] for ids in allergy.BLOCK_SOURCES.values() for source in ids}
    assert {"US", "EU", "UA"} <= regions


def test_no_ai_slop_punctuation_in_the_catalogue():
    for key, entry in MESSAGES.items():
        for text in entry.values():
            assert not re.search("[—–→“”‘’]", text), key
