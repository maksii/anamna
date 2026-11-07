import json
from datetime import date
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts
from anamna.reference import (
    UNIT_CONVERSIONS,
    band_geometry,
    canonical_unit,
    convert_value,
    evaluate,
    staleness,
)


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def _rule(conn, concept_id, **overrides):
    fields = {
        "id": overrides.pop("id", f"test-rule-{concept_id}-{len(overrides)}"),
        "reference_set_id": "abim-2026",
        "concept_id": concept_id,
        "label": "Test band",
        "context_json": "{}",
        "unit": None,
        "lower_bound": None,
        "upper_bound": None,
        "lower_inclusive": 1,
        "upper_inclusive": 1,
        "interpretation": "normal",
        "priority": 10,
        "notes": None,
        "sex": None,
        "age_min_years": None,
        "age_max_years": None,
    }
    fields.update(overrides)
    columns = ",".join(fields)
    placeholders = ",".join("?" for _ in fields)
    conn.execute(
        f"INSERT OR REPLACE INTO curated_reference_rules({columns}) VALUES ({placeholders})",
        list(fields.values()),
    )


# --- units -----------------------------------------------------------------


def test_canonical_unit_folds_case_spacing_and_cyrillic():
    assert canonical_unit("mmol/L") == canonical_unit(" ммоль/л ") == "mmol/l"
    assert canonical_unit("µmol/L") == canonical_unit("мкмоль/л") == "umol/l"
    assert canonical_unit(None) == ""


@pytest.mark.parametrize(
    "concept_id, value, source, target, expected",
    [
        # 5.6 mmol/L is the ADA impaired-fasting-glucose threshold, 100 mg/dL.
        ("blood-glucose", 5.6, "mmol/L", "mg/dL", 100.90),
        ("blood-glucose", 100.0, "mg/dL", "mmol/L", 5.5499),
        # 5 mmol/L total cholesterol is 193 mg/dL.
        ("total-cholesterol", 5.0, "mmol/L", "mg/dL", 193.35),
        ("ldl-cholesterol", 3.0, "mmol/L", "mg/dL", 116.01),
        ("hdl-cholesterol", 1.0, "mmol/L", "mg/dL", 38.67),
        ("vldl-cholesterol", 1.0, "mmol/L", "mg/dL", 38.67),
        # 1.7 mmol/L triglycerides is the familiar 150 mg/dL cut-point.
        ("triglycerides", 1.7, "mmol/L", "mg/dL", 150.569),
        ("triglycerides", 150.0, "mg/dL", "mmol/L", 1.6936),
        # 30 ng/mL 25-OH vitamin D is 75 nmol/L.
        ("25-hydroxyvitamin-d", 30.0, "ng/mL", "nmol/L", 74.88),
        ("25-hydroxyvitamin-d", 75.0, "nmol/L", "ng/mL", 30.048),
        # 400 pg/mL B12 is 295 pmol/L.
        ("vitamin-b12", 400.0, "pg/mL", "pmol/L", 295.12),
        ("vitamin-b12", 295.0, "pmol/L", "pg/mL", 399.837),
        # Urobilinogen: the Multistix «+» tier, 1 mg/dL, is Expert's 17 µmol/L.
        ("urine-urobilinogen", 1.0, "mg/dL", "µmol/L", 16.9),
        ("urine-urobilinogen", 35.0, "мкмоль/л", "mg/dL", 2.0710),
    ],
)
def test_every_registered_conversion_has_a_worked_example(
    concept_id, value, source, target, expected
):
    assert convert_value(value, source, target, concept_id) == pytest.approx(expected, rel=1e-4)


def test_every_registered_conversion_round_trips():
    for (concept_id, source, target), factor in UNIT_CONVERSIONS.items():
        back = UNIT_CONVERSIONS.get((concept_id, target, source))
        assert back is not None, f"{concept_id} {source}->{target} has no inverse"
        assert factor * back == pytest.approx(1.0)
        forward = convert_value(10.0, source, target, concept_id)
        assert convert_value(forward, target, source, concept_id) == pytest.approx(10.0)


def test_unregistered_conversion_is_refused_not_guessed():
    assert convert_value(5.6, "mmol/L", "mg/dL", "creatinine") is None
    assert convert_value(5.6, "mmol/L", "g/L", "blood-glucose") is None
    # Molar masses differ: the glucose factor must never leak into lipids.
    assert convert_value(5.0, "mmol/L", "mg/dL", "total-cholesterol") != pytest.approx(
        convert_value(5.0, "mmol/L", "mg/dL", "blood-glucose")
    )


