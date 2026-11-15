"""Connection/lifecycle regressions independent of the private audit corpus."""
from __future__ import annotations

import json

import pytest

from anamna.calculation_info import CALCULATION_URLS
from anamna.config import resource_path
from anamna.db import connect, utc_now
from anamna.derived import _creatinine_mg_dl, refresh_derived_observations
from anamna.lab_calculations import LAB_CALCULATIONS
from anamna.locales.messages import MESSAGES
from anamna.ingest.pipeline import repair_observation_semantics
from anamna.web import app as web

from test_concepts_repair import _egfr, _insert
from test_web_panels import build
from test_device_calculations import _history


@pytest.mark.parametrize("value,unit", [(88, None), (88, ""), (-88, "µmol/L"),
                                        (float("inf"), "mg/dL"), (1, "kg")])
def test_creatinine_requires_an_explicit_dimension_and_finite_positive_value(value, unit):
    assert _creatinine_mg_dl(value, unit) is None


def test_egfr_ambiguous_sample_is_not_reconstructed(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        _insert(db, owner, "conflicting-creatinine", "Creatinine", "creatinine", value=120, unit="µmol/L")
        refresh_derived_observations(db)
        assert _egfr(db) == []


@pytest.mark.parametrize("specimen", ["urine", "saliva", "CSF"])
def test_egfr_never_uses_an_explicit_nonblood_specimen(tmp_path, specimen):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified',specimen=? WHERE concept_id='creatinine'", (specimen,))
        refresh_derived_observations(db)
        assert _egfr(db) == []


def test_new_catalogue_identity_can_attach_to_checked_unknown_label_without_reinterpreting_it(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("INSERT INTO concepts(id,canonical_name,category,value_type,created_at) VALUES ('legacy-hp', 'Helicobacter pylori', 'unmapped', 'mixed', ?)", (utc_now(),))
        _insert(db, owner, "checked-unknown", "Helicobacter pylori", "legacy-hp", text="negative", status="corrected")
        db.execute("UPDATE observations SET extraction_method='human_corrected' WHERE id='checked-unknown'")
        repair_observation_semantics(db)
        row = db.execute("SELECT * FROM observations WHERE id='checked-unknown'").fetchone()
        assert row["concept_id"] == "h-pylori-test-method-unspecified"
        assert row["value_text"] == "negative" and row["verification_status"] == "corrected"
        assert row["raw_name"] == "Helicobacter pylori"
        assert repair_observation_semantics(db) == 0


def test_equations_have_bilingual_explanations_and_registered_library_sources():
    library = json.loads(resource_path("reference_library.json").read_text(encoding="utf-8"))
    sources = {item["url"] for item in library["sources"]}
    analytes = {item["concept_id"]: item for item in library["analytes"]}
    for calculation in LAB_CALCULATIONS:
        assert set(MESSAGES["doc." + calculation.method]) == {"en", "uk"}
        assert CALCULATION_URLS[calculation.method] == calculation.source_url
        assert calculation.source_url in sources
        assert analytes[calculation.concept_id]["calculation"]["output_provisional"]


def test_calculated_bmi_visible_with_both_inputs_in_both_views_and_languages(tmp_path):
    settings, owner = _history(tmp_path)
    from fastapi.testclient import TestClient
    from anamna.security import create_session

    client = TestClient(web.create_app(settings))
    token, _ = create_session(settings, owner)
    client.cookies.set("anamna_session", token)
    with connect(settings) as db:
        refresh_derived_observations(db)
    web.invalidate_catalog()
    for lang, expected in (("en", "Calculated · provisional"), ("uk", "Розраховано · не підтверджено")):
        client.cookies.set("anamna_lang", lang)
        for url in ("/metrics/body-mass-index", "/devices/metrics/body_mass_index"):
            response = client.get(url)
            assert response.status_code == 200
            assert CALCULATION_URLS["derived_bmi"] in response.text
            assert "2024" in response.text and "2025" in response.text
            assert (expected in response.text) if "/metrics/body-" in url else (MESSAGES["calc.provisional"][lang] in response.text)


def test_profile_only_bmi_has_no_invented_date_and_is_visible_with_its_inputs(tmp_path):
    settings, owner, client = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200,weight_kg=80 WHERE owner_user_id=?", (owner,))
        rows = web._linked_observation_rows(db, owner, "body-mass-index")
        assert len(rows) == 1 and rows[0]["value_numeric"] == 20
        assert rows[0]["observed_at"] is None and rows[0]["is_profile"]
        assert rows[0]["extraction_method"] == "derived_profile_bmi"
        assert web._metric_chart(db, rows, "kg/m²", "1990-01-01", "male") == []
    web.invalidate_catalog()
    for lang in ("en", "uk"):
        client.cookies.set("anamna_lang", lang)
        for url in ("/profile", "/metrics/body-mass-index", "/panels/body"):
            response = client.get(url)
            assert response.status_code == 200
            assert MESSAGES["calc.profile_source"][lang] in response.text, url
            if url == "/profile":
                assert MESSAGES["profile.bmi"][lang] in response.text
            assert "/documents/None" not in response.text
    with connect(settings) as db:
        db.execute("UPDATE patients SET weight_kg=100 WHERE owner_user_id=?", (owner,))
    web.invalidate_catalog(owner)
    response = client.get("/metrics/body-mass-index")
    assert response.status_code == 200 and ">25<" in response.text
