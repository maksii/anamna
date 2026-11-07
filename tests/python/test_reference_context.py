"""Clinical-context gating, target choice, conditional cadences and the other
reference-engine fixes from the 2026-11-06 sandbox audit (CLIN-01..33).

Each test names the finding it guards. Every one of them was a confident,
wrong verdict on a real record, not a cosmetic slip.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import seed_concepts
from anamna.reference import (
    BENIGN_INTERPRETATIONS,
    clinical_context,
    edge_safe_decimals,
    evaluate,
    range_text,
    staleness,
)

DERIVED_HIGH = {
    "cv_risk_category": "high",
    "cv_risk_basis": "derived",
    "cv_risk_at_least": True,
    "cv_risk_evidence": {
        "concept_id": "ldl-cholesterol", "value": 5.54, "threshold": 4.9,
        "inclusive": True, "date": "2026-08-04",
    },
}


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def _ldl(conn, value, context=None, **extra):
    return evaluate(
        conn, "ldl-cholesterol", value_numeric=value, unit="mmol/L", age_years=34,
        sex="male", clinical_context=context, **extra,
    )


# --- CLIN-01: risk-stratified goals ----------------------------------------


def test_ldl_goal_never_judges_without_a_risk_category(connection):
    verdict = _ldl(connection, 2.7)
    # 2.7 used to read "Optimal - goal at low CV risk" for a man whose record
    # held an LDL of 5.5: a goal applied with no risk category at all.
    assert "goal" not in str(verdict["band_label"]).casefold()
    assert verdict["curated_blocked"] == "requires_cv_risk_category"
    assert verdict["interpretation"] == "normal"  # EAS/EFLM population cut-point
    assert verdict["risk_note"] is None


def test_ldl_is_judged_against_the_goal_for_a_derived_high_risk(connection):
    verdict = _ldl(connection, 2.7, DERIVED_HIGH)
    assert verdict["interpretation"] == "high"
    assert "high cardiovascular risk" in verdict["band_label"]
    assert verdict["target_high"] == 1.8
    assert verdict["target_source_id"] == "esc-eas-2025"
    assert "4.9" in verdict["risk_note"] and "ESC/EAS" in verdict["risk_note"]
    assert "at least high" in verdict["risk_note"]
    # The Ukrainian protocol's looser 2.5 goal is its own position, not merged.
    publishers = {item["source_id"] for item in verdict["authority_positions"]}
    assert {"esc-eas-2025", "moz-564-2016"} <= publishers


def test_ldl_inside_the_goal_for_its_category_is_optimal(connection):
    verdict = _ldl(connection, 1.5, {"cv_risk_category": "high", "cv_risk_basis": "profile"})
    assert verdict["interpretation"] == "optimal"
    assert verdict["target_high"] == 1.8
    assert "profile" in verdict["risk_note"]


def test_non_hdl_and_apob_goals_are_gated_too(connection):
    for concept, unit, value in (("non-hdl-cholesterol", "mmol/L", 3.29), ("apolipoprotein-b", "g/L", 0.91)):
        plain = evaluate(connection, concept, value_numeric=value, unit=unit, age_years=34, sex="male")
        assert "goal" not in str(plain["band_label"]).casefold(), concept
        assert plain["curated_blocked"] == "requires_cv_risk_category", concept
        gated = evaluate(
            connection, concept, value_numeric=value, unit=unit, age_years=34, sex="male",
            clinical_context=DERIVED_HIGH,
        )
        assert gated["interpretation"] == "high", concept


def test_risk_category_is_derived_from_the_record_or_taken_from_the_profile(tmp_path):
    from test_web_panels import build

    settings, user_id, _client = build(tmp_path)
    with connect(settings) as conn:
        # LDL 4.42 in the fixture: below 4.9, so nothing may be derived.
        assert clinical_context(conn, user_id) == {}
        conn.execute("UPDATE observations SET value_numeric=5.1 WHERE id='obs-0'")
        derived = clinical_context(conn, user_id)
        assert derived["cv_risk_category"] == "high" and derived["cv_risk_at_least"] is True
        assert derived["cv_risk_evidence"]["concept_id"] == "ldl-cholesterol"
        # A rejected reading is not evidence.
        conn.execute("UPDATE observations SET verification_status='rejected' WHERE id='obs-0'")
        assert clinical_context(conn, user_id) == {}
        conn.execute("UPDATE patients SET cv_risk_category='very_high' WHERE owner_user_id=?", (user_id,))
        assert clinical_context(conn, user_id) == {"cv_risk_category": "very_high", "cv_risk_basis": "profile"}


def test_profile_sets_and_clears_the_risk_category(tmp_path):
    from fastapi.testclient import TestClient

    from anamna.security import create_user
    from anamna.web.app import create_app
    from test_web_profile import csrf_for, login
    from test_web_security import PASSWORD, seed_patient, settings_for

    settings = settings_for(tmp_path)
    migrate(settings)
    user = create_user(settings, "risk@example.test", "Risk", PASSWORD)
    seed_patient(settings, user, "Risk Patient")
    with TestClient(create_app(settings)) as client:
        login(client, "risk@example.test")
        page = client.get("/profile?tab=personal").text
        assert 'name="cv_risk_category"' in page
        csrf = csrf_for(settings, client)
        form = {"full_name": "Risk", "cv_risk_category": "very_high", "csrf_token": csrf}
        assert client.post("/profile", data=form, follow_redirects=False).headers["location"] == "/profile?saved=1"
        with connect(settings) as conn:
            assert clinical_context(conn, user)["cv_risk_category"] == "very_high"
        bad = client.post("/profile", data={**form, "cv_risk_category": "extreme"}, follow_redirects=False)
        assert bad.headers["location"] == "/profile?error=profile.error_choice"
        client.post("/profile", data={**form, "cv_risk_category": ""})
        with connect(settings) as conn:
            assert clinical_context(conn, user) == {}


def test_total_cholesterol_of_exactly_eight_does_not_derive_high_risk(tmp_path):
    from test_web_panels import build

    settings, user_id, _client = build(tmp_path)
    with connect(settings) as conn:
        concept = conn.execute("SELECT id FROM concepts WHERE id='total-cholesterol'").fetchone()
        assert concept is not None
        conn.execute(
            "UPDATE observations SET concept_id='total-cholesterol', value_numeric=8.0 WHERE id='obs-0'"
        )
        assert clinical_context(conn, user_id) == {}  # ESC/EAS: ">8 mmol/L"
        conn.execute("UPDATE observations SET value_numeric=8.1 WHERE id='obs-0'")
        assert clinical_context(conn, user_id)["cv_risk_category"] == "high"


def test_changes_no_longer_calls_a_high_risk_ldl_resolved(tmp_path):
    from test_web_panels import build
    from anamna.web import changes

    settings, user_id, client = build(tmp_path)
    with connect(settings) as conn:
        conn.execute("UPDATE observations SET value_numeric=5.49 WHERE id='obs-0'")
        conn.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               SELECT 'obs-ldl-new', owner_user_id, patient_id, document_id, 1, concept_id, raw_name,
                      'numeric', 2.7, unit_raw, '2026-11-05', 'extracted', 'test', 0.9, 'LDL', 'test', ?
               FROM observations WHERE id='obs-0'""",
            (utc_now(),),
        )
        result = changes.build_changes(conn, user_id)
    every = [
        entry for group in result["groups"]
        for entry in [*group["open"], *(e for _bucket, items in group["collapsed"] for e in items)]
    ]
    entries = [entry for entry in every if entry["concept_id"] == "ldl-cholesterol"]
    assert entries, "LDL missing from /changes"
    assert all(entry["bucket"] != "resolved" for entry in entries), entries