def test_unit_mismatch_yields_unjudged_rather_than_a_cross_unit_comparison(connection):
    # The ADA A1c bands are in %, and no % <-> mmol/mol conversion is
    # registered, so the value must not be compared against them.
    verdict = evaluate(connection, "hemoglobin-a1c", value_numeric=39.0, unit="mmol/mol",
                       age_years=34, sex="male")
    assert verdict["interpretation"] == "unjudged"
    assert verdict["unjudged_reason"] == "unit_mismatch"
    assert verdict["authority"] == "none"
    # The same result in the unit the guidance uses is judged.
    same = evaluate(connection, "hemoglobin-a1c", value_numeric=5.24, unit="%",
                    age_years=34, sex="male")
    assert same["authority"] == "curated"


def test_micro_sign_spellings_are_one_unit():
    assert (
        canonical_unit("umol/L")
        == canonical_unit("\u00b5mol/L")
        == canonical_unit("\u03bcmol/L")
        == canonical_unit("\u041c\u041a\u041c\u041e\u041b\u042c/\u041b")
        == "umol/l"
    )
    assert canonical_unit("cells/\u00b5L") == canonical_unit("cells/uL") == "cells/ul"
    assert canonical_unit(" MMOL/L\u00a0") == canonical_unit("mmol/l") == "mmol/l"


def test_micro_sign_concepts_still_resolve_to_a_curated_verdict(connection):
    # The library writes umol/L; the database writes the U+00B5 micro sign.
    # Comparing them as raw strings is how creatinine loses its verdict.
    for concept_id, value in (("uric-acid", 420.6),):
        verdict = evaluate(
            connection, concept_id, value_numeric=value, unit="\u00b5mol/L",
            age_years=34, sex="male",
        )
        assert verdict["authority"] == "curated", concept_id
        assert verdict["unjudged_reason"] is None, concept_id

    # Analytes whose only interval came from a test-prep table are now
    # correctly no_universal_target. The unit must still never be the reason
    # they go unjudged.
    for concept_id, value in (
        ("creatinine", 84.37),
        ("total-bilirubin", 16.0),
        ("direct-bilirubin", 3.55),
        ("serum-iron", 20.5),
        ("homocysteine", 13.7),
    ):
        verdict = evaluate(
            connection, concept_id, value_numeric=value, unit="\u00b5mol/L",
            age_years=34, sex="male",
        )
        assert verdict["unjudged_reason"] != "unit_mismatch", concept_id


# --- precedence ------------------------------------------------------------


def test_curated_guidance_beats_the_vendor_printed_range(connection):
    verdict = evaluate(
        connection,
        "hemoglobin-a1c",
        value_numeric=6.0,
        unit="%",
        age_years=34,
        sex="male",
        vendor_low=4.8,
        vendor_high=5.9,
        vendor_interpretation="high",
    )
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "borderline_high"
    assert "prediabetes" in verdict["band_label"].casefold()
    assert verdict["source_url"].startswith("https://")
    # ADA prints "5.7-6.4%" for prediabetes and ">=6.5%" for diabetes because a
    # clinical chart reports A1C to one decimal. Transcribed literally those
    # bounds leave a hole, so 6.45 would match no band at all and the verdict
    # would carry one band's interpretation under another band's label. The
    # continuous restatement of the same guidance is [5.7, 6.5).
    assert (verdict["low"], verdict["high"]) == (5.7, 6.5)


def test_adjacent_bands_leave_no_unclassifiable_value(connection):
    """A value between two published bands must not fall through to nothing.

    Guideline tables are written for integers; device data is averaged and
    arrives with decimals. Every partition must therefore be contiguous.
    """
    for concept_id, unit, value in (
        ("hemoglobin-a1c", "%", 6.45),
        ("sleep_duration", "hours", 6.95),
        ("systolic_blood_pressure", "mmHg", 129.5),
        ("body_mass_index", "kg/m²", 24.95),
        ("ldl-cholesterol", "mmol/L", 3.35),
        ("lipoprotein-a", "nmol/L", 104.9),
        ("white-blood-cell-count", "10^9/L", 11.7),
    ):
        verdict = evaluate(
            connection, concept_id, value_numeric=value, unit=unit, age_years=34, sex="male"
        )
        assert verdict["authority"] == "curated", concept_id
        # It must land in a real band. Which band is a matter for the cited
        # guidance -- blood pressure legitimately reads differently under the
        # US and European systems -- but "no band at all" is always a bug.
        assert verdict["interpretation"] != "unjudged", concept_id
        assert verdict["band_label"], concept_id
        assert verdict["position"] is not None, concept_id


#: Analytes whose bodies publish independent thresholds with a deliberate gap
#: between them (a deficiency limit and an overload limit, a treatment target
#: and a flare threshold). A value there is legitimately unflagged.
_INDEPENDENT_THRESHOLDS = {"ferritin", "potassium", "uric-acid"}


