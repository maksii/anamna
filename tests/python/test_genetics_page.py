"""/genetics: the DNA overview.  A result about the person's own genes is told
apart from results that only carry «ДНК» in their name (a germ found by PCR,
antibodies to DNA); every genetic test the planner offers is listed with
its price, and the page works for a record with no genetic results at all.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import genetics
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_vendor, seed_concepts
from anamna.locales.messages_genetics import MESSAGES
from anamna.reference import seed_reference_library
from anamna.security import create_session, create_user
from anamna.web import app as web
from anamna.web import testplan_routes
from anamna.web.app import create_app

ROWS = [
    # concept id, category, printed name, value (text or number), date
    ("hla-b27", "immunogenetics", "Виявлення носійства гену HLA B-27", "не виявлено", "2025-08-29"),
    ("chlamydia-trachomatis-pcr", "infection", "Chlamydia trachomatis (ПЛР) (кількісне визначення)", "не виявлено",
     "2022-08-23"),
    ("neisseria-gonorrhoeae-dna", "infection", "Виявлення ДНК Neisseria gonorrhoeae (ПЛР) (якісне визначення)",
     "не виявлено", "2022-08-23"),
    ("double-stranded-dna-antibodies", "autoimmune", "dsDNA", 0.15, "2025-08-29"),
]
OFFERS = {"gen-lactose": [{"lab": "esculab", "vendor": "Esculab", "cost": 670.0,
                           "items": ["Спадкова непереносимість лактози (кров)"]}]}


def build(tmp_path: Path, monkeypatch, *, with_results: bool = True, lang: str = "en",
          offers: dict | None = None) -> TestClient:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    settings = Settings(database_path=tmp_path / "health.sqlite3", source_dir=sources,
                        secret_key="genetics-test-secret", session_days=1)
    migrate(settings)
    user_id = create_user(settings, "dna@example.test", "DNA", "a-long-local-password")
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1988-03-17', 'male', ?)""", (patient_id, user_id, utc_now()))
        if with_results:
            vendor_id = ensure_vendor(connection, "Esculab", None)
            source = sources / "doc.pdf"
            source.write_text("report", encoding="utf-8")
            connection.execute(
                """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                       mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                       classification_confidence, report_date, imported_at, status)
                   VALUES ('doc', ?, ?, ?, 'doc.pdf', ?, 'application/pdf', 10, 'sha', 1, 'Lab', 'laboratory',
                           'native_text', 1, '2025-08-29', ?, 'final')""",
                (user_id, patient_id, vendor_id, str(source), utc_now()))
            for index, (concept_id, category, name, value, day) in enumerate(ROWS):
                numeric = isinstance(value, float)
                connection.execute(
                    """INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)
                       VALUES (?, ?, ?, ?, '2026-01-01')""",
                    (concept_id, concept_id, category, "numeric" if numeric else "text"))
                connection.execute(
                    """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                           raw_name, value_type, value_numeric, value_text, comparator, unit_raw, unit_canonical,
                           observed_at, verification_status, extraction_method, confidence, evidence_text,
                           parser_version, created_at)
                       VALUES (?, ?, ?, 'doc', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', 'test', 0.99, ?, 'test', ?)""",
                    (f"obs-{index}", user_id, patient_id, concept_id, name, "numeric" if numeric else "text",
                     value if numeric else None, None if numeric else value, "<" if numeric else None,
                     "kU/L" if numeric else None, "kU/L" if numeric else None, day, f"{name} {value}", utc_now()))
            seed_reference_library(connection)
    monkeypatch.setattr(testplan_routes, "special_offers",
                        lambda settings, connection, owner, entries: {e.id: [] for e in entries} | (offers or {}))
    web.invalidate_catalog()
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", lang)
    return client