# --- CLIN-02 / DOCB-12: the shaded target ----------------------------------


def test_a_benign_verdict_is_never_outside_its_own_target(connection):
    cases = [
        ("hdl-cholesterol", "mmol/L", 1.27, None),
        ("ldl-cholesterol", "mmol/L", 2.7, None),
        ("non-hdl-cholesterol", "mmol/L", 3.29, None),
        ("high-sensitivity-c-reactive-protein", "mg/L", 0.85, None),
        ("25-hydroxyvitamin-d", "ng/mL", 32.1, None),
    ]
    connection.execute(
        "INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)"
        " VALUES ('high-sensitivity-c-reactive-protein', 'High-sensitivity C-reactive protein',"
        " 'inflammation', 'numeric', '2026-01-01')"
    )
    for concept, unit, value, context in cases:
        verdict = evaluate(
            connection, concept, value_numeric=value, unit=unit, age_years=34, sex="male",
            clinical_context=context,
        )
        assert verdict["interpretation"] in BENIGN_INTERPRETATIONS, (concept, verdict["interpretation"])
        assert verdict["out_of_range_side"] is None, (concept, verdict["target_range_text"])


def test_hdl_protective_band_is_not_the_target_of_a_normal_value(connection):
    verdict = evaluate(connection, "hdl-cholesterol", value_numeric=1.27, unit="mmol/L", age_years=34, sex="male")
    assert verdict["target_low"] == 1.0
    assert verdict["target_high"] is None or verdict["target_high"] == 1.55
    labels = {item["band_label"] for item in evaluate(
        connection, "hdl-cholesterol", value_numeric=1.6, unit="mmol/L", age_years=34, sex="male"
    )["authority_positions"]}
    assert any("protective" in label for label in labels)


