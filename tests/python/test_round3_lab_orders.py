"""Independent synthetic source-row, specimen and order-identity regressions."""
from __future__ import annotations

import json

import pytest

from anamna import labsync, testplan
from anamna.db import connect
from anamna.derived import refresh_derived_observations
from anamna.labsync.common import iso_day, lab_row, parse_result
from anamna.labsync.expert import Client as ExpertClient
from anamna.labsync.synevo import Client as SynevoClient
from test_labsync import make, obs, seed_doc
from test_testplan_aliases import item


@pytest.mark.parametrize("printed,number,sign", [
    (0, 0, None), ("0", 0, None), ("<0", 0, "<"),
    ("1.25e-3", .00125, None), (">=2E+2", 200, ">="),
    (".5", .5, None), ("−1,5", -1.5, None),
])
def test_complete_numeric_source_values_keep_zero_sign_and_scientific_notation(printed, number, sign):
    assert parse_result(printed) == (sign, number)


@pytest.mark.parametrize("printed", ["1e999", "NaN", "inf", "1:80", "1e3 cells", "negative"])
def test_nonfinite_or_non_numeric_source_results_do_not_become_numbers(printed):
    assert parse_result(printed) == (None, None)


def test_both_structured_provider_adapters_keep_numeric_zero():
    [expert] = ExpertClient._rows({"name": "Synthetic panel", "indicators": [
        {"id": 1, "name": "Synthetic count", "value": 0, "unit": "%"},
    ]})
    [synevo] = SynevoClient._rows({"Results": [{"Name": "Synthetic count", "Val": 0, "Unit": "%"}]})
    for source in (expert, synevo):
        parsed = labsync._record_value(source)
        assert parsed.value_numeric == 0 and parsed.value_text is None


def test_zero_provider_parameter_id_is_preserved_with_the_zero_result():
    row = lab_row(test="Synthetic count", result=0, idtest=0)
    assert row["idtest"] == "0" and parse_result(row["result"]) == (None, 0)


@pytest.mark.parametrize("source,expected", [
    ("2024-02-29", "2024-02-29"), ("2024-02-29T23:15:00+02:00", "2024-02-29"),
    ("2024-02-29T21:15:00Z", "2024-02-29"), ("2025-02-29", ""),
    ("2025-04-31", ""), ("2025-00-12", ""), ("2025-01-01 not-a-time", ""),
])
def test_source_order_dates_validate_the_calendar_and_preserve_written_day(source, expected):
    assert iso_day(source) == expected
    assert labsync._record_day({"dates": [source]}) == (expected or None)


def test_explicit_provider_material_reaches_the_stored_provisional_observation(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    source = lab_row(test="Creatinine", result="80", units="µmol/L", material="urine", packet="Synthetic panel")
    with connect(settings) as db:
        document = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-801", "dates": ["2025-01-01"], "ordered_at": "2025-01-01"}, [source],
        )
        result = db.execute("SELECT specimen,verification_status,concept_id,value_numeric FROM observations WHERE document_id=?", (document,)).fetchone()
    assert result["specimen"] == "urine" and result["verification_status"] == "extracted"
    assert result["concept_id"] != "creatinine" and result["value_numeric"] == 80


def test_a_smear_site_does_not_leak_into_the_next_packet():
    rows = [lab_row(test="ТОЧКА 2", result="VAGINA", packet="Smear"),
            lab_row(test="Лейкоцити", result="2", packet="Smear"),
            lab_row(test="Creatinine", result="80", units="µmol/L", material="serum", packet="Chemistry")]
    parsed = labsync._record_values(rows)
    assert parsed[1][1].specimen == "VAGINA"
    assert parsed[2][1].specimen == "serum"


def test_explicit_source_packet_context_reaches_the_stored_observation(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    source = lab_row(test="Glucose", result="0", units="mmol/L", packet="Urine analysis")
    parsed = labsync._record_value(source)
    assert parsed.section == "Urine analysis" and parsed.specimen is None
    with connect(settings) as db:
        document = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-803", "dates": ["2025-01-01"]}, [source],
        )
        result = db.execute("SELECT specimen,concept_id,verification_status FROM observations WHERE document_id=?", (document,)).fetchone()
        assert labsync._refresh_record_values(settings, db) == 0
        assert tuple(db.execute("SELECT specimen,concept_id,verification_status FROM observations WHERE document_id=?", (document,)).fetchone()) == tuple(result)
    assert tuple(result) == ("сеча", "urine-glucose", "extracted")
    assert labsync._record_value({**source, "packet": "Blood and urine"}).specimen is None
    assert labsync._record_value({**source, "material": "serum"}).specimen == "serum"


