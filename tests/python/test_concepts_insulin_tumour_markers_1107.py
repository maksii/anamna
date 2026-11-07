"""Insulin, CA 125, CA 15-3 and HE4 get named concepts; free T4 in ng/dL joins pmol/L.

Synevo prints each of these several ways, and without a definition every
spelling minted its own unnamed concept: one analyte, two trend lines.
"""

import json
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.concepts import concept_for_alias, stable_concept_id
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts, stored_unit
from anamna.reference import LIBRARY_PATH, canonical_unit, convert_value

LIBRARY = json.loads(Path(LIBRARY_PATH).read_text(encoding="utf-8"))
ANALYTES = {entry["concept_id"]: entry for entry in LIBRARY["analytes"]}


@pytest.mark.parametrize(
    ("printed", "concept_id"),
    [
        ("Інсулін", "insulin"),
        ("Онкомаркер яєчників (СА-125)", "cancer-antigen-125-ca-125"),
        ("Онкомаркер яєчників (СА 125)", "cancer-antigen-125-ca-125"),
        ("СА125", "cancer-antigen-125-ca-125"),  # Cyrillic «СА»
        ("CA 125", "cancer-antigen-125-ca-125"),  # Latin
        ("Онкомаркер молочної залози (СА 15-3)", "cancer-antigen-15-3-ca-15-3"),
        ("CA15-3", "cancer-antigen-15-3-ca-15-3"),
        ("Онкомаркер HE4", "human-epididymis-protein-4-he4"),
        ("Ранній онкомаркер раку яєчників HE-4 антиген", "human-epididymis-protein-4-he4"),
        ("Тироксин вільний (T4 вільний)", "free-thyroxine"),
        ("Тироксин вільний (FT4)", "free-thyroxine"),
    ],
)
def test_printed_spellings_resolve_to_one_concept(printed, concept_id):
    definition = concept_for_alias(printed, "numeric")
    assert definition is not None, printed
    assert stable_concept_id(str(definition["name"])) == concept_id


def test_insulin_micro_units_are_one_unit_for_insulin_only():
    # Globally the two stay apart: «Од» is not an international unit elsewhere.
    assert canonical_unit("мкОд/мл") != canonical_unit("мкМО/мл")
    assert convert_value(6.45, "мкОд/мл", "mIU/L", "insulin") == 6.45
    assert convert_value(6.45, "мкМО/мл", "mIU/L", "insulin") == 6.45
    assert stored_unit("мкОд/мл", "mIU/L", "insulin") == "mIU/L"
    # The same spelling under another analyte does not fold.
    assert convert_value(1.6, "мкОд/мл", "mIU/L", "thyroid-stimulating-hormone") is None
    assert stored_unit("мкОд/мл", "mIU/L", "thyroid-stimulating-hormone") == "мкОд/мл"


def test_free_t4_ng_dl_converts_to_pmol_l():
    assert convert_value(1.22, "нг/дл", "pmol/L", "free-thyroxine") == pytest.approx(15.70, abs=0.01)
    assert convert_value(15.7, "пмоль/л", "ng/dL", "free-thyroxine") == pytest.approx(1.22, abs=0.01)
    # Molar, so per concept: ng/dL of anything else is not converted.
    assert convert_value(1.22, "нг/дл", "pmol/L", "free-triiodothyronine") is None


@pytest.mark.parametrize(
    "concept_id",
    ["insulin", "cancer-antigen-125-ca-125", "cancer-antigen-15-3-ca-15-3", "human-epididymis-protein-4-he4"],
)
def test_library_has_no_invented_number_and_ships_both_languages(concept_id):
    entry = ANALYTES[concept_id]
    assert entry["kind"] == "no_universal_target"
    assert entry["bands"] == []
    assert entry["source_ids"]
    assert entry["uk"]["name"] and entry["uk"]["short_description"] and entry["uk"]["why_it_matters"]


def test_a_learned_unnamed_concept_is_refiled_on_re_resolution(tmp_path):
    """Stored rows move without a re-read: ``repair_observation_semantics`` runs
    ``ensure_concept`` on every start, and a definition outranks the vendor
    alias learned while the analyte had no name."""
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as connection:
        seed_concepts(connection)
        vendor_id = ensure_vendor(connection, "Synevo", None)
        connection.execute(
            "INSERT INTO concepts(id, canonical_name, category, value_type, preferred_unit, created_at)"
            " VALUES ('unmapped-insulin', 'Інсулін (old)', 'unmapped', 'numeric', 'мкМО/мл', '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)"
            " VALUES ('unmapped-insulin', ?, 'Інсулін', 'інсулін')",
            (vendor_id,),
        )
        concept_id, preferred = ensure_concept(connection, "Інсулін", vendor_id, unit_raw="мкМО/мл")
        assert (concept_id, preferred) == ("insulin", "mIU/L")
        learned = connection.execute(
            "SELECT concept_id FROM concept_aliases WHERE vendor_id=? AND normalized_alias='інсулін'",
            (vendor_id,),
        ).fetchone()
        assert learned["concept_id"] == "insulin"