def test_every_band_set_is_contiguous_for_every_person(connection):
    """Sweep the whole library: every edge, just either side of it, and the
    midpoint between edges, for both sexes and every cardiovascular risk
    category. A value must land in a band -- otherwise evaluate() reports one
    band's interpretation under a different band's label."""
    from anamna.reference import CV_RISK_CATEGORIES, RULE_CACHE, _contains

    rows = connection.execute(
        """SELECT concept_id, unit, lower_bound, upper_bound FROM curated_reference_rules
           WHERE lower_bound IS NOT NULL OR upper_bound IS NOT NULL"""
    ).fetchall()
    by_concept: dict[tuple[str, str], set[float]] = {}
    for row in rows:
        key = (row["concept_id"], row["unit"] or "")
        by_concept.setdefault(key, set()).update(
            edge for edge in (row["lower_bound"], row["upper_bound"]) if edge is not None
        )
    holes = []
    token = RULE_CACHE.set({})
    try:
        for (concept_id, unit), edges in sorted(by_concept.items()):
            if concept_id in _INDEPENDENT_THRESHOLDS:
                continue
            ordered = sorted(edges)
            points = set(ordered)
            for low, high in zip(ordered, ordered[1:]):
                points |= {(low + high) / 2, low + (high - low) * 1e-3, high - (high - low) * 1e-3}
            for sex in ("male", "female"):
                for category in (None, *CV_RISK_CATEGORIES):
                    context = {"cv_risk_category": category} if category else None
                    for value in sorted(points):
                        verdict = evaluate(
                            connection, concept_id, value_numeric=value, unit=unit,
                            age_years=40, sex=sex, clinical_context=context,
                        )
                        if verdict["authority"] != "curated":
                            continue  # nothing applies to this person at all
                        if not _contains(
                            value, verdict["low"], verdict["high"],
                            verdict["low_inclusive"], verdict["high_inclusive"],
                        ):
                            holes.append((concept_id, sex, category, value))
    finally:
        RULE_CACHE.reset(token)
    assert not holes, holes[:20]


def test_fasting_glucose_follows_the_guidance_the_page_itself_cites(connection):
    # The laboratory prints 3.89-5.82 and calls 5.61 normal; the ADA standard
    # cited on the same page puts it in the prediabetes band.  The verdict must
    # not contradict the source shown beside it.
    verdict = evaluate(
        connection,
        "blood-glucose",
        value_numeric=5.61,
        unit="mmol/L",
        age_years=34,
        sex="male",
        vendor_low=3.89,
        vendor_high=5.82,
        vendor_interpretation="within_vendor_range",
    )
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "borderline_high"
    # Assert the meaning, not the wording: band labels name their authority now
    # ("Prediabetes range (ADA / Ukraine)") and will keep evolving as sources
    # are re-cited.
    assert "prediabetes" in verdict["band_label"].casefold()


def test_disagreeing_authorities_are_all_reported(connection):
    """Every published position travels with the verdict.

    Fasting glucose is the clearest case in the record: 5.61 mmol/L is
    prediabetes to the ADA and to Ukraine's MOZ protocol, high-risk to NICE and
    normal to the WHO. Collapsing that to one answer would hide a real clinical
    disagreement from the reader.
    """
    verdict = evaluate(
        connection, "blood-glucose", value_numeric=5.61, unit="mmol/L",
        age_years=34, sex="male",
    )
    positions = verdict["authority_positions"]
    assert len(positions) >= 2, positions
    assert verdict["authorities_disagree"] is True
    # Each position names a publisher and an interpretation of its own.
    assert all(item["publisher"] and item["interpretation"] for item in positions)
    interpretations = {item["interpretation"] for item in positions}
    assert len(interpretations) > 1, interpretations
    # The headline must take the cautious reading, never the reassuring one.
    assert verdict["interpretation"] != "normal"


