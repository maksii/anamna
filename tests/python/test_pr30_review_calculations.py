"""Review findings on the metric-connections change: verdicts, catalogue keys, calculations."""

from __future__ import annotations

import json

import pytest

from anamna import testplan
from anamna.db import connect, utc_now
from anamna.derived import DERIVED_EGFR_METHOD, refresh_derived_observations
from anamna.ingest.concepts import stable_concept_id
from anamna.reference import evaluate
from anamna.security import create_user

from test_web_panels import PASSWORD, build

EGFR = "estimated-glomerular-filtration-rate-ckd-epi-2021"
REPORTED_EGFR = "estimated-glomerular-filtration-rate-reported"
EGFR_UNIT = "mL/min/1.73m²"


# --- 1. eGFR in pregnancy keeps what the laboratory flagged ---------------------------


@pytest.mark.parametrize("concept_id", [EGFR, REPORTED_EGFR])
@pytest.mark.parametrize("flag", ["low", None])
def test_pregnancy_keeps_the_laboratorys_low_egfr(tmp_path, concept_id, flag):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        said = {"value_numeric": 45, "unit": EGFR_UNIT, "age_years": 34, "sex": "female",
                "vendor_low": 60, "vendor_interpretation": flag}
        usual = evaluate(db, concept_id, **said)
        pregnant = evaluate(db, concept_id, **said, clinical_context={"pregnant": True})
    assert usual["interpretation"] != "unjudged"
    assert (pregnant["interpretation"], pregnant["authority"]) == ("low", "vendor")
    assert pregnant["curated_blocked"] == "pregnancy_egfr"
    assert pregnant["unjudged_reason"] is None
    assert pregnant["vendor_status"] == "low"


def test_pregnancy_egfr_with_nothing_flagged_stays_unjudged_and_cites_the_guidance(tmp_path):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        for vendor in ({}, {"vendor_low": 60, "vendor_interpretation": "within_vendor_range"}):
            verdict = evaluate(db, EGFR, value_numeric=100, unit=EGFR_UNIT, age_years=34, sex="female",
                               clinical_context={"pregnant": True}, **vendor)
            assert (verdict["interpretation"], verdict["authority"]) == ("unjudged", "none")
            assert verdict["unjudged_reason"] == verdict["curated_blocked"] == "pregnancy_egfr"
            assert verdict["source_id"] == "nice-ng3-egfr-pregnancy"


# --- 2-4, 9. catalogue keys -----------------------------------------------------------


def item(item_id, name, *parameters, material=()):
    return {"id": item_id, "code": item_id, "name": name, "price": 100.0, "final_price": 100.0, "fees": [],
            "parameters": [{"id": pid, "name": pname} for pid, pname in parameters], "synonyms": [],
            "material": list(material)}


def keys(lab, *items):
    return {i["id"]: i for i in testplan.keyed(list(items), lab, lab.title(), {}, {}, {})}


CBC = (("268", "Гемоглобін (HGB)"), ("269", "Еритроцити (RBC)"), ("276", "Тромбоцити (PLT)"),
       ("280", "Лейкоцити (WBC)"))


def test_a_package_on_several_specimens_still_covers_its_blood_count():
    offerings = keys(
        "esculab",
        item("cbc", "Загальний аналіз крові", *CBC, material=["цільна кров ЗАК"]),
        item("package", "Пакет №199. Інтимне здоров'я (ПЛР, зішкріб із урогенітального тракту)", *CBC,
             ("9001", "Chlamydia trachomatis (ПЛР)"),
             material=["сеча", "зішкріб із урогенітального тракту", "цільна кров ЗАК"]),
    )
    counted = [["hemoglobin"], ["red-blood-cell-count"], ["platelet-count"], ["white-blood-cell-count"]]
    assert offerings["cbc"]["parameter_keys"] == counted
    assert offerings["package"]["parameter_keys"][:4] == counted


def test_the_material_still_refuses_a_blood_concept_in_a_urine_test():
    assert testplan._matches_specimen("blood-glucose", "Глюкоза", "", "сеча") is False
    assert testplan._matches_specimen("blood-glucose", "Глюкоза", "", "сироватка крові") is True
    # Two specimens: the material cannot say which, and the title is not asked.
    assert testplan._matches_specimen("blood-glucose", "Глюкоза", "Загальний аналіз сечі",
                                      "сеча + сироватка крові") is True


@pytest.mark.parametrize("lab,parameter,name,target", [
    ("synevo", "2482", "ANA. ДНК двоспіральна (dsDNA), антитіла IgG", "double-stranded-dna-antibodies"),
    ("synevo", "9219", "Мієлопероксидаза (MPO), антитіла IgG", "myeloperoxidase-antibodies"),
    ("synevo", "9220", "Протеїназа 3 (PR3), антитіла IgG", "proteinase-3-antibodies"),
    ("synevo", "name:mpo-anca", "Мієлопероксидаза (MPO), антитіла IgG_ANCA", "myeloperoxidase-antibodies"),
    ("synevo", "name:pr3-anca", "Протеїназа 3 (PR3), антитіла IgG_ANCA", "proteinase-3-antibodies"),
    ("esculab", "1681", "Антитіла IgG до протеїнази (PR3, с-ANCA) EliA", "proteinase-3-antibodies"),
])
def test_an_igg_autoantibody_row_keys_to_its_classless_concept(lab, parameter, name, target):
    assert keys(lab, item("offering", name, (parameter, name)))["offering"]["parameter_keys"] == [[target]]


