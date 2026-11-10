import json
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts
from anamna.reference import (
    _GATE_APPLIES,
    _RULE_SKIP,
    _band_context,
    _condition_met,
    _gate_rule,
    convert_value,
    evaluate,
    rule_applies_to_context,
)


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def _insert_band(conn, set_id, rule_id, low, high, interpretation, context, *, upper_inclusive=True):
    conn.execute(
        """INSERT INTO curated_reference_rules
           (id, reference_set_id, concept_id, label, context_json, unit, lower_bound, upper_bound,
            lower_inclusive, upper_inclusive, interpretation, priority, notes, sex,
            age_min_years, age_max_years)
           VALUES (?, ?, 'blood-glucose', ?, ?, 'mmol/L', ?, ?, 1, ?, ?, 10,
                   NULL, NULL, NULL, NULL)""",
        (rule_id, set_id, f"Band {rule_id}", json.dumps(context), low, high,
         int(upper_inclusive), interpretation),
    )


def _glucose_fasting_and_random_bands(conn):
    # seed_concepts loads the whole library into this temp database, so clear
    # this concept's published bands and judge against the test's own alone.
    conn.execute("DELETE FROM curated_reference_rules WHERE concept_id = 'blood-glucose'")
    set_id = conn.execute("SELECT id FROM reference_sets ORDER BY id LIMIT 1").fetchone()[0]
    # Fasting-only bands exclude a random sample; the random band requires one.
    _insert_band(conn, set_id, "glucose-normal", 3.9, 5.6, "normal",
                 {"excludes": ["not_fasting_sample"]}, upper_inclusive=False)
    _insert_band(conn, set_id, "glucose-fasting-high", 7.0, None, "high",
                 {"excludes": ["not_fasting_sample"]})
    _insert_band(conn, set_id, "glucose-random-high", 11.1, None, "high",
                 {"requires": ["not_fasting_sample"]})


# --- band gating -----------------------------------------------------------


def test_an_excluded_fact_switches_the_band_off():
    assert _gate_rule({"excludes": ["pregnant"]}, {}) is None
    assert _gate_rule({"excludes": ["pregnant"]}, {"pregnant": True}) == "excluded_pregnant"


def test_a_random_sample_rule_is_silently_skipped_when_fasting_is_unknown():
    assert _gate_rule({"requires": ["not_fasting_sample"]}, {}) == _RULE_SKIP
    assert (
        _gate_rule({"requires": ["not_fasting_sample"]}, {"not_fasting_sample": True})
        == _GATE_APPLIES
    )


def test_other_missing_clinical_facts_still_say_what_is_missing():
    assert _gate_rule({"requires": ["cv_risk_category"]}, {}) == "requires_cv_risk_category"
    assert _gate_rule({"requires": ["some_other_fact"]}, {}) == "requires_clinical_context"


def test_a_planning_pregnancy_indicator_is_skipped_silently():
    assert _gate_rule({"requires": ["planning_pregnancy"]}, {}) == _RULE_SKIP
    assert (
        _gate_rule({"requires": ["planning_pregnancy"]}, {"planning_pregnancy": True})
        == _GATE_APPLIES
    )


def test_a_band_applies_to_a_person_exactly_when_the_gate_lets_it_judge():
    def band(context):
        return {"context_json": json.dumps(context)}

    goal = band({"requires": ["cv_risk_category"], "cv_risk_category": "high"})
    assert rule_applies_to_context(band({}), {}) is True
    assert rule_applies_to_context(goal, {"cv_risk_category": "high"}) is True
    assert rule_applies_to_context(goal, {}) is False
    assert rule_applies_to_context(goal, {"cv_risk_category": "low"}) is False
    # An excluded fact that is present switches the band off for this person.
    fasting = band({"excludes": ["not_fasting_sample"]})
    assert rule_applies_to_context(fasting, {}) is True
    assert rule_applies_to_context(fasting, {"not_fasting_sample": True}) is False
    # A random-sample band needs the fact to apply.
    random_sample = band({"requires": ["not_fasting_sample"]})
    assert rule_applies_to_context(random_sample, {}) is False
    assert rule_applies_to_context(random_sample, {"not_fasting_sample": True}) is True


