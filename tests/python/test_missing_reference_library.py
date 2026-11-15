"""Public target identity and source integrity; no patient records involved."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/extend_missing_reference_library.py"
SPEC = importlib.util.spec_from_file_location("missing_reference_extension", SCRIPT)
extension = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extension)


def test_every_missing_target_has_sourced_bilingual_guidance_and_catalog_unit():
    entries = extension.additions()
    assert len(entries) == 22
    catalog = {stable_concept_id(item["name"]): item for item in CONCEPT_DEFINITIONS}
    sources = {item["id"]: item for item in extension.SOURCES}
    assert len(sources) == len(extension.SOURCES)
    assert len({entry["concept_id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert entry["concept_id"] in catalog
        assert entry["unit"] == catalog[entry["concept_id"]]["unit"]
        assert entry["kind"] == "no_universal_target"
        assert entry["bands"] == []
        assert entry["short_description"] and entry["why_it_matters"]
        assert entry["uk"]["name"]
        assert entry["uk"]["short_description"] != entry["short_description"]
        assert entry["uk"]["why_it_matters"] != entry["why_it_matters"]
        assert set(entry["source_ids"]) <= sources.keys()
        assert set(entry["regions_covered"]) == {sources[key]["region"] for key in entry["source_ids"]}
        assert entry["retest_interval_months"] is None
    for source in sources.values():
        assert source["identifier"] and source["publisher"] and source["name"]
        assert source["url"].startswith("https://")
        assert source["region"] in {"US", "EU", "UA", "INT"}
        assert isinstance(source["official"], bool)


def test_extension_is_idempotent_and_preserves_existing_clinical_bands():
    # Entirely synthetic existing guidance; the extension must not rewrite it.
    existing = {"concept_id": "synthetic-result", "bands": [{"lower": 3, "upper": 7}]}
    library = {"sources": [], "analytes": [copy.deepcopy(existing)]}
    result = extension.extend(library)
    assert result["analytes_added"] == 22
    assert result["sources_added"] == len(extension.SOURCES)
    once = copy.deepcopy(library)
    assert extension.extend(library) == {"analytes_added": 0, "sources_added": 0}
    assert library == once
    assert library["analytes"][0] == existing


def test_uncertain_methods_and_qualitative_genotypes_are_never_given_numeric_targets():
    entries = {entry["canonical_name"]: entry for entry in extension.additions()}
    homa = entries["HOMA index (reported, model unspecified)"]
    assert "not silently relabeled HOMA1-IR or HOMA2-IR" in homa["why_it_matters"]
    h_pylori = entries["H. pylori test, method unspecified"]
    assert "source does not establish" in h_pylori["short_description"]
    gliadin = entries["Gliadin IgG antibodies"]
    assert "does not establish a deamidated" in gliadin["why_it_matters"]
    for name in ("ROMA, premenopausal", "ROMA, postmenopausal"):
        assert len(entries[name]["source_ids"]) == 2
        assert entries[name]["jurisdiction_note"]
        assert entries[name]["uk"]["jurisdiction_note"]
        assert entries[name]["bands"] == []
    for name, *_ in extension.GENOTYPES:
        assert entries[name]["never_verdict"] is True
        assert entries[name]["not_a_measurement"] is True
        assert entries[name]["unit"] is None
