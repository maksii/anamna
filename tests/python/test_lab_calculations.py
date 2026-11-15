"""Synthetic sample boundaries and arithmetic for missing laboratory results."""

from __future__ import annotations

import sqlite3
import json

import pytest

from anamna.db import connect, utc_now
from anamna.derived import refresh_derived_observations
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id
from anamna.lab_calculations import LAB_CALCULATIONS, wanted_lab_observations


_COLUMNS = (
    "owner_user_id", "patient_id", "document_id", "page_number", "concept_id", "raw_name",
    "value_type", "value_numeric", "unit_raw", "unit_canonical", "observed_at",
    "verification_status", "extraction_method", "confidence", "evidence_text",
    "evidence_bbox_json", "parser_version", "report_id", "entry_source", "entered_by_user_id",
    "specimen", "sample_condition",
    "calculation_inputs_json",
)


@pytest.fixture
def connection():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE patients(id TEXT PRIMARY KEY, owner_user_id TEXT)")
        db.execute("INSERT INTO patients VALUES ('patient', 'owner')")
        db.execute("CREATE TABLE documents(id TEXT PRIMARY KEY, owner_user_id TEXT, patient_id TEXT)")
        db.execute("INSERT INTO documents VALUES ('document', 'owner', 'patient')")
        db.execute("CREATE TABLE reports(id TEXT PRIMARY KEY, owner_user_id TEXT, patient_id TEXT, document_id TEXT)")
        db.execute("CREATE TABLE concepts(id TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO concepts VALUES (?)", [(stable_concept_id(c["name"]),) for c in CONCEPT_DEFINITIONS])
        db.execute("CREATE TABLE observations(id TEXT PRIMARY KEY, " + ",".join(
            f"{column} {'REAL' if column in {'value_numeric', 'confidence'} else 'TEXT'}"
            for column in (*_COLUMNS, "comparator", "created_at")
        ) + ")")
        yield db