def test_a_class_or_method_the_concept_lacks_still_keeps_the_labs_own_key():
    offerings = keys(
        "esculab",
        item("igg", "Хелікобактеріоз (Helicobacter pylori), IgG",
             ("unknown-igg", "Ig G до Хелікобактер пілорі (Helicobacter Pylori)")),
        # Esculab prints the class with a Cyrillic «М».
        item("igm", "Хелікобактеріоз (Helicobacter pylori), IgM",
             ("unknown-igm", "Ig М до Хелікобактер пілорі (Helicobacter pylori)")),
        item("mpo-igm", "Мієлопероксидаза", ("unknown-mpo", "Мієлопероксидаза (MPO), антитіла IgM")),
    )
    assert offerings["igg"]["keys"] == ["esculab:unknown-igg"]
    assert offerings["igm"]["keys"] == ["esculab:unknown-igm"]
    assert offerings["mpo-igm"]["keys"] == ["esculab:unknown-mpo"]


def test_a_single_parameter_takes_its_title_when_it_names_the_same_thing():
    offerings = keys(
        "esculab",
        item("hla", "Виявлення носійства гену HLA B-27",
             ("338", "Виявлення носійства HLA-B27-антигену (ПЛР) (якісне визначення)"), material=["цільна кров"]),
        item("retic", "Ретикулоцити", ("unknown-rethe", "Гемоглобін (RET-He)")),
        item("homa2", "Індекс HOMA", ("unknown-homa2", "Індекс HOMA2")),
        item("placeholder", "Калій", ("unknown-placeholder", "Результат")),
    )
    assert offerings["hla"]["keys"] == ["hla-b27"]
    assert testplan.optimise([offerings["hla"]], {"hla-b27"})["missing"] == []
    assert offerings["retic"]["keys"] == ["esculab:unknown-rethe"]
    assert offerings["homa2"]["keys"] == ["esculab:unknown-homa2"]
    assert offerings["placeholder"]["keys"] == ["potassium"]


def test_esculab_reticulocyte_count_and_percentage_are_two_results():
    offering = keys("esculab", item("ret", "Загальний аналіз крові з підрахунком ретикулоцитів",
                                    ("546", "Ретикулоцити %"), ("547", "Ретикулоцити"),
                                    material=["цільна кров ЗАК"]))["ret"]
    assert offering["parameter_keys"] == [["reticulocytes"], ["reticulocytes-absolute"]]


# --- 6-8. derived results -------------------------------------------------------------