def text_of(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def section(markup: str, anchor: str) -> str:
    start = markup.index(f'id="{anchor}"')
    return markup[start:markup.index("</section>", start)]


def test_own_genes_and_a_germs_dna_are_kept_apart(tmp_path, monkeypatch):
    response = build(tmp_path, monkeypatch, offers=OFFERS).get("/genetics")
    assert response.status_code == 200
    mine, other = section(response.text, "gx-mine"), section(response.text, "gx-other")
    assert 'href="/metrics/hla-b27"' in mine and "/metrics/chlamydia" not in mine
    assert "You do not carry HLA-B27" in text_of(mine)
    assert "does not need repeating" in text_of(mine)
    for concept in ("chlamydia-trachomatis-pcr", "neisseria-gonorrhoeae-dna", "double-stranded-dna-antibodies"):
        assert f'href="/metrics/{concept}"' in other
    assert "A germ's DNA (PCR)" in text_of(other) and "Antibodies to DNA" in text_of(other)


def test_every_dna_test_is_listed_with_price_plan_link_and_sources(tmp_path, monkeypatch):
    response = build(tmp_path, monkeypatch, offers=OFFERS).get("/genetics")
    page = text_of(response.text)
    for entry in genetics.ENTRIES:
        assert f'id="{entry.id}"' in response.text
    assert "From 670 UAH at Esculab" in page
    assert "Done 29 Aug 2025" in page  # HLA-B27, already in the record
    assert 'href="/plan-tests?special=1&amp;touched=1&amp;sx=gen-lactose"' in response.text
    assert "sx=gen-hla-b27" not in response.text  # done once is done
    assert 'href="/plan-tests?special=1&amp;preset=genetics"' in response.text
    assert "Not sold by the labs we compare" in page  # priced elsewhere, not this one
    assert "medlineplus.gov/genetics/gene/mthfr" in response.text and "dec.gov.ua" in response.text


def test_the_ukrainian_page_has_no_untranslated_keys(tmp_path, monkeypatch):
    response = build(tmp_path, monkeypatch, lang="uk", offers=OFFERS).get("/genetics")
    page = text_of(response.text)
    assert "Результати про ваші гени" in page and "ДНК збудника (ПЛР)" in page
    assert "Від 670 грн у Esculab" in page
    assert not re.search(r"\b(genetics|special)\.[a-z]", page)


def test_a_record_without_genetic_results_still_explains_the_tests(tmp_path, monkeypatch):
    response = build(tmp_path, monkeypatch, with_results=False).get("/genetics")
    assert response.status_code == 200
    page = text_of(response.text)
    assert "No tests of your own genes yet" in page
    assert 'id="gx-other"' not in response.text
    assert "Prices are not available yet" in page
    assert "Lactose intolerance gene" in page and "Warfarin dose genes" in page


@pytest.mark.parametrize("concept, category, name, expected", [
    ("hla-b27", "immunogenetics", "Виявлення носійства гену HLA B-27", "gene"),
    ("x", "unmapped", "Генетика. Мутація гена MTHFR", "gene"),
    ("mycoplasma-hominis-dna", "infection", "Виявлення ДНК Mycoplasma hominis (ПЛР)", "germ"),
    ("double-stranded-dna-antibodies", "autoimmune", "dsDNA", "antibody"),
    ("x", "breath_test", "Дихальний тест на непереносимість лактози", None),
    ("x", "infection", "Генітальний герпес, IgG", None),
])
def test_what_a_result_is_about(concept, category, name, expected):
    assert genetics.kind(concept, category, name) == expected


def test_the_printed_outcome_picks_the_explanation():
    assert genetics.outcome("не виявлено") == "absent"
    assert genetics.outcome("Виявлено") == "present"
    assert genetics.outcome("12.3") is None
    assert genetics.entry_for("x", "Генетика. Лейденська мутація FVL") == ["gen-thrombophilia"]


def test_every_explanation_reads_in_both_languages_and_is_sourced():
    keys = {f"genetics.entry.{entry.id}.{part}" for entry in genetics.ENTRIES for part in ("for", "limits")}
    keys |= {f"genetics.entry.{entry_id}.differs" for entry_id in genetics.DIFFERS}
    keys |= {f"genetics.result.{entry_id}.{part}" for entry_id in genetics.RESULT_TEXTS
             for part in ("absent", "present", "context")}
    assert keys <= MESSAGES.keys()
    for key, value in MESSAGES.items():
        assert value.get("en") and value.get("uk"), key
        for text in value.values():
            assert not re.search("[—–…“”→←]", text), key
    for entry in genetics.ENTRIES:
        regions = {genetics.SOURCES[source].region for source in genetics.ENTRY_SOURCES[entry.id]}
        assert "US" in regions and regions & {"EU", "INT"}, entry.id
    assert {entry.id for entry in genetics.ENTRIES} == {e for _, ids in genetics.GROUPS for e in ids}
