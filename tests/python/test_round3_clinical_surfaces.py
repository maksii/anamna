"""Synthetic clinical applicability and cross-process context-cache evidence."""
from __future__ import annotations

import pytest
from datetime import date
from markupsafe import escape

from anamna import factors
from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale, t
from anamna.reference import evaluate, guidance, load_library
from anamna.derived import DERIVED_EGFR_METHOD, refresh_derived_observations
from anamna.web import app as web

from test_audit_sample_facts import add_observation
from test_concepts_repair import _insert
from test_web_panels import build


EGFR = "estimated-glomerular-filtration-rate-ckd-epi-2021"
REPORTED_EGFR = "estimated-glomerular-filtration-rate-reported"
PREGNANCY_URL = "https://www.nice.org.uk/guidance/ng3/chapter/Recommendations"


def _reported_egfr(tmp_path, concept_id=EGFR):
    settings, owner, client = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET sex_at_birth='female',pregnancy_due_date='2025-08-01'")
        _insert(db, owner, "reported-egfr", "Reported eGFR", concept_id, value=100, unit="mL/min/1.73m²")
        db.execute("UPDATE observations SET vendor_reference_low=90,vendor_reference_high=120,vendor_interpretation='within_vendor_range' WHERE id='reported-egfr'")
    web.invalidate_catalog()
    return settings, owner, client


@pytest.mark.parametrize("locale", ["en", "uk"])
@pytest.mark.parametrize("concept_id", [EGFR, REPORTED_EGFR])
def test_reported_pregnancy_egfr_keeps_source_claim_without_clinical_staging(tmp_path, locale, concept_id):
    settings, owner, client = _reported_egfr(tmp_path, concept_id)
    client.cookies.set("anamna_lang", locale)
    page = client.get(f"/metrics/{concept_id}")
    assert page.status_code == 200
    verdict = page.context["verdict"]
    assert verdict["interpretation"] == "unjudged"
    assert verdict["authority"] == "none"
    assert verdict["curated_blocked"] == "pregnancy_egfr"
    assert verdict["vendor_status"] == "within_vendor_range"
    assert verdict["source_id"] == "nice-ng3-egfr-pregnancy"
    assert verdict["source_url"] == PREGNANCY_URL
    token = activate_locale(locale)
    try:
        assert str(escape(t("verdict.blocked_egfr_pregnancy"))) in page.text
    finally:
        reset_locale(token)
    assert 'data-reason="pregnancy_egfr"' in page.text
    with connect(settings) as db:
        row = db.execute("SELECT value_numeric,verification_status,extraction_method FROM observations WHERE id='reported-egfr'").fetchone()
        assert tuple(row) == (100, "verified", "native_pdf_text_parser")
        entry = guidance(db, concept_id)
        assert any(source["id"] == verdict["source_id"] and source["url"] == PREGNANCY_URL for source in entry["sources"])


def test_pregnancy_guard_does_not_fall_back_to_a_normal_laboratory_range(tmp_path):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        verdict = evaluate(db, EGFR, value_numeric=100, unit="mL/min/1.73m²", age_years=34,
                           sex="female", vendor_low=90, vendor_high=120,
                           vendor_interpretation="within_vendor_range", clinical_context={"pregnant": True})
    assert verdict["interpretation"] == "unjudged"
    assert verdict["vendor_status"] == "within_vendor_range"
    library = load_library()
    source = next(item for item in library["sources"] if item["id"] == verdict["source_id"])
    assert source["url"] == verdict["source_url"] == PREGNANCY_URL
    assert source["official"] is True


def test_external_pregnancy_context_edit_invalidates_warm_medical_catalog(tmp_path):
    settings, owner, client = _reported_egfr(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET pregnancy_due_date=NULL")
        created = db.execute("SELECT created_at FROM patients WHERE owner_user_id=?", (owner,)).fetchone()[0]
    before = client.get(f"/metrics/{EGFR}")
    assert before.context["verdict"]["interpretation"] != "unjudged"
    with connect(settings) as other_process:
        old_stamp = web._fingerprint(other_process, owner, "lab")
        other_process.execute("UPDATE patients SET pregnancy_due_date='2025-08-01'")
        assert other_process.execute("SELECT created_at FROM patients WHERE owner_user_id=?", (owner,)).fetchone()[0] == created
        assert web._fingerprint(other_process, owner, "lab") != old_stamp
    after = client.get(f"/metrics/{EGFR}")
    assert after.context["verdict"]["interpretation"] == "unjudged"
    assert after.context["verdict"]["curated_blocked"] == "pregnancy_egfr"


def test_external_factor_edit_invalidates_a_warm_inr_verdict_without_timestamp_advance(tmp_path):
    settings, owner, client = build(tmp_path)
    add_observation(settings, owner, "inr", 2.5, "2025-02-13", "synthetic-inr", raw_name="INR", unit="ratio")
    first = client.get("/metrics/inr")
    assert first.context["verdict"]["band_label"] != "Vitamin K antagonist therapeutic range"
    values, error = factors.clean({"kind": "medicine", "name": "Warfarin", "status": "current", "atc_code": "B01AA03", "started_on": "2025-01-01"}, today=date(2025, 3, 1))
    assert error is None
    with connect(settings) as db:
        factor_id = factors.create(db, owner, f"patient-{owner}", values)
        created, updated = db.execute("SELECT created_at,updated_at FROM factors WHERE id=?", (factor_id,)).fetchone()
    on = client.get("/metrics/inr")
    assert on.context["verdict"]["band_label"] == "Vitamin K antagonist therapeutic range"
    with connect(settings) as other_process:
        other_process.execute("UPDATE factors SET atc_code='A01AA01',name='Synthetic other factor' WHERE id=?", (factor_id,))
        assert tuple(other_process.execute("SELECT created_at,updated_at FROM factors WHERE id=?", (factor_id,)).fetchone()) == (created, updated)
    off = client.get("/metrics/inr")
    assert off.context["verdict"]["band_label"] != "Vitamin K antagonist therapeutic range"


@pytest.mark.parametrize("raw_name", ["eGFR", "eGFR (CKD-EPI 2009)", "eGFR (MDRD)"])
def test_generic_reported_egfr_blocks_duplicate_equation_and_keeps_printed_method(tmp_path, raw_name):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        _insert(db, owner, "reported-generic", raw_name, REPORTED_EGFR, value=100, unit="mL/min/1.73m²")
        refresh_derived_observations(db)
        assert db.execute("SELECT COUNT(*) FROM observations WHERE extraction_method=?", (DERIVED_EGFR_METHOD,)).fetchone()[0] == 0
        row = db.execute("SELECT raw_name,concept_id,value_numeric FROM observations WHERE id='reported-generic'").fetchone()
        assert tuple(row) == (raw_name, REPORTED_EGFR, 100)
        assert guidance(db, REPORTED_EGFR)["no_universal_target_reason"]


def test_generic_egfr_guidance_has_no_invented_equation_specific_bands():
    entry = next(item for item in load_library()["analytes"] if item["concept_id"] == REPORTED_EGFR)
    assert entry["canonical_name"] == "Estimated glomerular filtration rate, reported"
    assert entry["kind"] == "no_universal_target"
    assert entry["bands"] == []
    assert entry["retest_interval_months"] is None
