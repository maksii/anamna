"""Synthetic catalogue identity and complete navigation graph qualification."""
from __future__ import annotations

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, concept_for_alias, stable_concept_id, refine_definition, specimen_family
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts
from anamna.panels import DISPLAY_SUPPRESSED, PANELS, PANEL_BY_ID, SAME_DEVICE_KEYS, panel_for_concept


@pytest.mark.parametrize("label,name", [
    ("ІМТ", "Body mass index"),
    ("IMT", "Carotid intima-media thickness"),
    ("cimt", "Carotid intima-media thickness"),
    ("Індекс маси тіла (IMT)", "Body mass index"),
    ("Carotid intima-media thickness (ІМТ)", "Carotid intima-media thickness"),
])
def test_actual_script_and_explicit_name_disambiguate_lookalike_codes(label, name):
    assert concept_for_alias(label)["name"] == name


def test_incidental_report_category_does_not_replace_the_actual_printed_abbreviation():
    assert concept_for_alias("ІМТ", category="cardiovascular")["name"] == "Body mass index"
    assert concept_for_alias("IMT", category="body")["name"] == "Carotid intima-media thickness"


def test_mixed_script_ambiguous_code_requires_identity_evidence():
    assert concept_for_alias("IМT") is None
    assert concept_for_alias("IМT", category="body")["name"] == "Body mass index"


@pytest.mark.parametrize("label", [
    "Aspartate aminotransferase (ALT)", "Total bilirubin (DBIL)",
    "Body mass index (HbA1c)",
])
def test_conflicting_explicit_analyte_name_and_code_are_not_guessed(label):
    assert concept_for_alias(label) is None


def test_known_blood_name_cannot_be_replaced_by_urine_code_fallback():
    assert concept_for_alias("White blood cell count (WBC)", specimen="urinalysis") is None


def test_identity_survives_catalogue_seeding_and_import_lookup(tmp_path):
    settings = Settings(tmp_path / "synthetic.sqlite3", tmp_path / "sources", "synthetic")
    migrate(settings)
    with connect(settings) as db:
        seed_concepts(db)
        vendor = ensure_vendor(db, "Synthetic clinic", None)
        assert ensure_concept(db, "ІМТ", vendor, unit_raw="kg/m²")[0] == "body-mass-index"
        assert ensure_concept(db, "IMT", vendor, unit_raw="mm")[0] == "carotid-intima-media-thickness"


@pytest.mark.parametrize("label,name", [
    ("Glucose", "Urine glucose"), ("Protein", "Urine protein"),
    ("Bilirubin", "Urine bilirubin"), ("Ketones", "Urine ketones"),
    ("Nitrite", "Urine nitrite"), ("Urobilinogen", "Urine urobilinogen"),
    ("Leukocytes", "Urine leukocytes"), ("Erythrocytes", "Urine erythrocytes"),
    ("White blood cells", "Urine leukocytes"), ("Red blood cells", "Urine erythrocytes"),
    ("Colour", "Urine colour"), ("Appearance", "Urine appearance"),
])
def test_generic_english_api_labels_reach_their_explicit_urine_quantity(label, name):
    assert concept_for_alias(label, specimen="urinalysis")["name"] == name
    assert concept_for_alias(label, category="urinalysis")["name"] == name


def test_contextual_api_aliases_do_not_guess_unknown_specimen_or_protein_fraction():
    assert concept_for_alias("Protein") is None
    assert concept_for_alias("Glucose")["name"] == "Blood glucose"
    assert concept_for_alias("Albumin", specimen="urinalysis") is None
    assert concept_for_alias("Total bilirubin", specimen="urinalysis") is None
    assert concept_for_alias("Protein", specimen="csf") is None
    assert concept_for_alias("Leukocytes", specimen="hematology")["name"] == "White blood cell count"
    assert concept_for_alias("Erythrocytes", specimen="hematology")["name"] == "Red blood cell count"


def test_contextual_urine_count_keeps_its_microscopy_unit_refinement(tmp_path):
    settings = Settings(tmp_path / "synthetic.sqlite3", tmp_path / "sources", "synthetic")
    migrate(settings)
    with connect(settings) as db:
        seed_concepts(db)
        vendor = ensure_vendor(db, "Synthetic clinic", None)
        assert ensure_concept(db, "Leukocytes", vendor, unit_raw="per HPF", specimen="urine")[0] == "urine-leukocytes-per-high-power-field"


@pytest.mark.parametrize("label", ["Urinalysis", "urinalysis panel", "URINALYSIS"])
def test_english_urinalysis_material_is_recognized(label):
    assert specimen_family(label) == "urinalysis"


@pytest.mark.parametrize("name,unit", [
    ("Urine leukocytes", "LEU/µL"), ("Urine erythrocytes", "ERY/µL"),
    ("Urine leukocytes", "cells/µL"), ("Urine erythrocytes", "cells/µL"),
])
def test_cell_concentration_does_not_establish_a_chemical_strip_method(name, unit):
    definition = concept_for_alias(name)
    assert refine_definition(definition, unit=unit) is definition