def test_vendor_range_speaks_when_no_curated_rule_exists(connection):
    verdict = evaluate(
        connection,
        "quick-prothrombin-index",
        value_numeric=100.9,
        unit="%",
        vendor_low=70.0,
        vendor_high=140.0,
        vendor_interpretation="within_vendor_range",
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "normal"
    assert 0.0 <= verdict["position"] <= 1.0


def test_no_range_at_all_is_unjudged(connection):
    verdict = evaluate(connection, "not-a-real-concept", value_numeric=84.0, unit="g/L")
    assert verdict["interpretation"] == "unjudged"
    assert verdict["authority"] == "none"
    assert verdict["position"] is None
    assert verdict["unjudged_reason"] == "no_rule"


def test_no_universal_target_is_a_first_class_state(connection):
    # Mumps IgG has no published universal interval.  That is an answer, not a
    # gap: the laboratory's own printed range still governs.
    verdict = evaluate(
        connection, "mumps-virus-igg", value_numeric=4.7, unit="index",
        vendor_high=0.8, vendor_interpretation="positive",
    )
    assert verdict["no_universal_target"] is True
    assert verdict["authority"] == "vendor"


def test_a_positive_result_meaning_immunity_is_not_alarming(connection):
    immune = evaluate(
        connection, "mumps-virus-igg", value_numeric=4.7, unit="index",
        vendor_high=0.8, vendor_interpretation="positive",
    )
    assert immune["interpretation"] == "optimal"
    assert immune["positive_is_good"] is True
    # An analyte with ordinary polarity keeps the alarming reading.
    acute = evaluate(
        connection, "mumps-virus-igm", value_numeric=2.0, unit="index",
        vendor_high=0.8, vendor_interpretation="positive",
    )
    assert acute["interpretation"] == "positive"


def test_fixed_attributes_cannot_produce_a_verdict(connection):
    for concept_id in ("blood-group", "rhesus-factor", "hla-b27", "body_height"):
        verdict = evaluate(connection, concept_id, value_text="A(II)")
        assert verdict["interpretation"] == "not_a_measurement", concept_id
        assert verdict["position"] is None


def test_a_rule_needing_an_unknown_clinical_input_is_skipped(connection):
    _rule(connection, "ldl-cholesterol", id="risk-gated", unit="mmol/L",
          upper_bound=1.4, interpretation="optimal", priority=999,
          context_json=json.dumps({"requires": "cardiovascular_risk"}))
    verdict = evaluate(
        connection, "ldl-cholesterol", value_numeric=4.42, unit="mmol/L",
        age_years=34, sex="male",
    )
    # The risk-gated rule needs a clinical input the record does not hold, so
    # it must not be the band that speaks. Any other cited band may.
    assert verdict["band_label"] != "Test band"
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "high"


def test_ldl_above_every_published_goal_is_flagged(connection):
    # 4.42 exceeds even the most lenient ESC/EAS goal, so the flag holds
    # whatever cardiovascular risk category the patient turns out to be in.
    verdict = evaluate(
        connection, "ldl-cholesterol", value_numeric=4.42, unit="mmol/L",
        age_years=34, sex="male",
    )
    assert verdict["interpretation"] == "high"
    assert verdict["authority"] == "curated"


def test_an_allergen_result_resolves_to_its_cap_class(connection):
    connection.execute(
        "INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)"
        " VALUES ('bet-v-1', 'Bet v 1 PR-10', 'allergy', 'numeric', '2026-01-01')"
    )
    from anamna.reference import seed_reference_library

    seed_reference_library(connection)
    verdict = evaluate(
        connection, "bet-v-1", value_numeric=0.5, unit="kUA/L", age_years=34, sex="male"
    )
    # Class 1 (0.35-0.7) is narrower than the manufacturer cut-off band that
    # also contains 0.5, so selection must be deterministic.
    assert verdict["band_label"] == "Class 1 - low"
    assert verdict["interpretation"] == "positive"
    assert evaluate(
        connection, "bet-v-1", value_numeric=0.1, unit="kUA/L", age_years=34, sex="male"
    )["interpretation"] == "negative"


def test_an_abnormal_band_is_not_masked_by_an_overlapping_normal_band(connection):
    # WHO reports "no anaemia" for anything at or above 130 g/L; the ABIM
    # laboratory interval calls anything above 180 high.  Both contain 185.
    verdict = evaluate(
        connection, "hemoglobin", value_numeric=185.0, unit="g/L", age_years=34, sex="male"
    )
    assert verdict["interpretation"] == "high"
    assert evaluate(
        connection, "hemoglobin", value_numeric=146.0, unit="g/L", age_years=34, sex="male"
    )["interpretation"] == "normal"


def test_a_text_result_is_never_compared_against_a_numeric_band(connection):
    # urine-bilirubin carries a umol/L unit in the library but is reported as
    # text.  It must go through the qualitative path.
    verdict = evaluate(connection, "urine-bilirubin", value_text="\u043d\u0435 \u0432\u0438\u044f\u0432\u043b\u0435\u043d\u043e",
                       age_years=34, sex="male")
    assert verdict["interpretation"] == "negative"
    assert verdict["authority"] == "curated"
    assert verdict["position"] is None


# --- demographics ----------------------------------------------------------


def test_sex_and_age_filtering(connection):
    connection.execute("DELETE FROM curated_reference_rules WHERE concept_id='ferritin'")
    _rule(connection, "ferritin", id="male-band", unit="ng/mL", lower_bound=30.0,
          upper_bound=400.0, sex="male", age_min_years=18.0, interpretation="normal",
          priority=20)
    _rule(connection, "ferritin", id="female-band", unit="ng/mL", lower_bound=13.0,
          upper_bound=150.0, sex="female", age_min_years=18.0, interpretation="normal",
          priority=20)
    _rule(connection, "ferritin", id="child-band", unit="ng/mL", lower_bound=7.0,
          upper_bound=140.0, age_max_years=18.0, interpretation="normal", priority=30)

    male = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL",
                    age_years=34, sex="male")
    assert male["interpretation"] == "normal"
    assert (male["low"], male["high"]) == (30.0, 400.0)

    female = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL",
                      age_years=34, sex="female")
    assert female["interpretation"] == "high"
    assert (female["low"], female["high"]) == (13.0, 150.0)

    child = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL",
                     age_years=12, sex="male")
    assert child["band_label"] == "Test band"
    assert (child["low"], child["high"]) == (7.0, 140.0)