def test_an_abnormal_verdict_shades_its_own_bodys_healthy_band(connection):
    # 8.9 is above NORIP (8.8) and inside the US 3.0-11.7: the bar must shade
    # NORIP's interval, not the US one that contains the value.
    verdict = evaluate(connection, "white-blood-cell-count", value_numeric=8.9, unit="10^9/L", age_years=34, sex="male")
    assert verdict["interpretation"] == "high"
    assert (verdict["target_low"], verdict["target_high"]) == (3.5, 8.8)
    assert verdict["out_of_range_side"] == "high"


# --- CLIN-03: inclusivity in every interval text ---------------------------


def test_interval_text_carries_the_band_comparator(connection):
    assert range_text(None, 7, "hours", True, False).startswith("< 7")
    assert range_text(0, None, None, False, True) == "> 0"  # "detected", never "≥ 0"
    sleep = evaluate(connection, "sleep_duration", value_numeric=6.95, unit="hours", age_years=34, sex="male")
    assert sleep["range_text"].startswith("< 7"), sleep["range_text"]
    assert sleep["target_range_text"].startswith("≥ 7"), sleep["target_range_text"]
    ldl = _ldl(connection, 2.5)
    assert ldl["range_text"].startswith("< 3"), ldl["range_text"]


# --- CLIN-04: conditional retest cadences ----------------------------------


def test_abnormal_only_cadence_does_not_fall_due_for_a_normal_result():
    today = date(2026, 11, 6)
    normal = staleness("2025-01-01", 3, today=today, condition={"applies_when": "abnormal"}, interpretation="normal")
    assert normal["state"] == "no_interval"
    assert "abnormal" in normal["condition_note"]
    raised = staleness("2025-01-01", 3, today=today, condition='{"applies_when": "abnormal"}', interpretation="high")
    assert raised["state"] == "overdue"


