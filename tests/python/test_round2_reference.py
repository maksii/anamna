"""Synthetic regressions for complete, correctly attributed public provenance."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.i18n import activate_locale, reset_locale
from anamna.reference import guidance, load_library, seed_reference_library, sources_for


def _extension():
    path = Path(__file__).resolve().parents[2] / "scripts/extend_calculation_reference_library.py"
    spec = importlib.util.spec_from_file_location("round2_calculation_references", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_atherogenic_equation_is_attributed_to_the_actual_paper():
    # The linked PMCID identifies this Cureus paper; it is not a diabetes-only
    # study or a paper published in Journal of Laboratory Physicians.
    extension = _extension()
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9812546/"
    source = extension.SOURCES[url]
    assert source[2] == "Cureus"
    assert source[3] == "A Descriptive Study of Atherogenic Indices in Patients Admitted to a Tertiary Care Hospital"
    assert "10.7759/cureus.32231" in source[4]
    library = load_library()
    stored = next(item for item in library["sources"] if item["url"] == url)
    assert stored["publisher"] == source[2]
    assert stored["name"] == source[3]
    assert stored["official"] is False


def test_no_target_sources_caveats_and_both_jurisdictions_survive_seed(tmp_path):
    settings = Settings(tmp_path / "provenance.sqlite3", tmp_path / "sources", "synthetic-secret")
    migrate(settings)
    sources = [
        dict(id="synthetic-us", name="First source", publisher="Synthetic publisher A",
             region="US", official=True, url="https://example.org/first", notes="Publication note"),
        dict(id="synthetic-eu", name="Second source", publisher="Synthetic publisher B",
             region="EU", official=True, url="https://example.org/second", access_note="Assay limitation"),
    ]
    analyte = dict(
        concept_id="synthetic-provenance", kind="no_universal_target", bands=[],
        source_id="synthetic-us", source_ids=["synthetic-us", "synthetic-eu"],
        short_description="Synthetic definition", no_universal_target_reason="Assay-specific interval",
        jurisdiction_note="Different published methods",
        uk=dict(short_description="Синтетичний опис", no_universal_target_reason="Інтервал залежить від методу",
                jurisdiction_note="Різні опубліковані методи"),
    )
    with connect(settings) as db:
        db.execute("INSERT INTO concepts(id,canonical_name,category,value_type,created_at) VALUES (?,?,'blood','numeric','2026-01-01')",
                   (analyte["concept_id"], "Synthetic provenance"))
        seed_reference_library(db, dict(sources=sources, analytes=[analyte]))
        assert {row["id"] for row in sources_for(db, [analyte["concept_id"]])} == {"synthetic-us", "synthetic-eu"}
        assert sources_for(db, []) == []
        english = guidance(db, analyte["concept_id"])
        assert english["source_ids"] == analyte["source_ids"]
        assert english["no_universal_target_reason"] == analyte["no_universal_target_reason"]
        assert english["jurisdiction_note"] == analyte["jurisdiction_note"]
        assert len(english["sources"]) == 2
        assert next(row for row in english["sources"] if row["id"] == "synthetic-eu")["notes"] == "Assay limitation"
        token = activate_locale("uk")
        try:
            ukrainian = guidance(db, analyte["concept_id"])
            assert ukrainian["no_universal_target_reason"] == analyte["uk"]["no_universal_target_reason"]
            assert ukrainian["jurisdiction_note"] == analyte["uk"]["jurisdiction_note"]
        finally:
            reset_locale(token)
        changed = copy.deepcopy(analyte)
        changed.update(source_ids=["synthetic-us"], no_universal_target_reason=None, jurisdiction_note=None, uk={})
        seed_reference_library(db, dict(sources=sources, analytes=[changed]))
        row = db.execute("SELECT * FROM concept_guidance WHERE concept_id=?", (analyte["concept_id"],)).fetchone()
        assert json.loads(row["source_ids_json"]) == ["synthetic-us"]
        assert row["no_universal_target_reason"] is None
        assert row["no_universal_target_reason_uk"] is None
        assert row["jurisdiction_note"] is None
        assert {item["id"] for item in sources_for(db, [analyte["concept_id"]])} == {"synthetic-us"}


def test_indirect_bilirubin_is_documented_as_conditional_not_universal():
    library = load_library()
    analyte = next(item for item in library["analytes"] if item["concept_id"] == "indirect-bilirubin")
    assert analyte["calculation"]["automatic_enabled"] is False
    assert analyte["calculation"]["requires_compatible_assays"] is True
    assert "north-west-anglia-direct-bilirubin-methods" in analyte["source_ids"]
    assert "disabled" in analyte["jurisdiction_note"]
    assert analyte["uk"]["jurisdiction_note"]


def test_calculated_globulin_has_no_invented_reference_band():
    library = load_library()
    analyte = next(item for item in library["analytes"] if item["concept_id"] == "globulin-calculated")
    assert analyte["unit"] == "g/L"
    assert analyte["bands"] == []
    assert analyte["kind"] == "no_universal_target"
    assert "electrophoresis" in analyte["short_description"]
    assert analyte["calculation"]["method"] == "derived_globulin"
    assert analyte["uk"]["why_it_matters"]


def test_cdc_is_not_claimed_as_the_authority_for_bmi_bands_before_twenty():
    library = load_library()
    analyte = next(item for item in library["analytes"] if item["concept_id"] == "body-mass-index")
    assert "age 20" in analyte["jurisdiction_note"]
    assert "18 or 19" in analyte["jurisdiction_note"]
    assert "20" in analyte["uk"]["jurisdiction_note"]
    for band in analyte["bands"]:
        if band["age_min"] < 20:
            assert band["source_id"] != "cdc-bmi"
            assert "cdc-bmi" not in band.get("corroborated_by", [])


def test_calculation_extension_is_idempotent_and_preserves_numeric_edges():
    library = load_library()
    before = {
        entry["concept_id"]: [(band.get("lower"), band.get("upper"), band.get("age_min"),
                               band.get("age_max")) for band in entry.get("bands", [])]
        for entry in library["analytes"]
    }
    once = copy.deepcopy(library)
    _extension().extend(library)
    assert library == once
    assert before == {
        entry["concept_id"]: [(band.get("lower"), band.get("upper"), band.get("age_min"),
                               band.get("age_max")) for band in entry.get("bands", [])]
        for entry in library["analytes"]
    }
