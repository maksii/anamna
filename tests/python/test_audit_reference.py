"""Audit of the reference engine: unjudged values, censored results, the
laboratory's own flag, overlapping bands, and the library's provenance.

Each test pins one way a verdict used to be wrong in front of a patient.
"""

import json
from pathlib import Path

import pytest

from anamna import reference
from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts
from anamna.reference import LIBRARY_PATH, evaluate, seed_reference_library

BENIGN = reference.BENIGN_INTERPRETATIONS
LIBRARY = json.loads(Path(LIBRARY_PATH).read_text(encoding="utf-8"))
ANALYTES = {entry["concept_id"]: entry for entry in LIBRARY["analytes"]}
EGFR = "estimated-glomerular-filtration-rate-ckd-epi-2021"
HS_CRP = "high-sensitivity-c-reactive-protein"


def _unit(concept_id: str) -> str:
    return ANALYTES[concept_id]["unit"]


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        seed_reference_library(conn)
        yield conn


# --- a value no band contains is not judged by a band that does not describe it


def test_inr_without_an_anticoagulant_is_not_judged_normal(connection):
    verdict = evaluate(connection, "inr", value_numeric=1.8, unit=_unit("inr"), age_years=34, sex="male")
    assert verdict["interpretation"] not in BENIGN
    assert verdict["authority"] != "curated"