def test_age_limited_cadence_and_unknowable_settings():
    today = date(2026, 11, 6)
    fit = {"age_min": 45, "age_max": 75}
    assert staleness("2024-01-01", 12, today=today, condition=fit, age_years=34)["state"] == "no_interval"
    assert staleness("2024-01-01", 12, today=today, condition=fit, age_years=50)["state"] == "overdue"
    assert staleness("2024-01-01", 12, today=today, condition=fit)["state"] == "no_interval"
    occupational = staleness("2024-01-01", 12, today=today, condition={"applies_when": "occupational"})
    assert occupational["state"] == "no_interval" and occupational["condition_note"]
    bp = {"any": [{"age_min": 40}, {"applies_when": "abnormal"}]}
    assert staleness("2024-01-01", 12, today=today, condition=bp, age_years=34, interpretation="normal")["state"] == "no_interval"
    assert staleness("2024-01-01", 12, today=today, condition=bp, age_years=34, interpretation="high")["state"] == "overdue"
    # Routine lipid re-screening is for results at goal; above it, treatment sets the date.
    lipids = {"applies_when": "not_abnormal"}
    assert staleness("2020-01-01", 60, today=today, condition=lipids, interpretation="critical_high")["state"] == "no_interval"
    assert staleness("2020-01-01", 60, today=today, condition=lipids, interpretation="normal")["state"] == "overdue"


def test_seeded_conditions_reach_the_guidance_table_and_skip_panel_cadence(connection):
    from anamna.panels import PANEL_BY_ID, panel_retest_months

    rows = dict(connection.execute(
        "SELECT concept_id, retest_condition_json FROM concept_guidance WHERE retest_condition_json IS NOT NULL"
    ).fetchall())
    for concept in ("thyroid-stimulating-hormone", "stool-blood", "stool-helminth-eggs",
                    "renal-epithelial-cells-in-urine", "eosinophils-absolute", "ldl-cholesterol"):
        assert concept in rows, concept
    thyroid = next(panel for panel in PANEL_BY_ID.values() if "thyroid-stimulating-hormone" in str(panel.member_names).casefold() or panel.id == "thyroid")
    assert panel_retest_months(connection, thyroid) != 3


# --- CLIN-08 / 09 / 10 / 33: what must not be judged by the wrong source ----


def test_standard_crp_is_not_judged_by_cardiovascular_tiers(connection):
    verdict = evaluate(
        connection, "c-reactive-protein", value_numeric=3.6, unit="mg/L", age_years=34, sex="male",
        vendor_high=5.0,
    )
    assert verdict["authority"] == "vendor"
    assert verdict["interpretation"] == "normal"
    assert verdict["no_universal_target"] is True
    connection.execute(
        "INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)"
        " VALUES ('high-sensitivity-c-reactive-protein', 'High-sensitivity C-reactive protein',"
        " 'inflammation', 'numeric', '2026-01-01')"
    )
    hs = evaluate(connection, "high-sensitivity-c-reactive-protein", value_numeric=3.6, unit="mg/L", age_years=34, sex="male")
    assert hs["authority"] == "curated" and hs["interpretation"] == "borderline_high"


def test_adult_stool_ph_follows_the_laboratory(connection):
    verdict = evaluate(
        connection, "stool-ph", value_numeric=6.5, unit="", age_years=34, sex="male",
        vendor_low=7.0, vendor_high=7.5,
    )
    assert verdict["authority"] == "vendor"
    assert verdict["no_universal_target"] is True


@pytest.mark.parametrize("concept, unit, value", [
    ("respiratory_rate", "breaths/min", 11.68),
    ("blood_oxygen", "%", 95.6),
    ("weekly-systolic-blood-pressure-maximum", "mmHg", 153.0),
    ("weekly-diastolic-blood-pressure-minimum", "mmHg", 70.0),
])
def test_wearable_averages_and_weekly_extremes_are_not_judged(connection, concept, unit, value):
    verdict = evaluate(connection, concept, value_numeric=value, unit=unit, age_years=34, sex="male")
    assert verdict["interpretation"] == "unjudged", concept
    assert verdict["no_universal_target"] is True, concept