def _observe(db, owner, row_id, name, value, unit, document="doc-1", **more):
    row = {
        "id": row_id, "owner_user_id": owner, "patient_id": f"patient-{owner}", "document_id": document,
        "page_number": 1, "concept_id": stable_concept_id(name), "raw_name": name, "value_type": "numeric",
        "value_numeric": value, "unit_raw": unit, "observed_at": "2025-02-13",
        "verification_status": "verified", "extraction_method": "native_pdf_text_parser", "confidence": 0.9,
        "evidence_text": f"{name} {value}", "parser_version": "test", "created_at": utc_now(), **more,
    }
    db.execute(f"INSERT INTO observations({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))


def _derived(db, method):
    return db.execute("SELECT * FROM observations WHERE extraction_method=? ORDER BY id", (method,)).fetchall()


def test_a_calculated_result_is_stored_at_the_precision_a_laboratory_prints(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("DELETE FROM observations")
        _observe(db, owner, "plt", "Platelet count", 253, "10^9/L")
        _observe(db, owner, "mpv", "Mean platelet volume", 7, "fL")
        _observe(db, owner, "hgb", "Hemoglobin", 151, "g/L")
        _observe(db, owner, "rbc", "Red blood cell count", 4.7, "10^12/L")
        _observe(db, owner, "wbc", "White blood cell count", 6.84, "10^9/L")
        _observe(db, owner, "neu", "Neutrophils", 51.3, "%")
        refresh_derived_observations(db)
        [pct] = _derived(db, "derived_plateletcrit")
        [mch] = _derived(db, "derived_mch")
        [neutrophils] = _derived(db, "derived_differential_absolute")
    assert pct["value_numeric"] == 0.18  # 0.1771 at four places
    assert mch["value_numeric"] == 32.1
    assert neutrophils["value_numeric"] == 3.51


def _second_account(settings):
    other = create_user(settings, "second@example.test", "Second", PASSWORD)
    with connect(settings) as db:
        db.execute("""INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
                      VALUES (?, ?, 'Second', '1985-01-01', 'female', ?)""", (f"patient-{other}", other, utc_now()))
        db.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status)
               SELECT 'doc-2', ?, ?, vendor_id, 'second.pdf', source_path, mime_type, byte_size, 'sha-2',
                      page_count, title, clinical_type, extraction_strategy, classification_confidence,
                      report_date, imported_at, status FROM documents WHERE id='doc-1'""",
            (other, f"patient-{other}"),
        )
        _observe(db, other, "second-creatinine", "Creatinine", 70, "мкмоль/л", document="doc-2")
        _observe(db, other, "second-plt", "Platelet count", 250, "10^9/L", document="doc-2")
        _observe(db, other, "second-mpv", "Mean platelet volume", 10, "fL", document="doc-2")
    return other


def test_a_refresh_limited_to_one_account_leaves_the_others_alone(tmp_path):
    settings, owner, _ = build(tmp_path)
    other = _second_account(settings)
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        assert refresh_derived_observations(db, owner_user_id=other) == {"added": 2, "updated": 0, "removed": 0}
        assert {row["owner_user_id"] for row in db.execute(
            "SELECT owner_user_id FROM observations WHERE substr(extraction_method, 1, 8)='derived_'")} == {other}
        # The first account's refresh neither sees nor removes the second's results.
        assert refresh_derived_observations(db, owner_user_id=owner) == {"added": 1, "updated": 0, "removed": 0}
        assert refresh_derived_observations(db, owner_user_id=owner) == {"added": 0, "updated": 0, "removed": 0}
        assert len(_derived(db, DERIVED_EGFR_METHOD)) == 2
        # The whole database, as start-up asks, finds nothing left to do.
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}
        db.execute("UPDATE observations SET verification_status='rejected' WHERE id='second-mpv'")
        assert refresh_derived_observations(db, owner_user_id=owner) == {"added": 0, "updated": 0, "removed": 0}
        assert refresh_derived_observations(db, owner_user_id=other) == {"added": 0, "updated": 0, "removed": 1}


def _verified_egfr(db):
    db.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
    refresh_derived_observations(db)
    [row] = _derived(db, DERIVED_EGFR_METHOD)
    db.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (row["id"],))
    return row


def test_a_result_stored_before_inputs_were_recorded_keeps_its_review(tmp_path):
    """As the previous release left it: the input's own line as evidence, no
    recorded inputs, no sample context."""
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE observations SET specimen='сироватка крові' WHERE concept_id='creatinine'")
        row = _verified_egfr(db)
        db.execute("""UPDATE observations SET evidence_text='Creatinine evidence', calculation_inputs_json=NULL,
                      specimen=NULL WHERE id=?""", (row["id"],))
        assert refresh_derived_observations(db) == {"added": 0, "updated": 1, "removed": 0}
        [after] = _derived(db, DERIVED_EGFR_METHOD)
        assert after["verification_status"] == "verified"
        assert after["value_numeric"] == row["value_numeric"]
        assert after["evidence_text"] == row["evidence_text"]
        assert after["specimen"] == "сироватка крові"
        assert json.loads(after["calculation_inputs_json"])[0]["input_id"] == "obs-2"
        assert refresh_derived_observations(db) == {"added": 0, "updated": 0, "removed": 0}


def test_a_change_in_how_the_evidence_is_written_keeps_the_review(tmp_path):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        _verified_egfr(db)
        # The input's source line is re-read and its unit folded differently:
        # the same number, input, unit and date.
        db.execute("""UPDATE observations SET evidence_text='Креатинін 88 мкмоль/л', unit_canonical='umol/l'
                      WHERE concept_id='creatinine'""")
        assert refresh_derived_observations(db) == {"added": 0, "updated": 1, "removed": 0}
        [after] = _derived(db, DERIVED_EGFR_METHOD)
        assert after["verification_status"] == "verified"
        assert "Креатинін 88 мкмоль/л" in after["evidence_text"]


def test_a_changed_input_still_reopens_the_review(tmp_path):
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        row = _verified_egfr(db)
        # 88 -> 88.2 µmol/L rounds to the same eGFR; the input is not the one reviewed.
        db.execute("UPDATE observations SET value_numeric=88.2 WHERE concept_id='creatinine'")
        refresh_derived_observations(db)
        [same_number] = _derived(db, DERIVED_EGFR_METHOD)
        assert same_number["value_numeric"] == row["value_numeric"]
        assert same_number["verification_status"] == "extracted"
        db.execute("UPDATE observations SET verification_status='verified' WHERE id=?", (row["id"],))
        db.execute("UPDATE observations SET value_numeric=120 WHERE concept_id='creatinine'")
        refresh_derived_observations(db)
        [changed] = _derived(db, DERIVED_EGFR_METHOD)
        assert changed["value_numeric"] < row["value_numeric"]
        assert changed["verification_status"] == "extracted"