def test_source_method_metadata_survives_separately_from_reference_bounds(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    method = "Лейкоцити визначаються за активністю лейкоцитестерази."
    source = lab_row(test="Urine leukocytes", result="negative", units="cells/µL",
                     packet="Urine analysis", norm=[method])
    parsed = labsync._record_value(source)
    assert parsed.note == method and parsed.reference_text is None
    with connect(settings) as db:
        document = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-804", "dates": ["2025-01-01"]}, [source],
        )
        assert db.execute("SELECT note FROM observations WHERE document_id=?", (document,)).fetchone()[0] == method
        db.execute("UPDATE observations SET note='Reviewer note' WHERE document_id=?", (document,))
        labsync._refresh_record_values(settings, db)
        note = db.execute("SELECT note FROM observations WHERE document_id=?", (document,)).fetchone()[0]
        assert note == f"Reviewer note; {method}"
        labsync._refresh_record_values(settings, db)
        assert db.execute("SELECT note FROM observations WHERE document_id=?", (document,)).fetchone()[0] == note


def test_independent_method_rows_stay_beside_a_report_without_forcing_duplicate_retirement(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    pdf = seed_doc(settings, owner, vendor="Esculab", order="synthetic-805", day="2025-01-01",
                   values=[("Ferritin", 10., "ng/mL", None)])
    rows = [lab_row(test="Ferritin", result="10", units="ng/mL"),
            lab_row(test="Urine leukocytes", result="negative", units="cells/µL", packet="Urine analysis",
                    norm=["Лейкоцити визначаються за активністю лейкоцитестерази."])]
    check = labsync.cross_check(rows, [obs("Ferritin", 10., "ng/mL")])
    row = {"document_id": pdf, "provider": "esculab", "order_id": "synthetic-805"}
    with connect(settings) as db:
        record = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-805", "ordered_at": "2025-01-01"}, rows,
        )
        assert labsync._keep_unread_record_values(db, owner, row, check) == 1
        held = db.execute("SELECT concept_id,verification_status FROM observations WHERE document_id=?", (record,)).fetchall()
        assert [tuple(result) for result in held] == [("urine-leukocyte-esterase", "extracted")]
        source = db.execute("SELECT source_path,duplicate_of_document_id FROM documents WHERE id=?", (record,)).fetchone()
        assert source["duplicate_of_document_id"] is None
        assert len(json.loads(labsync.resolve_source_path(settings, source["source_path"]).read_text(encoding="utf-8"))["rows"]) == 2
        assert db.execute("SELECT COUNT(*) FROM observations WHERE document_id=?", (pdf,)).fetchone()[0] == 1
        assert labsync._keep_unread_record_values(db, owner, row, check) == 0


def test_explicit_incompatible_material_also_ends_a_sticky_site_inside_a_packet():
    rows = [lab_row(test="ТОЧКА 2", result="VAGINA", packet="Combined visit"),
            lab_row(test="Лейкоцити", result="2", material="урогенітальний зішкріб", packet="Combined visit"),
            lab_row(test="Creatinine", result="80", units="µmol/L", material="serum", packet="Combined visit"),
            lab_row(test="Synthetic next result", result="1", packet="Combined visit")]
    values = labsync._record_values(rows)
    assert values[1][1].specimen == "VAGINA"
    assert values[2][1].specimen == "serum"
    assert values[3][1].specimen is None


def test_rereading_an_existing_provisional_numeric_text_keeps_its_value(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    source = lab_row(test="Synthetic quantitative result", result="<1e-3", units="g/L")
    with connect(settings) as db:
        document = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-802", "dates": ["2025-01-01"], "ordered_at": "2025-01-01"}, [source],
        )
        # The prior reader stored the complete source string as text.
        db.execute("UPDATE observations SET value_numeric=NULL,value_text='<1e-3',value_type='text',comparator=NULL WHERE document_id=?", (document,))
        assert labsync._refresh_record_values(settings, db) == 1
        value = db.execute("SELECT value_numeric,value_text,value_type,comparator,verification_status FROM observations WHERE document_id=?", (document,)).fetchone()
        assert tuple(value) == (.001, None, "numeric", "<", "extracted")
        assert labsync._refresh_record_values(settings, db) == 0


def test_confirming_a_unitless_api_result_does_not_confirm_its_inferred_catalog_unit(tmp_path):
    settings, owner, _ = make(tmp_path, enable=())
    rows = [lab_row(test="Creatinine", result="80", material="serum"),
            lab_row(test="Hemoglobin", result="15", material="blood"),
            lab_row(test="Red blood cell count", result="5", units="10^12/L", material="blood")]
    with connect(settings) as db:
        document = labsync._file_lab_record(
            settings, db, owner, "esculab", f"patient-{owner}",
            {"order_id": "synthetic-803", "dates": ["2025-01-01"], "ordered_at": "2025-01-01"}, rows,
        )
        unitless = db.execute("SELECT unit_raw,unit_canonical FROM observations WHERE document_id=? AND concept_id='creatinine'", (document,)).fetchone()
        assert unitless["unit_raw"] is None and unitless["unit_canonical"] is not None
        db.execute("UPDATE observations SET verification_status='verified' WHERE document_id=?", (document,))
        refresh_derived_observations(db)
        assert db.execute("SELECT COUNT(*) FROM observations WHERE document_id=? AND extraction_method IN ('derived_ckd_epi_2021','derived_mch','derived_mchc')", (document,)).fetchone()[0] == 0