# --- CLIN-11 / 12 / 14 / 15: positions and who said what -------------------


def test_wbc_us_range_is_its_own_divergent_position(connection):
    verdict = evaluate(connection, "white-blood-cell-count", value_numeric=8.9, unit="10^9/L", age_years=34, sex="male")
    positions = {item["source_id"]: item for item in verdict["authority_positions"]}
    assert positions["nchs-sr11-247"]["interpretation"] == "normal"
    assert positions["norip-haem-2004"]["interpretation"] == "high"
    assert verdict["authorities_disagree"] is True


def test_lpa_shows_every_bodys_complete_position(connection):
    high = evaluate(connection, "lipoprotein-a", value_numeric=197, unit="nmol/L", age_years=34, sex="male")
    ids = {item["source_id"] for item in high["authority_positions"]}
    assert {"eas-lpa-2022", "esc-eas-2025", "acc-aha-2026", "moz-564-2016-akn"} <= ids
    ua = next(item for item in high["authority_positions"] if item["source_id"] == "moz-564-2016-akn")
    assert ua["interpretation"] == "no_universal_target" and ua["note"]
    assert high["target_source_id"] == "eas-lpa-2022" and high["target_high"] == 75.0
    grey = evaluate(connection, "lipoprotein-a", value_numeric=110, unit="nmol/L", age_years=34, sex="male")
    by_id = {item["source_id"]: item["interpretation"] for item in grey["authority_positions"]}
    assert by_id["eas-lpa-2022"] == "borderline" and by_id["esc-eas-2025"] == "high"
    assert by_id["acc-aha-2026"] == "normal"
    assert grey["authorities_disagree"] is True


def test_normal_against_optimal_is_not_a_disagreement(connection):
    bp = evaluate(connection, "systolic_blood_pressure", value_numeric=115, unit="mmHg", age_years=34, sex="male")
    assert len(bp["authority_positions"]) >= 2
    assert bp["authorities_disagree"] is False
    stage = evaluate(connection, "systolic_blood_pressure", value_numeric=135, unit="mmHg", age_years=34, sex="male")
    assert stage["authorities_disagree"] is True  # US stage 1 vs EU high-normal
    glucose = evaluate(connection, "blood-glucose", value_numeric=5.61, unit="mmol/L", age_years=34, sex="male")
    assert glucose["authorities_disagree"] is True


def test_the_printed_target_is_cited_to_its_own_body(connection):
    verdict = evaluate(connection, "non-hdl-cholesterol", value_numeric=3.29, unit="mmol/L", age_years=34, sex="male")
    assert verdict["target_high"] == 3.8
    assert verdict["target_source_id"] == "eas-eflm-2016"
    assert "EAS" in verdict["target_source_name"]


# --- CLIN-13 / DOCA-24: the laboratory's own claim --------------------------


def test_lab_range_status_is_derived_when_no_flag_was_printed(connection):
    verdict = evaluate(
        connection, "quick-prothrombin-index", value_numeric=100.9, unit="%",
        vendor_low=70.0, vendor_high=140.0,
    )
    assert verdict["vendor_status"] == "within_vendor_range"
    above = evaluate(connection, "quick-prothrombin-index", value_numeric=150, unit="%", vendor_low=70.0, vendor_high=140.0)
    assert above["vendor_status"] == "high"


def test_lab_flag_over_an_official_normal_names_both_claims(connection):
    verdict = evaluate(
        connection, "hemoglobin-a1c", value_numeric=5.3, unit="%", age_years=34, sex="male",
        vendor_low=4.0, vendor_high=5.0, vendor_interpretation="high",
    )
    assert verdict["conflicts_with_vendor"] is True
    assert verdict["interpretation"] == "indeterminate"
    assert "lab" in verdict["label"].casefold() and "official" in verdict["label"].casefold()


# --- DOCC-16: assay-specific allergen cut-off -------------------------------