def test_unknown_sex_does_not_guess_a_sexed_rule(connection):
    connection.execute("DELETE FROM curated_reference_rules WHERE concept_id='ferritin'")
    _rule(connection, "ferritin", id="male-only", unit="ng/mL", lower_bound=30.0,
          upper_bound=400.0, sex="male", interpretation="normal")
    for unknown in (None, "", "unknown"):
        verdict = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL",
                           age_years=34, sex=unknown)
        assert verdict["interpretation"] == "unjudged"
        assert verdict["unjudged_reason"] == "sex_unknown"
        assert verdict["curated_blocked"] == "sex_unknown"


def test_unknown_age_does_not_guess_an_age_scoped_rule(connection):
    connection.execute("DELETE FROM curated_reference_rules WHERE concept_id='ferritin'")
    _rule(connection, "ferritin", id="adult-only", unit="ng/mL", lower_bound=30.0,
          upper_bound=400.0, age_min_years=18.0, interpretation="normal")
    verdict = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL")
    assert verdict["unjudged_reason"] == "age_unknown"


def test_gated_ferritin_inflammation_band_does_not_judge_a_healthy_adult(connection):
    """WHO's ≤70 inflammation band must never call a healthy ferritin low.

    The band is real guidance -- for a patient known to be inflamed -- but this
    record holds no inflammation status, so it is blocked, and the sexed
    normal bands speak instead.  Unconditional, it reported every healthy
    ferritin between 30 and 70 as "low", both sexes.
    """
    for sex, band in (("male", "Iron stores not depleted (men)"),
                      ("female", "Iron stores not depleted (women)")):
        verdict = evaluate(connection, "ferritin", value_numeric=50.0, unit="ng/mL",
                           age_years=34, sex=sex)
        assert verdict["interpretation"] == "normal", sex
        assert verdict["band_label"] == band
        # The gate stays visible: the page can say a more specific
        # inflammation-gated interval exists.
        assert verdict["curated_blocked"] == "requires_clinical_context"
    # The genuinely high reading is still flagged.
    high = evaluate(connection, "ferritin", value_numeric=202.0, unit="ng/mL",
                    age_years=34, sex="male")
    assert high["interpretation"] == "high"


def test_ferritin_female_overload_band_states_whose_threshold_it_applies(connection):
    # WHO's 150 µg/L figure is for menstruating women; the record does not know
    # menstrual status, so the stricter threshold applies to every female
    # profile -- and the band must say so rather than mislabel a 60-year-old.
    verdict = evaluate(connection, "ferritin", value_numeric=170.0, unit="ng/mL",
                       age_years=60, sex="female")
    assert verdict["interpretation"] == "high"
    assert "applied to all female profiles" in verdict["band_label"]
    assert "200" in verdict["note"]


def test_matched_band_cites_its_own_publisher_not_the_top_candidates(connection):
    # Female HDL 1.11 mmol/L is judged by the МОЗ 564 female band, which beats
    # the higher-priority EAS/EFLM "Not low" band on abnormality. The citation
    # must follow the band that spoke: built from candidates[0] it presented a
    # МОЗ України band as an EAS/EFLM claim.
    verdict = evaluate(connection, "hdl-cholesterol", value_numeric=1.11,
                       unit="mmol/L", age_years=34, sex="female")
    assert verdict["interpretation"] == "low"
    assert verdict["band_label"] == "Low (Ukrainian protocol, women)"
    assert verdict["source_id"] == "moz-564-2016"
    assert "МОЗ" in verdict["source_name"]
    # The same value is fine for a man under every cited body.
    male = evaluate(connection, "hdl-cholesterol", value_numeric=1.11,
                    unit="mmol/L", age_years=34, sex="male")
    assert male["interpretation"] == "normal"
    assert male["source_id"] == "eas-eflm-2016"