def test_inr_without_an_anticoagulant_is_judged_by_the_laboratory_range(connection):
    verdict = evaluate(
        connection, "inr", value_numeric=1.8, unit=_unit("inr"), age_years=34, sex="male",
        vendor_low=0.8, vendor_high=1.2,
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "high"


def test_inr_on_an_anticoagulant_is_judged_against_the_therapeutic_range(connection):
    verdict = evaluate(
        connection, "inr", value_numeric=2.5, unit=_unit("inr"), age_years=34, sex="male",
        clinical_context={"vka_therapy": True},
    )
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "normal"


def test_ferritin_of_unknown_sex_is_not_reported_high_or_low(connection):
    high = evaluate(connection, "ferritin", value_numeric=120.0, unit=_unit("ferritin"), age_years=34, sex=None)
    assert high["interpretation"] != "high"
    assert high["authority"] != "curated"
    between = evaluate(connection, "ferritin", value_numeric=50.0, unit=_unit("ferritin"), age_years=34, sex=None)
    assert between["authority"] != "curated"
    low = evaluate(connection, "ferritin", value_numeric=10.0, unit=_unit("ferritin"), age_years=34, sex=None)
    assert low["authority"] == "curated"
    assert low["interpretation"] == "low"


def test_ferritin_with_known_sex_keeps_its_curated_reading(connection):
    male = evaluate(connection, "ferritin", value_numeric=120.0, unit=_unit("ferritin"), age_years=34, sex="male")
    assert male["authority"] == "curated"
    assert male["interpretation"] in BENIGN


def test_uric_acid_targets_do_not_judge_a_person_without_gout(connection):
    unit = _unit("uric-acid")
    for value in (380.0, 170.0):
        verdict = evaluate(connection, "uric-acid", value_numeric=value, unit=unit, age_years=34, sex="male")
        assert verdict["authority"] != "curated", value
    high = evaluate(connection, "uric-acid", value_numeric=420.0, unit=unit, age_years=34, sex="male")
    assert high["authority"] == "curated"
    assert high["interpretation"] == "high"
    treated = evaluate(
        connection, "uric-acid", value_numeric=300.0, unit=unit, age_years=34, sex="male",
        clinical_context={"urate_lowering_therapy": True},
    )
    assert treated["authority"] == "curated"
    assert treated["interpretation"] == "normal"


# --- a censored result is judged on the side the laboratory stated


def test_strict_less_than_selects_the_band_below_the_printed_limit(connection):
    exact = evaluate(connection, HS_CRP, value_numeric=1.0, unit=_unit(HS_CRP), age_years=34, sex="male")
    assert exact["low"] == 1.0
    censored = evaluate(
        connection, HS_CRP, value_numeric=1.0, unit=_unit(HS_CRP), age_years=34, sex="male",
        comparator="<",
    )
    assert censored["high"] == 1.0
    assert censored["low"] is None
    assert censored["interpretation"] in BENIGN


def test_greater_than_is_not_judged_by_a_band_closed_above(connection):
    verdict = evaluate(
        connection, EGFR, value_numeric=60.0, unit=_unit(EGFR), age_years=34, sex="male",
        comparator=">",
    )
    assert verdict["authority"] != "curated"


def test_greater_or_equal_is_judged_by_a_band_open_above(connection):
    verdict = evaluate(
        connection, EGFR, value_numeric=90.0, unit=_unit(EGFR), age_years=34, sex="male",
        comparator=">=",
    )
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "normal"
    assert verdict["low"] == 90
    assert verdict["high"] is None


# --- the laboratory's own flag is what the report told the patient


def test_a_laboratory_flag_contradicting_a_normal_reading_is_a_conflict(connection):
    verdict = evaluate(
        connection, "potassium", value_numeric=4.2, unit=_unit("potassium"), age_years=34, sex="male",
        vendor_interpretation="high",
    )
    assert verdict["conflicts_with_vendor"] is True
    assert verdict["interpretation"] == "indeterminate"


def test_a_laboratory_flag_beats_the_printed_bounds(connection):
    verdict = evaluate(
        connection, "potassium", value_numeric=4.2, unit=_unit("potassium"), age_years=34, sex="male",
        vendor_low=3.5, vendor_high=5.1, vendor_interpretation="high",
    )
    assert verdict["conflicts_with_vendor"] is True
    assert verdict["interpretation"] == "indeterminate"


def test_a_laboratory_flag_saying_within_agrees_with_a_normal_reading(connection):
    verdict = evaluate(
        connection, "potassium", value_numeric=4.2, unit=_unit("potassium"), age_years=34, sex="male",
        vendor_low=3.5, vendor_high=5.1, vendor_interpretation="within_vendor_range",
    )
    assert verdict["interpretation"] in BENIGN
    assert verdict["conflicts_with_vendor"] is False


def test_printed_bounds_without_a_flag_still_agree_with_a_normal_reading(connection):
    verdict = evaluate(
        connection, "potassium", value_numeric=4.2, unit=_unit("potassium"), age_years=34, sex="male",
        vendor_low=3.5, vendor_high=5.1, vendor_interpretation=None,
    )
    assert verdict["interpretation"] in BENIGN


# --- a censored laboratory range is judged only where its side is certain

ALBUMIN = "albumin"


def test_less_than_below_a_laboratory_range_is_low(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=5.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0, comparator="<",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "low"
    assert verdict["vendor_status"] == "low"


def test_greater_than_above_a_laboratory_range_is_high(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=100.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=20.0, vendor_high=100.0, comparator=">",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "high"


def test_less_than_with_only_an_upper_bound_is_normal_when_below_it(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=5.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_high=40.0, comparator="<",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "normal"


def test_less_than_inside_a_laboratory_range_is_unjudged(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=30.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0, comparator="<",
    )
    assert verdict["interpretation"] == "unjudged"
    assert verdict["vendor_status"] is None


def test_less_than_a_range_starting_at_zero_is_normal(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=0.3, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=0.0, vendor_high=5.0, comparator="<",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "normal"


def test_less_than_just_above_a_positive_lower_bound_is_low(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=0.3, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=0.5, vendor_high=5.0, comparator="<",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "low"


def test_less_than_reaching_above_the_upper_bound_is_unjudged(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=3.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=1.0, vendor_high=5.0, comparator="<",
    )
    assert verdict["interpretation"] == "unjudged"


def test_greater_than_inside_a_laboratory_range_is_unjudged(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=30.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0, comparator=">",
    )
    assert verdict["interpretation"] == "unjudged"
    assert verdict["vendor_status"] is None


def test_an_exact_value_inside_a_laboratory_range_is_still_normal(connection):
    verdict = evaluate(
        connection, ALBUMIN, value_numeric=30.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0,
    )
    assert verdict["interpretation"] == "normal"


def test_a_stored_laboratory_flag_still_decides_a_censored_result(connection):
    flagged = evaluate(
        connection, ALBUMIN, value_numeric=5.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0, vendor_interpretation="within_vendor_range",
    )
    censored = evaluate(
        connection, ALBUMIN, value_numeric=5.0, unit=_unit(ALBUMIN), age_years=34, sex="male",
        vendor_low=5.0, vendor_high=40.0, vendor_interpretation="within_vendor_range",
        comparator="<",
    )
    assert censored["interpretation"] == flagged["interpretation"]
    assert censored["vendor_status"] == "within_vendor_range"


# --- one body, one answer


def test_a_bodys_position_matches_the_chip_when_its_bands_overlap(connection):
    verdict = evaluate(connection, "folate-serum", value_numeric=4.0, unit=_unit("folate-serum"), age_years=34, sex="male")
    assert verdict["interpretation"] == "low"
    who = [item for item in verdict["authority_positions"] if item["source_id"] == "who-folate-vmnis-2015"]
    assert len(who) == 1
    assert who[0]["interpretation"] == verdict["interpretation"]


# --- the code and the library agree on the flags they both carry


def test_library_flags_stay_in_step_with_the_code():
    for concept_id, entry in ANALYTES.items():
        if entry.get("positive_is_good"):
            assert concept_id in reference.POSITIVE_IS_GOOD, concept_id
        if entry.get("never_verdict") or entry.get("not_a_measurement"):
            assert concept_id in reference.NOT_A_MEASUREMENT, concept_id


# --- every number in the library says where it came from


def test_every_analyte_with_numeric_bands_cites_its_sources():
    for concept_id, entry in ANALYTES.items():
        bands = entry.get("bands") or []
        if any(band.get("lower") is not None or band.get("upper") is not None for band in bands):
            assert entry.get("source_ids"), concept_id
        for band in bands:
            if band.get("source_id"):
                assert band["source_id"] in (entry.get("source_ids") or []), (concept_id, band["source_id"])


def test_every_source_has_an_identifier():
    for source in LIBRARY["sources"]:
        assert source.get("identifier"), source["id"]


def test_a_band_naming_another_bodys_lower_edge_cites_a_source_it_lists():
    for concept_id, entry in ANALYTES.items():
        for band in entry.get("bands") or []:
            if band.get("lower_source_id"):
                assert band["lower"] is not None, (concept_id, band["label"])
                assert band["lower_source_id"] in (entry.get("source_ids") or []), (concept_id, band["lower_source_id"])
                assert band["lower_source_id"] != band.get("source_id"), (concept_id, band["label"])