def test_alex_results_use_the_alex_cut_off_and_an_unofficial_badge(connection):
    connection.execute(
        "INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)"
        " VALUES ('bet-v-1', 'Bet v 1 PR-10', 'allergy', 'numeric', '2026-01-01')"
    )
    from anamna.reference import seed_reference_library

    seed_reference_library(connection)
    alex = evaluate(connection, "bet-v-1", value_numeric=0.1, unit="kUA/L", age_years=34, sex="male", vendor_high=0.3)
    assert alex["interpretation"] == "negative"
    assert alex["target_high"] == 0.3 and alex["target_range_text"].startswith("< 0")
    assert alex["source_id"] == "madx-alex2-ifu"
    assert alex["source_official"] is False
    assert alex["authority_label"] != evaluate(connection, "hemoglobin-a1c", value_numeric=5.3, unit="%", age_years=34, sex="male")["authority_label"]
    positive = evaluate(connection, "bet-v-1", value_numeric=0.32, unit="kUA/L", age_years=34, sex="male", vendor_high=0.3)
    assert positive["interpretation"] == "positive"
    # Without an ALEX cut-off the ImmunoCAP class scale still applies.
    cap = evaluate(connection, "bet-v-1", value_numeric=0.5, unit="kUA/L", age_years=34, sex="male")
    assert cap["band_label"] == "Class 1 - low"


# --- CLIN-24: display precision never crosses an edge -----------------------


def test_edge_safe_decimals_keeps_a_value_on_its_side_of_the_edge(connection):
    sleep = evaluate(connection, "sleep_duration", value_numeric=6.95, unit="hours", age_years=34, sex="male")
    assert edge_safe_decimals(6.95, 0, sleep, "hours") == 2
    assert edge_safe_decimals(6.2, 0, sleep, "hours") == 0
    assert edge_safe_decimals(11.68, 0, {"edges": [12.0], "unit": "breaths/min"}) == 1
    # A different display unit leaves the precision alone.
    assert edge_safe_decimals(6.95, 0, sleep, "min") == 0


# --- PERF-07: one rule read per concept per request -------------------------


def test_rules_are_read_once_per_concept_inside_a_request_scope(connection):
    from anamna.reference import RULE_CACHE

    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    token = RULE_CACHE.set({})
    try:
        for value in (4.0, 5.0, 6.0, 7.0):
            evaluate(connection, "hemoglobin-a1c", value_numeric=value, unit="%", age_years=34, sex="male")
    finally:
        RULE_CACHE.reset(token)
        connection.set_trace_callback(None)
    assert sum("curated_reference_rules" in sql for sql in statements) == 1, statements


# --- UX-08 / CLIN-28: Ukrainian rule text -----------------------------------


def test_rule_helpers_speak_ukrainian(connection):
    from anamna.i18n import activate_locale, reset_locale
    from anamna.reference import interpretation_label, rule_label, rule_note

    rule = connection.execute(
        "SELECT * FROM curated_reference_rules WHERE concept_id='ldl-cholesterol' AND label_uk IS NOT NULL AND notes_uk IS NOT NULL LIMIT 1"
    ).fetchone()
    assert rule is not None, "notes_uk was not seeded"
    token = activate_locale("uk")
    try:
        assert rule_label(rule) == rule["label_uk"]
        assert rule_note(rule) == rule["notes_uk"]
        assert interpretation_label("critical_high") == "Критично високий"
        uk_verdict = _ldl(connection, 2.7, DERIVED_HIGH)
        assert "щонайменше високий" in uk_verdict["risk_note"]
        assert uk_verdict["band_label"] == next(
            row["label_uk"] for row in connection.execute(
                "SELECT label, label_uk FROM curated_reference_rules WHERE concept_id='ldl-cholesterol'"
            ) if row["label"] == "Above the goal for high cardiovascular risk"
        )
    finally:
        reset_locale(token)