def test_a_skipped_sexed_rule_stays_visible_on_a_successful_verdict(connection):
    """ALT 30 U/L with unknown sex: the unisex ≤40 band judges "normal", but
    the skipped ACG female cut (25) would say "high" -- the dilution must not
    be silent."""
    verdict = evaluate(connection, "alanine-aminotransferase", value_numeric=30.0,
                       unit="U/L", age_years=34, sex=None)
    assert verdict["interpretation"] == "normal"
    assert verdict["authority"] == "curated"
    assert verdict["curated_blocked"] == "sex_unknown"
    # With the sex recorded the more specific rule speaks and nothing is
    # withheld.
    female = evaluate(connection, "alanine-aminotransferase", value_numeric=30.0,
                      unit="U/L", age_years=34, sex="female")
    assert female["interpretation"] == "high"
    assert female["curated_blocked"] is None


def test_intersex_on_an_all_sexed_concept_reads_sex_not_covered(connection):
    # Every haemoglobin band is sexed. For an intersex profile that must read
    # as "the published guidance does not cover this sex", never as "nothing
    # is published" -- 12 rules exist.
    verdict = evaluate(connection, "hemoglobin", value_numeric=140.0, unit="g/L",
                       age_years=34, sex="intersex")
    assert verdict["interpretation"] == "unjudged"
    assert verdict["unjudged_reason"] == "sex_not_covered"
    assert verdict["curated_blocked"] == "sex_not_covered"
    # Unknown sex keeps its own, different reason: recording it would fix it.
    unknown = evaluate(connection, "hemoglobin", value_numeric=140.0, unit="g/L",
                       age_years=34, sex="unknown")
    assert unknown["unjudged_reason"] == "sex_unknown"


def test_intersex_still_gets_unisex_guidance_where_it_exists(connection):
    # Sexed-rule skips are ordinary when a unisex band still matches; an
    # intersex reader must get the EASL ULN verdict without a block notice.
    verdict = evaluate(connection, "alanine-aminotransferase", value_numeric=30.0,
                       unit="U/L", age_years=34, sex="intersex")
    assert verdict["interpretation"] == "normal"
    assert verdict["authority"] == "curated"
    assert verdict["curated_blocked"] is None


def test_vo2_max_is_judged_for_every_friend_decade(connection):
    """FRIEND publishes decade tables for 20-79; age 39 must not fall out of
    its own "30-39" band (the matcher excludes at age_max, so windows are
    written 30 -> 40)."""
    for sex in ("male", "female"):
        for age in (20, 29.9, 34, 39.9, 45, 55, 65, 79.9):
            verdict = evaluate(connection, "vo2_max", value_numeric=30.0,
                               unit="mL/kg/min", age_years=age, sex=sex)
            assert verdict["authority"] == "curated", (sex, age)
            assert verdict["interpretation"] != "unjudged", (sex, age)
    # Spot values traced to the FRIEND columns of Rossi Neto 2019, Table 2
    # (doi:10.1371/journal.pone.0209897), which reproduces Kaminsky 2015.
    at_39 = evaluate(connection, "vo2_max", value_numeric=45.0,
                     unit="mL/kg/min", age_years=39, sex="male")
    assert at_39["band_label"] == "50th to 75th percentile (male, age 30-39)"
    at_45 = evaluate(connection, "vo2_max", value_numeric=45.0,
                     unit="mL/kg/min", age_years=45, sex="male")
    assert at_45["band_label"] == "75th to 90th percentile (male, age 40-49)"


def test_urine_bilirubin_strip_tier_in_micromoles_is_abnormal(connection):
    # Expert Hospital's «+» tier prints as 17 µmol/L. While the rule sat on a
    # learned duplicate concept this real abnormal reading was never judged.
    verdict = evaluate(connection, "urine-bilirubin", value_numeric=17.0,
                       unit="мкмоль/л", age_years=34, sex="male")
    assert verdict["interpretation"] == "high"
    assert verdict["authority"] == "curated"


def test_urobilinogen_micromolar_reading_is_not_a_unit_mismatch(connection):
    # 35 µmol/L now converts into the library's mg/dL world; the qualitative
    # dipstick band still must not swallow the numeric value.
    verdict = evaluate(connection, "urine-urobilinogen", value_numeric=35.0,
                       unit="мкмоль/л", age_years=34, sex="male")
    assert verdict["unjudged_reason"] != "unit_mismatch"


# --- qualitative -----------------------------------------------------------