def add(db, name, value, unit, **overrides):
    row = {
        "id": f"input-{db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]}",
        "owner_user_id": "owner", "patient_id": "patient", "document_id": "document",
        "page_number": 1, "concept_id": stable_concept_id(name), "raw_name": name,
        "value_type": "numeric", "value_numeric": value, "unit_raw": unit,
        "observed_at": "2024-01-10", "verification_status": "verified",
        "extraction_method": "native_pdf_text_parser", "confidence": 0.99,
        "evidence_text": "Synthetic source line", "parser_version": "test", "entry_source": "document",
        "created_at": utc_now(),
    }
    row.update(overrides)
    db.execute(f"INSERT INTO observations({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    return row["id"]


def results(db):
    return {row["concept_id"]: row for values in wanted_lab_observations(db).values()
            if (row := dict(zip(_COLUMNS, values, strict=True)))}


def test_cbc_calculations_and_explicit_converted_units(connection):
    add(connection, "Hemoglobin", 15, "g/dL")
    add(connection, "Hematocrit", 0.45, "L/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    rows = results(connection)
    assert rows["mean-corpuscular-volume"]["value_numeric"] == 90
    assert rows["mean-corpuscular-hemoglobin"]["value_numeric"] == 30
    assert rows["mean-corpuscular-hemoglobin-concentration"]["value_numeric"] == 333.3
    assert {row["verification_status"] for row in rows.values()} == {"extracted"}
    assert "150 g/L" in rows["mean-corpuscular-hemoglobin"]["evidence_text"]
    assert "input-0" in rows["mean-corpuscular-hemoglobin"]["evidence_text"]


def test_only_independently_reported_mcv_can_recover_hct(connection):
    add(connection, "Mean corpuscular volume", 90, "fL")
    add(connection, "Red blood cell count", 5, "10^12/L")
    assert results(connection)["hematocrit"]["value_numeric"] == 45
    connection.execute("UPDATE observations SET extraction_method='derived_mcv'")
    assert results(connection) == {}


def test_plateletcrit_unit_algebra(connection):
    add(connection, "Platelet count", 250, "10^9/L")
    add(connection, "Mean platelet volume", 10, "fL")
    assert results(connection)["plateletcrit"]["value_numeric"] == 0.25


def test_subtractions_keep_reported_targets_and_refuse_negative_values(connection):
    add(connection, "Total cholesterol", 5.2, "mmol/L")
    add(connection, "HDL cholesterol", 1.2, "mmol/L")
    add(connection, "Total bilirubin", 20, "µmol/L")
    add(connection, "Direct bilirubin", 5, "µmol/L")
    assert results(connection)["non-hdl-cholesterol"]["value_numeric"] == 4
    # A common sample does not prove the total/direct assay pair is compatible.
    assert "indirect-bilirubin" not in results(connection)
    add(connection, "Non-HDL cholesterol", 4.1, "mmol/L", verification_status="extracted")
    assert "non-hdl-cholesterol" not in results(connection)
    connection.execute("UPDATE observations SET value_numeric=25 WHERE concept_id='direct-bilirubin'")
    assert "indirect-bilirubin" not in results(connection)


def test_cholesterol_mass_units_are_explicitly_converted(connection):
    add(connection, "Total cholesterol", 200, "mg/dL")
    add(connection, "HDL cholesterol", 50, "mg/dL")
    assert results(connection)["non-hdl-cholesterol"]["value_numeric"] == round(150 / 38.67, 2)
    assert results(connection)["atherogenic-coefficient"]["value_numeric"] == 3


def test_coefficient_refuses_zero_hdl(connection):
    add(connection, "Total cholesterol", 5, "mmol/L")
    add(connection, "HDL cholesterol", 0, "mmol/L")
    assert "atherogenic-coefficient" not in results(connection)


def test_clinical_bmi_uses_explicit_same_sample_units(connection):
    add(connection, "Body weight", 81000, "g")
    add(connection, "Body height", 1.8, "m")
    assert results(connection)["body-mass-index"]["value_numeric"] == 25
    connection.execute("UPDATE observations SET unit_raw=NULL WHERE concept_id='body-height'")
    assert results(connection) == {}


@pytest.mark.parametrize("name,unit", [("Body weight", "arbitrary"), ("Body height", "arbitrary"),
                                     ("Body weight", "cm"), ("Body height", "kg")])
def test_clinical_bmi_unknown_or_incompatible_units_do_not_abort_other_calculations(connection, name, unit):
    add(connection, "Body weight", 81, unit if name == "Body weight" else "kg")
    add(connection, "Body height", 180, unit if name == "Body height" else "cm")
    add(connection, "Hemoglobin", 150, "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    rows = results(connection)
    assert "body-mass-index" not in rows
    assert rows["mean-corpuscular-hemoglobin"]["value_numeric"] == 30


def test_reported_device_bmi_wins_but_computed_fallback_does_not(connection):
    connection.execute("CREATE TABLE device_metric_days(id TEXT, owner_user_id TEXT, patient_id TEXT, day TEXT, metric_key TEXT)")
    add(connection, "Body weight", 81, "kg")
    add(connection, "Body height", 180, "cm")
    connection.execute("INSERT INTO device_metric_days VALUES ('derived-bmi-old', 'owner', 'patient', '2024-01-10', 'body_mass_index')")
    assert results(connection)["body-mass-index"]["value_numeric"] == 25
    connection.execute("UPDATE device_metric_days SET id='reported-device-bmi'")
    assert results(connection) == {}
    connection.execute("UPDATE device_metric_days SET owner_user_id='another-owner'")
    assert results(connection)["body-mass-index"]["value_numeric"] == 25


def test_albumin_globulin_ratio_and_zero_denominator(connection):
    add(connection, "Albumin", 4, "g/dL")
    add(connection, "Total protein", 70, "g/L")
    assert results(connection)["albumin-to-globulin-ratio"]["value_numeric"] == 1.33
    assert results(connection)["globulin-calculated"]["value_numeric"] == 30
    connection.execute("UPDATE observations SET value_numeric=40 WHERE concept_id='total-protein'")
    assert "albumin-to-globulin-ratio" not in results(connection)
    assert results(connection)["globulin-calculated"]["value_numeric"] == 0
    connection.execute("UPDATE observations SET value_numeric=30 WHERE concept_id='total-protein'")
    assert results(connection) == {}


@pytest.mark.parametrize("change", [
    {"owner_user_id": "another-owner"}, {"patient_id": "another-patient"},
    {"document_id": "another-document"}, {"report_id": "another-order"},
    {"observed_at": "2024-01-11"}, {"observed_at": "2024-01-10T14:00:00"},
    {"specimen": "urine"}, {"sample_condition": "fasting"},
    {"observed_at": None}, {"document_id": None},
])
def test_no_combining_across_sample_boundaries(connection, change):
    add(connection, "Hemoglobin", 150, "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L", **change)
    assert results(connection) == {}


@pytest.mark.parametrize("change", [
    {"verification_status": "extracted"}, {"verification_status": "rejected"},
    {"comparator": "<"}, {"value_numeric": -5}, {"value_numeric": 0},
    {"value_numeric": float("inf")}, {"unit_raw": None}, {"unit_raw": "arbitrary"},
    {"extraction_method": "derived_anything"},
])
def test_invalid_or_unchecked_inputs_do_not_create_results(connection, change):
    add(connection, "Hemoglobin", 150, "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L", **change)
    assert results(connection) == {}


@pytest.mark.parametrize("day", ["", "2024", "2024-02-30", "2024-01-10garbage", "2024-01-10T99:00:00"])
def test_invalid_common_date_cannot_be_a_sample_anchor(connection, day):
    add(connection, "Hemoglobin", 150, "g/L", observed_at=day)
    add(connection, "Red blood cell count", 5, "10^12/L", observed_at=day)
    assert results(connection) == {}


def test_duplicate_input_is_ambiguous_even_if_identical(connection):
    add(connection, "Hemoglobin", 150, "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    assert results(connection) == {}


def test_unmanaged_calculation_target_is_not_duplicated(connection):
    add(connection, "Hemoglobin", 150, "g/L")
    add(connection, "Red blood cell count", 5, "10^12/L")
    add(connection, "Mean corpuscular hemoglobin", 30, "pg", extraction_method="derived_other_equation")
    assert results(connection) == {}


@pytest.mark.parametrize("name", ["Neutrophils", "Lymphocytes", "Monocytes", "Eosinophils", "Basophils",
                                 "Immature granulocytes", "Granulocytes", "Mixed white cells"])
def test_each_automated_population_converts_without_merging(connection, name):
    add(connection, "White blood cell count", 8, "10^9/L")
    add(connection, name, 25, "%")
    absolute_id = stable_concept_id(f"{name}, absolute")
    assert results(connection)[absolute_id]["value_numeric"] == 2
    connection.execute("DELETE FROM observations WHERE concept_id=?", (stable_concept_id(name),))
    add(connection, f"{name}, absolute", 2, "10^9/L")
    assert results(connection)[stable_concept_id(name)]["value_numeric"] == 25


def test_manual_differential_never_becomes_automated_or_anc(connection):
    add(connection, "White blood cell count", 8, "10^9/L")
    add(connection, "Segmented neutrophils", 50, "%")
    add(connection, "Band neutrophils", 5, "%")
    add(connection, "Lymphocytes (manual differential)", 25, "%")
    assert results(connection) == {}


def test_percentage_above_100_is_refused_and_zero_is_preserved(connection):
    add(connection, "White blood cell count", 8, "10^9/L")
    add(connection, "Basophils", 0, "%")
    assert results(connection)["basophils-absolute"]["value_numeric"] == 0
    connection.execute("UPDATE observations SET value_numeric=101 WHERE concept_id='basophils'")
    assert results(connection) == {}


def test_reticulocyte_percent_and_absolute_have_correct_thousand_factor(connection):
    add(connection, "Red blood cell count", 5, "10^12/L")
    retic = add(connection, "Reticulocytes", 2, "%")
    assert results(connection)["reticulocytes-absolute"]["value_numeric"] == 100
    connection.execute("DELETE FROM observations WHERE id=?", (retic,))
    add(connection, "Reticulocytes, absolute", 0.1, "10^12/L")
    assert results(connection)["reticulocytes"]["value_numeric"] == 2


def test_irf_is_medium_plus_high_and_cannot_exceed_100(connection):
    add(connection, "Reticulocytes, medium fluorescence fraction", 8, "%")
    high = add(connection, "Reticulocytes, high fluorescence fraction", 2, "%")
    assert results(connection)["immature-reticulocyte-fraction"]["value_numeric"] == 10
    connection.execute("UPDATE observations SET value_numeric=95 WHERE id=?", (high,))
    assert results(connection) == {}


def test_reported_irf_wins_and_derived_fractions_never_chain(connection):
    add(connection, "Reticulocytes, medium fluorescence fraction", 8, "%")
    high = add(connection, "Reticulocytes, high fluorescence fraction", 2, "%", extraction_method="derived_other")
    assert results(connection) == {}
    connection.execute("UPDATE observations SET extraction_method='native_pdf_text_parser' WHERE id=?", (high,))
    add(connection, "Immature reticulocyte fraction", 9.9, "%", verification_status="extracted")
    assert results(connection) == {}


def test_stable_identity_but_changed_inputs_change_provenance(connection):
    hb_id = add(connection, "Hemoglobin", 150, "g/L")
    rbc_id = add(connection, "Red blood cell count", 5, "10^12/L")
    first = wanted_lab_observations(connection)
    connection.execute("UPDATE observations SET value_numeric=300 WHERE id=?", (hb_id,))
    connection.execute("UPDATE observations SET value_numeric=10 WHERE id=?", (rbc_id,))
    second = wanted_lab_observations(connection)
    assert first.keys() == second.keys()
    [old], [new] = first.values(), second.values()
    assert old[7] == new[7] == 30
    assert old[14] != new[14]


@pytest.mark.parametrize("specimen", ["urine", "saliva", "CSF", "stool", "vaginal smear"])
def test_matching_nonblood_specimens_cannot_supply_blood_equations(connection, specimen):
    add(connection, "Hemoglobin", 150, "g/L", specimen=specimen)
    add(connection, "Red blood cell count", 5, "10^12/L", specimen=specimen)
    add(connection, "Albumin", 40, "g/L", specimen=specimen)
    add(connection, "Total protein", 70, "g/L", specimen=specimen)
    assert results(connection) == {}


@pytest.mark.parametrize("source", [{"report_id": "", "document_id": None},
                                    {"report_id": None, "document_id": " "}])
def test_empty_sample_identity_cannot_join_results(connection, source):
    add(connection, "Hemoglobin", 150, "g/L", **source)
    add(connection, "Red blood cell count", 5, "10^12/L", **source)
    assert results(connection) == {}


def test_report_and_document_identifiers_are_separate_namespaces(connection):
    connection.execute("INSERT INTO reports VALUES ('same-id', 'owner', 'patient', 'document')")
    connection.execute("INSERT INTO documents VALUES ('same-id', 'owner', 'patient')")
    add(connection, "Hemoglobin", 150, "g/L", report_id="same-id")
    add(connection, "Red blood cell count", 5, "10^12/L", document_id="same-id")
    assert results(connection) == {}


@pytest.mark.parametrize("mutation", [
    "UPDATE documents SET owner_user_id='another-owner' WHERE id='document'",
    "UPDATE documents SET patient_id='another-patient' WHERE id='document'",
    "UPDATE reports SET owner_user_id='another-owner' WHERE id='report'",
    "UPDATE reports SET patient_id='another-patient' WHERE id='report'",
    "UPDATE reports SET document_id='another-document' WHERE id='report'",
])
def test_source_document_and_report_must_belong_to_the_same_record(connection, mutation):
    connection.execute("INSERT INTO reports VALUES ('report', 'owner', 'patient', 'document')")
    connection.execute("INSERT INTO documents VALUES ('another-document', 'owner', 'patient')")
    add(connection, "Hemoglobin", 150, "g/L", report_id="report")
    add(connection, "Red blood cell count", 5, "10^12/L", report_id="report")
    assert results(connection)["mean-corpuscular-hemoglobin"]["value_numeric"] == 30
    connection.execute(mutation)
    assert results(connection) == {}


@pytest.mark.parametrize("change", ["owner_user_id='another-owner'", "patient_id='another-patient'"])
def test_report_only_inputs_also_check_the_reports_document_identity(connection, change):
    connection.execute("INSERT INTO reports VALUES ('report', 'owner', 'patient', 'document')")
    add(connection, "Hemoglobin", 150, "g/L", document_id=None, report_id="report")
    add(connection, "Red blood cell count", 5, "10^12/L", document_id=None, report_id="report")
    assert results(connection)["mean-corpuscular-hemoglobin"]["value_numeric"] == 30
    connection.execute("UPDATE documents SET " + change + " WHERE id='document'")
    assert results(connection) == {}


def test_patient_owner_must_match_even_if_both_source_rows_share_wrong_owner(connection):
    add(connection, "Hemoglobin", 150, "g/L", owner_user_id="other-owner")
    add(connection, "Red blood cell count", 5, "10^12/L", owner_user_id="other-owner")
    assert results(connection) == {}


def test_equivalent_units_still_preserve_changed_input_provenance(connection):
    hb = add(connection, "Hemoglobin", 150, "g/L", specimen="blood", sample_condition="fasting")
    add(connection, "Red blood cell count", 5, "10^12/L", specimen="blood", sample_condition="fasting")
    [first] = wanted_lab_observations(connection).values()
    connection.execute("UPDATE observations SET value_numeric=15, unit_raw='g/dL' WHERE id=?", (hb,))
    [second] = wanted_lab_observations(connection).values()
    assert first[7] == second[7] == 30
    assert first[14] != second[14]
    assert first[-3:-1] == second[-3:-1] == ("blood", "fasting")


def test_structured_dependencies_keep_source_values_units_time_and_links(connection):
    hb = add(connection, "Hemoglobin", 15, "g/dL", observed_at="2024-01-10T09:30:00+02:00")
    rbc = add(connection, "Red blood cell count", 5, "10^12/L", observed_at="2024-01-10T09:30:00+02:00")
    row = results(connection)["mean-corpuscular-hemoglobin"]
    assert row["value_numeric"] == 30
    inputs = json.loads(row["calculation_inputs_json"])
    assert inputs == [
        {"input_kind": "observation", "input_id": hb, "input_concept_id": "hemoglobin",
         "input_name": "Hemoglobin", "input_value": 15, "input_unit": "g/dL",
         "input_day": "2024-01-10T09:30:00+02:00", "document_id": "document", "report_id": None},
        {"input_kind": "observation", "input_id": rbc, "input_concept_id": "red-blood-cell-count",
         "input_name": "Red blood cell count", "input_value": 5, "input_unit": "10^12/L",
         "input_day": "2024-01-10T09:30:00+02:00", "document_id": "document", "report_id": None},
    ]


def test_reported_calculated_globulin_wins(connection):
    add(connection, "Albumin", 40, "g/L")
    add(connection, "Total protein", 70, "g/L")
    add(connection, "Globulin, calculated", 29.9, "g/L", verification_status="extracted")
    assert "globulin-calculated" not in results(connection)


def test_equations_have_sources_and_all_names_resolve():
    concepts = {stable_concept_id(item["name"]) for item in CONCEPT_DEFINITIONS}
    for calculation in LAB_CALCULATIONS:
        assert calculation.source_url.startswith("https://")
        assert calculation.concept_id in concepts
        assert all(item.concept_id in concepts for item in calculation.inputs)


def test_reconciliation_lifecycle_on_migrated_database(tmp_path):
    from test_web_panels import build

    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        # This fixture is an isolated synthetic record, not the development DB.
        db.execute("DELETE FROM observations")
        identity = {"owner_user_id": owner, "patient_id": f"patient-{owner}", "document_id": "doc-1"}
        hb = add(db, "Hemoglobin", 150, "g/L", **identity)
        add(db, "Red blood cell count", 5, "10^12/L", **identity)
        assert refresh_derived_observations(db) == {"added": 1, "updated": 0, "removed": 0}
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}
        row = db.execute("SELECT * FROM observations WHERE extraction_method='derived_mch'").fetchone()
        assert row["value_numeric"] == 30
        db.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (row["id"],))
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}
        assert db.execute("SELECT verification_status FROM observations WHERE id=?", (row["id"],)).fetchone()[0] == "verified"

        # An unrelated newly supported equation leaves this verification alone.
        add(db, "Total cholesterol", 5, "mmol/L", **identity)
        add(db, "HDL cholesterol", 1, "mmol/L", **identity)
        assert refresh_derived_observations(db) == {"added": 2, "updated": 0, "removed": 0}
        assert db.execute("SELECT verification_status FROM observations WHERE id=?", (row["id"],)).fetchone()[0] == "verified"

        db.execute("UPDATE observations SET value_numeric=160 WHERE id=?", (hb,))
        assert refresh_derived_observations(db) == {"added": 0, "updated": 1, "removed": 0}
        changed = db.execute("SELECT * FROM observations WHERE id=?", (row["id"],)).fetchone()
        assert changed["value_numeric"] == 32
        assert changed["verification_status"] == "extracted"

        # A printed target supersedes arithmetic without changing its inputs.
        add(db, "Mean corpuscular hemoglobin", 31.9, "pg", id="printed-mch", **identity)
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 1}
        assert db.execute("SELECT COUNT(*) FROM observations WHERE extraction_method='derived_mch'").fetchone()[0] == 0
        db.execute("DELETE FROM observations WHERE concept_id='total-cholesterol'")
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 2}
        assert db.execute("SELECT COUNT(*) FROM observations WHERE extraction_method='derived_non_hdl'").fetchone()[0] == 0