def test_band_context_carries_exclusions():
    assert _band_context({}, {"excludes": ["pregnant"]})["excludes"] == ["pregnant"]


def test_evaluate_lets_a_fasting_band_step_aside_for_a_random_sample(connection):
    _glucose_fasting_and_random_bands(connection)

    fasting_normal = evaluate(connection, "blood-glucose", value_numeric=5.0, unit="mmol/L")
    assert fasting_normal["interpretation"] == "normal"
    assert fasting_normal["band_label"] == "Band glucose-normal"
    assert fasting_normal.get("curated_blocked") is None

    # The only band that contains 5.0 is excluded, so nothing judges it and the
    # block reason says why.
    random_mid = evaluate(
        connection, "blood-glucose", value_numeric=5.0, unit="mmol/L",
        clinical_context={"not_fasting_sample": True},
    )
    assert random_mid["interpretation"] == "unjudged"
    assert random_mid["curated_blocked"] == "excluded_not_fasting_sample"
    assert random_mid["unjudged_reason"] == "excluded_not_fasting_sample"

    # The random band judges a random sample; the excluded fasting band's
    # reason travels beside that verdict.
    random_high = evaluate(
        connection, "blood-glucose", value_numeric=12.0, unit="mmol/L",
        clinical_context={"not_fasting_sample": True},
    )
    assert random_high["interpretation"] == "high"
    assert random_high["band_label"] == "Band glucose-random-high"
    assert random_high["curated_blocked"] == "excluded_not_fasting_sample"

    # Without the fact the fasting band judges, and the random band stays silent.
    fasting_high = evaluate(connection, "blood-glucose", value_numeric=12.0, unit="mmol/L")
    assert fasting_high["interpretation"] == "high"
    assert fasting_high["band_label"] == "Band glucose-fasting-high"
    assert fasting_high.get("curated_blocked") is None


# --- retest cadence --------------------------------------------------------


def test_a_borderline_retest_is_due_only_for_a_borderline_result():
    cadence = {"applies_when": "borderline"}
    assert _condition_met(cadence, "borderline_high", 40) == (True, "")
    assert _condition_met(cadence, "high", 40) == (False, "borderline_only")
    assert _condition_met(cadence, "normal", 40) == (False, "borderline_only")


# --- unit conversions ------------------------------------------------------


@pytest.mark.parametrize(
    "value, source, target, concept_id, expected",
    [
        (1.0, "mg/dL", "µmol/L", "uric-acid", 59.48),
        (1.0, "mg/dL", "µmol/L", "creatinine", 88.4),
        (1.0, "mg/dL", "µmol/L", "total-bilirubin", 17.1),
        (1.0, "mg/dL", "µmol/L", "direct-bilirubin", 17.1),
        (1.0, "mg/dL", "µmol/L", "indirect-bilirubin", 17.1),
        (1.0, "mg/dL", "mmol/L", "magnesium", 0.4114),
        (1.0, "mmol/L", "mg/dL", "non-hdl-cholesterol", 38.67),
        (14.0, "g/dL", "g/L", "hemoglobin", 140.0),
        (4.0, "g/dL", "g/L", "albumin", 40.0),
        (7.0, "g/dL", "g/L", "total-protein", 70.0),
        (5.0, "µg/L", "ng/mL", "ferritin", 5.0),
        (140.0, "мекв/л", "mmol/L", "sodium", 140.0),
        (4.0, "mEq/L", "mmol/L", "potassium", 4.0),
    ],
)
def test_added_conversions_hold_in_both_directions(value, source, target, concept_id, expected):
    assert convert_value(value, source, target, concept_id) == pytest.approx(expected, rel=1e-4)
    assert convert_value(expected, target, source, concept_id) == pytest.approx(value, rel=1e-4)


def test_a_monovalent_ion_conversion_does_not_leak_to_mass_units():
    assert convert_value(1, "mg/dL", "mmol/L", "sodium") is None