def test_expected_value_comparison_judges_text_results(connection):
    _rule(
        connection,
        "hiv-i-ii-rapid-test",
        id="expected-negative",
        context_json=json.dumps({"expected_text": ["negative", "не виявлено"]}),
        interpretation="negative",
        label="Expected result",
        priority=20,
    )
    _rule(
        connection,
        "hiv-i-ii-rapid-test",
        id="expected-positive",
        context_json=json.dumps({"expected_text": ["positive", "виявлено"]}),
        interpretation="positive",
        label="Reactive",
        priority=10,
    )
    negative = evaluate(connection, "hiv-i-ii-rapid-test", value_text="Негативний")
    assert negative["interpretation"] == "negative"
    assert negative["authority"] == "curated"
    assert negative["position"] is None

    detected = evaluate(connection, "hiv-i-ii-rapid-test", value_text="Positive")
    assert detected["interpretation"] == "positive"

    unexpected = evaluate(connection, "hiv-i-ii-rapid-test", value_text="сумнівний")
    assert unexpected["interpretation"] == "indeterminate"


# --- geometry --------------------------------------------------------------


def test_two_sided_band_sits_inside_the_track():
    geometry = band_geometry(5.0, 4.0, 6.0)
    assert geometry["band_start"] == pytest.approx(0.2)
    assert geometry["band_end"] == pytest.approx(0.8)
    assert geometry["position"] == pytest.approx(0.5)
    assert geometry["out_of_range_side"] is None
    # Band edges land in the same place whatever the numbers, so bars on one
    # page stay visually comparable.
    wide = band_geometry(150.0, 100.0, 400.0)
    assert wide["band_start"] == pytest.approx(0.2)
    assert wide["band_end"] == pytest.approx(0.8)


def test_open_ended_bands_get_a_sensible_display_domain():
    upper_only = band_geometry(2.0, None, 4.0)
    assert upper_only["band_start"] == pytest.approx(0.0)
    assert upper_only["band_end"] == pytest.approx(0.8)
    assert upper_only["position"] == pytest.approx(0.4)

    lower_only = band_geometry(1.4, 1.2, None)
    assert lower_only["band_start"] == pytest.approx(0.2)
    assert lower_only["band_end"] == pytest.approx(1.0)
    assert 0.2 < lower_only["position"] < 1.0

    assert band_geometry(1.0, None, None)["position"] is None


def test_far_out_of_range_markers_are_clamped_but_still_flagged():
    geometry = band_geometry(40.0, None, 4.0)
    assert geometry["position"] == 1.0
    assert geometry["out_of_range_side"] == "high"

    low = band_geometry(-100.0, 4.0, 6.0)
    assert low["position"] == 0.0
    assert low["out_of_range_side"] == "low"


def test_exclusive_bounds_count_as_out_of_range():
    assert band_geometry(6.0, None, 6.0, high_inclusive=False)["out_of_range_side"] == "high"
    assert band_geometry(6.0, None, 6.0, high_inclusive=True)["out_of_range_side"] is None


# --- staleness -------------------------------------------------------------


def test_staleness_states_at_their_boundaries():
    today = date(2026, 8, 3)
    assert staleness(None, 12, today=today)["state"] == "never"
    # No published screening cadence is its own state, not "fresh".
    no_interval = staleness("2024-01-01", None, today=today)
    assert no_interval["state"] == "no_interval"
    assert no_interval["days_ago"] == 945
    assert no_interval["due_on"] is None

    # Due 12 months after the test; 61 days out is still fresh, 60 is due soon.
    assert staleness("2025-10-03", 12, today=today)["state"] == "fresh"
    assert staleness("2025-10-02", 12, today=today)["state"] == "due_soon"
    assert staleness("2025-08-03", 12, today=today)["state"] == "due_soon"
    assert staleness("2025-08-02", 12, today=today)["state"] == "overdue"

    overdue = staleness("2024-08-03", 12, today=today)
    assert overdue["state"] == "overdue"
    assert overdue["days_ago"] == 730
    assert overdue["due_on"] == "2025-08-03"
    assert overdue["interval_months"] == 12


def test_staleness_handles_month_end_and_timestamps():
    assert staleness("2025-01-31", 1, today=date(2025, 2, 28))["due_on"] == "2025-02-28"
    assert staleness("2025-11-05T08:00:00", 12, today=date(2026, 8, 3))["days_ago"] == 271


# --- conflicting authorities ------------------------------------------------


def test_a_curated_normal_never_covers_a_range_the_laboratory_called_low(connection):
    """Folate 3.06 ng/mL must never read as normal.

    It used to, because the only curated interval came from a test-prep table
    (1.8-9.0). WHO puts 3-5.9 ng/mL in "possible deficiency" and EFSA's
    functional adequacy threshold is 4.4, so the patient's own laboratory --
    which printed 3.89-26.8 and called it low -- was right and the library was
    wrong. With the official sources cited the two now agree, which is why
    there is no longer a conflict to report.
    """
    verdict = evaluate(
        connection,
        "folate-serum",
        value_numeric=3.06,
        unit="ng/mL",
        age_years=34,
        sex="male",
        vendor_low=3.89,
        vendor_high=26.8,
        vendor_interpretation="low",
    )
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] not in {"normal", "optimal", "negative"}
    # Agreeing sources must not raise a false alarm about disagreeing.
    assert verdict["conflicts_with_vendor"] is False
    assert verdict["vendor_range_text"] == "3.89-26.8 ng/mL"
    assert verdict["band_label"]