@pytest.mark.parametrize("material,specimen", [("urine", "serum"), ("CERVIX", "VAGINA")])
def test_equal_named_results_from_distinct_samples_cannot_be_cross_verified(material, specimen):
    source = lab_row(test="Synthetic quantity", result="4", units="g/L", material=material)
    observation = {**obs("Synthetic quantity", 4., "g/L"), "specimen": specimen}
    result = labsync.cross_check([source], [observation])
    assert result["counts"]["match"] == 0
    assert result["counts"]["missing"] == result["counts"]["extra"] == 1


def test_a_manual_differential_does_not_match_an_automated_result_by_loose_name():
    source = lab_row(test="Neutrophils (manual differential)", result="50", units="%")
    result = labsync.cross_check([source], [obs("Neutrophils", 50., "%")])
    assert result["counts"]["match"] == 0
    assert result["counts"]["missing"] == result["counts"]["extra"] == 1


def test_a_missing_named_analyte_is_not_suppressed_by_an_unrelated_equal_number():
    result = labsync.cross_check([lab_row(test="Ferritin", result="40", units="ng/mL")],
                                [obs("C-reactive protein", 40., "ng/mL")])
    wanted = labsync._wanted_record_values(result)
    assert len(wanted) == 1
    assert next(iter(wanted.values())).raw_name == "Ferritin"


def test_a_censored_lab_result_is_not_suppressed_by_an_exact_value():
    parsed = labsync._record_value(lab_row(test="Ferritin", result="<1", units="ng/mL"))
    assert not labsync._same_result(parsed, obs("Ferritin", 1., "ng/mL"))


def test_duplicate_result_check_reads_the_crosscheck_view_shape():
    source = labsync._record_value(lab_row(test="Ferritin", result="1", units="ng/mL"))
    assert labsync._same_result(source, labsync._obs_view(obs("Ferritin", 1., "ng/mL")))
    assert not labsync._same_result(source, labsync._obs_view(obs("C-reactive protein", 1., "ng/mL")))


@pytest.mark.parametrize("result,number", [("negative", None), ("1", 1.)])
def test_unresolved_different_test_names_are_not_suppressed_by_coincident_results(result, number):
    parsed = labsync._record_value(lab_row(test="Synthetic antibody A", result=result))
    other = obs("Synthetic antibody B", number, "")
    other["value_text"] = result if number is None else None
    assert not labsync._same_result(parsed, other)
    other["raw_name"] = parsed.raw_name
    assert labsync._same_result(parsed, other)


def test_known_aliases_can_still_identify_the_same_result():
    parsed = labsync._record_value(lab_row(test="Ferritin", result="1", units="ng/mL"))
    assert labsync._same_result(parsed, obs("Феритин", 1., "ng/mL"))


def test_qualitative_results_with_different_printed_units_remain_independent():
    parsed = labsync._record_value(lab_row(test="Synthetic antibody", result="negative", units="AU/mL"))
    other = obs("Synthetic antibody", None, "index")
    other["value_text"] = "negative"
    assert not labsync._same_result(parsed, other)


@pytest.mark.parametrize("curated_id", ["32", "unseen-32"])
def test_explicit_order_material_binds_curated_and_fallback_parameter_identity(curated_id):
    source = {**item("test", "Glucose", (curated_id, "Glucose")), "material": ["urine"]}
    [keyed] = testplan.keyed([source], "esculab", "Esculab", {})
    assert "blood-glucose" not in keyed["keys"]
    assert "estimated-glomerular-filtration-rate-ckd-epi-2021" not in keyed["keys"]
    if curated_id == "unseen-32":
        assert keyed["keys"] == ["urine-glucose"]


def test_explicit_result_material_prevents_learning_the_serum_identity():
    learned = {}
    testplan._learn_row(learned, lab_row(test="Creatinine", result="40", material="urine", idtest="synthetic"),
                        "esculab", {"creatinine": "creatinine"}, {40.: ["creatinine"]})
    assert "id:synthetic" not in learned


@pytest.mark.parametrize("label", ["Глюкоза", "Glucose"])
@pytest.mark.parametrize("blood_material", [["serum"], []])
def test_shared_parameter_id_does_not_borrow_the_first_items_specimen(label, blood_material):
    blood = {**item("blood", label, ("unseen", label)), "material": blood_material}
    urine = {**item("urine", label, ("unseen", label)), "material": ["urine"]}
    forward = {entry["id"]: entry["keys"] for entry in testplan.keyed([blood, urine], "esculab", "Esculab", {})}
    reverse = {entry["id"]: entry["keys"] for entry in testplan.keyed([urine, blood], "esculab", "Esculab", {})}
    assert forward == reverse
    assert forward["blood"] == ["blood-glucose"]
    assert forward["urine"] == ["urine-glucose"]
