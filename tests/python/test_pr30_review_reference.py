"""The reference library after the review of the connection audit; no patient records involved."""
from __future__ import annotations

import copy
import json
import runpy
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "data/reference_library.json"
review = runpy.run_path(str(ROOT / "scripts/extend_review_reference_library.py"))


def _library() -> dict:
    return json.loads(LIBRARY.read_text(encoding="utf-8"))


def test_a_laboratory_catalogue_is_never_an_official_source_and_is_spelled_one_way():
    sources = _library()["sources"]
    assert "laboratory_catalog" not in {source.get("kind") for source in sources}
    catalogues = [source for source in sources if source.get("kind") == "laboratory_catalogue"]
    assert {"mayo-amh1-2026", "synevo-gliadin-igg-9169", "dila-giardia-total-2026",
            "medlab-folate-genotypes-6111", "corewell-albumin-globulin-ratio"} <= {source["id"] for source in catalogues}
    assert [source["id"] for source in catalogues if source["official"]] == []
    assert next(source for source in sources if source["id"] == "utah-laboratory-hematology")["official"] is False


def test_every_source_names_a_real_identifier_and_a_stable_public_address():
    for source in _library()["sources"]:
        assert source["identifier"] != source["id"], source["id"]
        # A source read for this release is pinned to the commit that was read.
        assert source["reviewed_at"] < "2026-11-15" or "/blob/main/" not in source["url"], source["id"]
        assert "prd1.mayocliniclabs.com" not in source["url"], source["id"]
        assert "/api/sitecore/" not in source["url"], source["id"]
        # A page that could not be retrieved is not cited.
        assert "retrieval returned" not in source.get("access_note", ""), source["id"]


def test_agreement_keeps_the_established_vocabulary_and_the_version_follows_the_review():
    library = _library()
    assert {entry.get("agreement") for entry in library["analytes"]} <= {"concordant", "divergent", "single_source", None}
    # The version is never older than the newest review it contains.
    assert library["version"] >= max(source["reviewed_at"] for source in library["sources"])


def test_indirect_bilirubin_keeps_the_ukrainian_guidelines_beside_the_assay_caveat():
    entry = next(item for item in _library()["analytes"] if item["concept_id"] == "indirect-bilirubin")
    for note in (entry["jurisdiction_note"], entry["uk"]["jurisdiction_note"]):
        assert "00212" in note and "00214" in note and "50 мкмоль/л" in note
    assert "automatic reconstruction is disabled" in entry["jurisdiction_note"]
    assert "автоматичне відновлення вимкнено" in entry["uk"]["jurisdiction_note"]


def test_atherogenic_coefficient_loses_only_the_castelli_label():
    entry = next(item for item in _library()["analytes"] if item["concept_id"] == "atherogenic-coefficient")
    assert entry["short_description"].startswith("The atherogenic coefficient is a ratio")
    assert "Castelli" not in entry["short_description"] and "Кастеллі" not in entry["uk"]["short_description"]
    assert "«до 3»" in entry["short_description"] and "«до 3»" in entry["uk"]["short_description"]


def test_every_citation_added_by_the_review_resolves_and_adds_no_band():
    library = _library()
    sources = {source["id"]: source for source in library["sources"]}
    analytes = {entry["concept_id"]: entry for entry in library["analytes"]}
    for source in review["SOURCES"]:
        assert sources[source["id"]]["official"] is True and source["access_note"]
        assert source["url"].startswith("https://")
    for concept_id, (source_ids, note, note_uk) in review["ATTACH"].items():
        entry = analytes[concept_id]
        assert set(source_ids) <= set(entry["source_ids"])
        assert {sources[key]["region"] for key in entry["source_ids"]} == set(entry["regions_covered"])
        assert "UA" in entry["regions_covered"]
        assert note in entry["jurisdiction_note"] and note_uk in entry["uk"]["jurisdiction_note"]
        assert entry["bands"] == [] and entry["kind"] == "no_universal_target"
        assert entry["agreement"] == ("divergent" if concept_id in review["DIVERGENT"] else "concordant")


def test_the_extensions_change_nothing_in_the_published_library():
    library = _library()
    once = copy.deepcopy(library)
    review["extend_all"](library)
    assert library == once


def test_the_extensions_rebuild_the_published_library_from_the_previous_release():
    shown = subprocess.run(["git", "show", "origin/main:data/reference_library.json"],
                           cwd=ROOT, capture_output=True)
    if shown.returncode:
        pytest.skip("origin/main is not available in this checkout")
    library = json.loads(shown.stdout.decode("utf-8"))
    if library["version"] != "2026-08-07":
        pytest.skip("the rebuild is defined against the 2026-08-07 release")
    review["extend_all"](library)
    assert json.dumps(library, ensure_ascii=False, indent=2) + "\n" == LIBRARY.read_text(encoding="utf-8")