def test_agreeing_authorities_do_not_raise_a_conflict(connection):
    verdict = evaluate(
        connection,
        "hemoglobin",
        value_numeric=146.0,
        unit="g/L",
        age_years=34,
        sex="male",
        vendor_low=130.0,
        vendor_high=160.0,
        vendor_interpretation="within_vendor_range",
    )
    assert verdict["conflicts_with_vendor"] is False
    assert verdict["interpretation"] == "normal"


def test_sex_specific_bands_with_shared_labels_are_not_collapsed(connection):
    """Two bands differing only by sex must survive as two rows.

    WHO writes "Severe anaemia" for men and for women alike. While the rule id
    hashed only (source, concept, label), the second insert overwrote the first
    and haemoglobin lost its entire male reference interval -- a healthy 146 g/L
    then reported as high, because it matched no male band at all.
    """
    rows = connection.execute(
        """SELECT sex, COUNT(*) n FROM curated_reference_rules
           WHERE concept_id='hemoglobin' GROUP BY sex"""
    ).fetchall()
    by_sex = {row["sex"]: row["n"] for row in rows}
    assert by_sex.get("male", 0) >= 4, by_sex
    assert by_sex.get("female", 0) >= 4, by_sex

    for value, expected in ((146.0, "normal"), (185.0, "high"), (75.0, "critical_low")):
        verdict = evaluate(
            connection, "hemoglobin", value_numeric=value, unit="g/L",
            age_years=34, sex="male",
        )
        assert verdict["interpretation"] == expected, (value, verdict["interpretation"])
        assert verdict["authority"] == "curated"


def test_every_official_source_is_https_and_attributed(connection):
    """A citation the reader cannot open is not a citation."""
    for row in connection.execute(
        "SELECT id, name, publisher, source_url FROM reference_sets"
    ):
        assert row["source_url"].startswith("https://"), row["id"]
        assert row["publisher"], row["id"]
        assert row["name"], row["id"]


def test_cyrillic_giga_per_litre_is_not_folded_onto_grams_per_litre():
    """«Г/л» is 10^9/L; «г/л» is g/L. One letter of case, a factor of 10^9.

    MOZ protocols print both (Наказ 1581/2024, Наказ 49/2021). The unit table
    is looked up casefolded, which collapsed them onto "g/l" -- so a platelet
    or leukocyte count in Г/л would have been judged against a haemoglobin
    interval, the same silent-wrong-verdict class as the µ/мк folding above.
    """
    assert canonical_unit("г/л") == "g/l"
    assert canonical_unit("Г/л") == "10^9/l"
    assert canonical_unit("Г/Л") == "10^9/l"
    assert canonical_unit("г/л") != canonical_unit("Г/л")
    # Г/л must land on the same key the other 10^9/L spellings already use.
    assert canonical_unit("Г/л") == canonical_unit("10^9/L") == canonical_unit("×10⁹/л")


def test_reseeding_does_not_wipe_a_name_the_library_cannot_express(connection):
    """`name_uk` must survive an app start; the prose columns must not linger.

    The 295 allergens are seeded from one shared `_allergen_specific_ige`
    template with no per-concept name slot, so `uk.get("name")` is always None
    for them. An unconditional `name_uk=excluded.name_uk` therefore nulled all
    295 rows on every single app start -- data destroyed by a routine boot.
    The prose columns stay library-authoritative on purpose: clearing a
    translation in the JSON has to clear it in the database too.
    """
    from anamna.reference import seed_reference_library

    seed_reference_library(connection)
    # Pick a concept the library itself leaves unnamed -- that is exactly the
    # case the allergens are in, and the only case where COALESCE decides.
    target = connection.execute(
        "SELECT concept_id FROM concept_guidance "
        "WHERE name_uk IS NULL OR TRIM(name_uk)='' "
        "ORDER BY concept_id LIMIT 1"
    ).fetchone()
    assert target, "expected at least one concept the library does not name"
    concept_id = target["concept_id"]

    connection.execute(
        "UPDATE concept_guidance SET name_uk=?, short_description_uk=? WHERE concept_id=?",
        ("Назва поза бібліотекою", "Проза поза бібліотекою", concept_id),
    )
    seed_reference_library(connection)
    row = connection.execute(
        "SELECT name_uk, short_description_uk FROM concept_guidance WHERE concept_id=?",
        (concept_id,),
    ).fetchone()

    assert row["name_uk"] == "Назва поза бібліотекою"
    assert row["short_description_uk"] != "Проза поза бібліотекою"