@pytest.mark.parametrize("name,reference,target", [
    ("Urine leukocytes", "Leukocyte esterase activity", "Urine leukocytes (dipstick)"),
    ("Urine leukocytes", "Активність лейкоцитарної естерази", "Urine leukocytes (dipstick)"),
    ("Urine erythrocytes", "Peroxidase activity", "Urine erythrocytes (dipstick)"),
    ("Urine erythrocytes", "За пероксидазною активністю", "Urine erythrocytes (dipstick)"),
    ("Urine erythrocytes", "Reagent strip test", "Urine erythrocytes (dipstick)"),
])
def test_explicit_source_method_identifies_strip_results(name, reference, target):
    assert refine_definition(concept_for_alias(name), unit="cells/µL", reference=reference)["name"] == target


def test_mixed_strip_and_microscopy_reference_does_not_prove_a_specific_method():
    definition = concept_for_alias("Urine leukocytes")
    assert refine_definition(definition, unit="cells/µL", reference="Urine strip and microscopy") is definition


@pytest.mark.parametrize("label", ["eGFR", "CKD-EPI", "ШКФ", "рШКФ (CKD-EPI)",
                                   "Estimated glomerular filtration rate", "eGFR (CKD-EPI 2009)", "eGFR (MDRD)"])
def test_reported_egfr_does_not_invent_an_equation_year(label):
    definition = concept_for_alias(label)
    assert definition["name"] == "Estimated glomerular filtration rate, reported"
    assert panel_for_concept(stable_concept_id(definition["name"])).id == "kidney"


def test_explicit_equation_alias_retains_2021_identity_but_not_other_biomarkers():
    assert concept_for_alias("eGFR (CKD-EPI 2021)")["name"] == "Estimated glomerular filtration rate (CKD-EPI 2021)"
    assert concept_for_alias("Cystatin C (CKD-EPI2021)") is None
    assert concept_for_alias("MDRD (CKD-EPI2021)") is None
    assert concept_for_alias("Combined markers (CKD-EPI2021)") is None


def test_every_catalogue_alias_round_trips_with_its_own_quantity_context():
    for definition in CONCEPT_DEFINITIONS:
        for alias in (definition["name"], *definition["aliases"]):
            assert concept_for_alias(
                alias, str(definition.get("value_type", "numeric")), str(definition["category"]),
            ) is definition, (definition["name"], alias)


def test_every_defined_result_has_a_panel_or_an_explicit_suppression():
    # Previous audits excused every imaging metric instead of providing a
    # coherent study collection. There is no generic panel-less escape hatch.
    assert [definition["name"] for definition in CONCEPT_DEFINITIONS
            if not panel_for_concept(stable_concept_id(definition["name"]), str(definition["category"]))
            and stable_concept_id(definition["name"]) not in DISPLAY_SUPPRESSED] == []


def test_protocol_collections_are_nonprescriptive_and_do_not_merge_laboratory_fractions():
    protocol_ids = {
        "echocardiography", "vascular_ultrasound", "abdominal_ultrasound", "renal_ultrasound",
        "thyroid_ultrasound", "pelvic_ultrasound", "breast_imaging", "soft_tissue_imaging",
        "eeg", "imaging_radiation",
    }
    assert all(PANEL_BY_ID[key].renderer == "imaging" for key in protocol_ids)
    assert PANEL_BY_ID["tumour_markers"].renderer == "context"
    assert PANEL_BY_ID["weather"].renderer == "context"
    assert set(PANEL_BY_ID["weather"].device_members) == {"weather_temperature", "weather_humidity"}
    assert "albumin" not in PANEL_BY_ID["abdominal_ultrasound"].members
    assert "creatinine" not in PANEL_BY_ID["renal_ultrasound"].members
    assert "thyroid-stimulating-hormone" not in PANEL_BY_ID["thyroid_ultrasound"].members
    assert "cancer-antigen-15-3-ca-15-3" not in PANEL_BY_ID["breast_imaging"].members
    assert "cancer-antigen-15-3-ca-15-3" in PANEL_BY_ID["tumour_markers"].members
    assert panel_for_concept("cancer-antigen-125-ca-125").id == "ovarian_risk"


def test_sdnn_and_rmssd_remain_distinct_panel_metrics_without_same_measurement_merge():
    assert "heart_rate_variability" in PANEL_BY_ID["cardio_fitness"].device_members
    assert "heart_rate_variability_rmssd" in PANEL_BY_ID["sleep"].device_members
    assert not {"heart_rate_variability", "heart_rate_variability_rmssd"} & SAME_DEVICE_KEYS
    assert all(len(panel.members) == len(set(panel.members)) for panel in PANELS)