def test_clinical_bmi_replaces_device_fallback_in_one_refresh(tmp_path):
    from test_device_calculations import _derived, _history
    from test_linked_metrics import _document

    settings, owner = _history(tmp_path)
    with connect(settings) as db:
        refresh_derived_observations(db)
        assert _derived(db)[0]["value"] == 20
    _document(settings, owner, "clinical-body", "Test Clinic", "consultation", "2025-01-01")
    with connect(settings) as db:
        identity = {"owner_user_id": owner, "patient_id": f"patient-{owner}", "document_id": "clinical-body",
                    "observed_at": "2025-01-01"}
        add(db, "Body weight", 100, "kg", **identity)
        add(db, "Body height", 200, "cm", **identity)
        assert refresh_derived_observations(db) == {"added": 1, "updated": 0, "removed": 1}
        assert _derived(db) == []
        row = db.execute("SELECT * FROM observations WHERE extraction_method='derived_bmi'").fetchone()
        assert row["value_numeric"] == 25
        assert row["verification_status"] == "extracted"
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}


def test_unqualified_legacy_indirect_bilirubin_is_retracted(tmp_path):
    from test_web_panels import build

    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("DELETE FROM observations")
        identity = {"owner_user_id": owner, "patient_id": f"patient-{owner}", "document_id": "doc-1"}
        add(db, "Total bilirubin", 20, "µmol/L", **identity)
        add(db, "Direct bilirubin", 5, "µmol/L", **identity)
        add(db, "Indirect bilirubin", 15, "µmol/L", extraction_method="derived_indirect_bilirubin",
            verification_status="extracted", **identity)
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 1}
        assert db.execute("SELECT COUNT(*) FROM observations WHERE extraction_method='derived_indirect_bilirubin'").fetchone()[0] == 0
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}
