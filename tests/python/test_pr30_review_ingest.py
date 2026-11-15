"""Review of PR 30, ingest side: parsers, concepts, pipeline and the lab cross-check.

Every case is synthetic.  Each one failed on the branch as it was reviewed.
"""
from __future__ import annotations

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.ingest import parsers, pipeline
from anamna.ingest.concepts import concept_for_alias, refine_definition, same_method_family, specimen_family
from anamna.ingest.pipeline import (
    DuplicateRefused,
    _copy_rows_held_by_primary,
    _shared_result_relations,
    ensure_concept,
    ensure_vendor,
    repair_observation_semantics,
)
from anamna.labsync.common import lab_row

from test_concepts_repair import _insert
from test_labsync import obs
from test_web_panels import build


# --- 1: a thousands group is not a numbered assay's number ------------------------


@pytest.mark.parametrize("line,name,value", [
    ("Вітамін B12 1 050 пг/мл 191 - 663", "Вітамін B12", 1050),
    ("Вітамін B12 1 050 пг/мл", "Вітамін B12", 1050),
    ("Імуноглобулін E загальний 2 050 МО/мл 0 - 100", "Імуноглобулін E загальний", 2050),
    ("Феритин 1 050 нг/мл 30 - 400", "Феритин", 1050),
    ("Тромбоцити 250 000 кл/мкл 150000 - 400000", "Тромбоцити", 250000),
    ("Лейкоцити 4 050 кл/мкл", "Лейкоцити", 4050),
    # The number is the assay's own: nothing is joined.
    ("CA 125 050 Од/мл", "CA 125", 50),
    ("Вітамін B 12 050 пг/мл", "Вітамін B 12", 50),
    ("Immunoglobulin G 4 050 мг/дл", "Immunoglobulin G 4", 50),
    ("Інтерлейкін 6 050 пг/мл", "Інтерлейкін 6", 50),
    # No leading zero and no interval: no proof, no join.
    ("Інтерлейкін 6 150 пг/мл", "Інтерлейкін 6", 150),
    ("Вітамін B 12 350 пг/мл 191 - 663", "Вітамін B 12", 350),
])
def test_a_thousands_group_joins_unless_it_is_the_assays_own_number(line, name, value):
    row, = parsers.parse_unit_rows(line, 1)
    assert (row.raw_name, row.value_numeric) == (name, value)


# --- 2: results shared between two documents are found by day ---------------------


def _second_document(connection, document_id="doc-2"):
    document = dict(connection.execute("SELECT * FROM documents WHERE id='doc-1'").fetchone())
    document.update(id=document_id, sha256=f"{document_id}-sha", title="A second print")
    connection.execute(
        f"INSERT INTO documents ({','.join(document)}) VALUES ({','.join('?' for _ in document)})",
        tuple(document.values()),
    )


def test_timestamped_results_still_relate_two_documents(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        _second_document(connection)
        for row_id, document_id in (("first", "doc-1"), ("second", "doc-2")):
            _insert(connection, owner, row_id, "Феритин", "ferritin", value=41.5, unit="нг/мл",
                    canonical="ng/mL", observed="2025-02-13T08:30:00")
            connection.execute("UPDATE observations SET document_id=? WHERE id=?", (document_id, row_id))
        documents = {str(row["id"]): row for row in connection.execute("SELECT * FROM documents")}
        relations: dict = {}
        _shared_result_relations(connection, owner, documents["doc-2"], "doc-2", documents, relations)
        assert [note for _confidence, note in relations.values()] == ["auto:shared_results:1"]


# --- 3: the strip's own unit is the strip ----------------------------------------


@pytest.mark.parametrize("label,unit,value_text,reference,expected", [
    ("Лейкоцити", "Leu/µL", "не виявлені", "не виявлені 25 = + 100 = ++ 500 = +++", "urine-leukocyte-esterase"),
    ("Еритроцити", "Ery/µL", "не виявлені", "не виявлені 10 = + 25 = ++ 50 = +++", "urine-erythrocytes-dipstick"),
    # A concentration alone names no method; the field does.
    ("Лейкоцити", "кл/мкл", None, "0 - 25", "urine-leukocytes"),
    ("Лейкоцити", "в п/з", "1-2", "0 - 5", "urine-leukocytes-per-high-power-field"),
])
def test_a_strip_unit_files_the_row_under_the_dipstick(tmp_path, label, unit, value_text, reference, expected):
    settings, _owner, _ = build(tmp_path)
    with connect(settings) as connection:
        vendor = ensure_vendor(connection, "Synthetic laboratory", None)
        concept_id, _unit = ensure_concept(
            connection, label, vendor, value_type="text" if value_text else "numeric", unit_raw=unit,
            clinical_type="laboratory", context="Загальний аналіз сечі", value_text=value_text,
            reference_text=reference,
        )
        assert concept_id == expected


def test_the_repair_leaves_a_checked_strip_row_where_the_person_checked_it(tmp_path):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET title='Загальний аналіз сечі' WHERE id='doc-1'")
        ensure_concept(connection, "Лейкоцити", ensure_vendor(connection, "Test Lab", None), value_type="text",
                       unit_raw="Leu/µL", context="Загальний аналіз сечі", value_text="не виявлені")
        _insert(connection, owner, "strip", "Лейкоцити", "urine-leukocyte-esterase", text="не виявлені",
                unit="Leu/µL", canonical="Leu/µL")
        connection.execute("UPDATE observations SET vendor_reference_text=? WHERE id='strip'",
                           ("не виявлені 25 = + 100 = ++ 500 = +++",))
        repair_observation_semantics(connection)
        stored = connection.execute("SELECT concept_id, verification_status FROM observations WHERE id='strip'")
        assert tuple(stored.fetchone()) == ("urine-leukocyte-esterase", "verified")


# --- 4: a method only the lab's row states is not a second test ------------------


def test_a_method_stated_by_one_side_only_still_pairs_the_reading():
    source = lab_row(test="Лейкоцити", result="25", units="кл/мкл", material="сеча",
                     norm=["Визначення за активністю лейкоцитестерази", "0 - 25"])
    printed = obs("Лейкоцити", 25.0, "кл/мкл")
    printed["specimen"] = "сеча"
    result = labsync.cross_check([source], [printed])
    assert result["counts"]["match"] == 1
    assert result["counts"]["missing"] == result["counts"]["extra"] == 0
    assert labsync._wanted_record_values(result) == {}


def test_two_stated_methods_are_two_readings():
    source = lab_row(test="Лейкоцити", result="25", units="Leu/µL", material="сеча")
    printed = obs("Лейкоцити", 25.0, "в п/з")
    printed["specimen"] = "сеча"
    result = labsync.cross_check([source], [printed])
    assert result["counts"]["match"] == 0
    assert same_method_family("Urine leukocytes", "Urine leukocytes (dipstick)")
    assert not same_method_family("Urine leukocytes (dipstick)", "Urine leukocytes per high-power field")
    # A fraction and a concentration are two quantities, not two methods.
    assert not same_method_family("Reticulocytes", "Reticulocytes, absolute")


@pytest.mark.parametrize("lab_unit,our_unit,same", [
    ("ng/mL", "", True), ("", "ng/mL", True), ("ng/mL", "нг/мл", True), ("ng/mL", "pg/mL", False),
])
def test_the_same_value_with_one_unit_missing_is_left_to_the_person(lab_unit, our_unit, same):
    parsed = labsync._record_value(lab_row(test="Ferritin", result="40", units=lab_unit))
    assert labsync._same_result(parsed, obs("Ferritin", 40.0, our_unit or None)) is same


# --- 5: a title is a preference; a row's own material binds ----------------------


@pytest.fixture
def filed(tmp_path):
    settings, _owner, _ = build(tmp_path)
    with connect(settings) as connection:
        vendor = ensure_vendor(connection, "Synthetic laboratory", None)

        def file(raw_name, **row):
            row.setdefault("clinical_type", "laboratory")
            return ensure_concept(connection, raw_name, vendor, **row)[0]

        yield file


@pytest.mark.parametrize("label,unit,title,expected", [
    ("Креатинін", "мкмоль/л", "Загальний аналіз сечі · Біохімічний аналіз", "creatinine"),
    ("Гемоглобін", "г/л", "Аналіз сечі загальний (з мікроскопією осаду) · Загальний аналіз крові", "hemoglobin"),
    ("Тиреотропний гормон (TSH)", "мкМО/мл", "Аналіз сечі; ТТГ", "thyroid-stimulating-hormone"),
    ("Сечовина", "ммоль/л", "Аналіз сечі загальний", "urea"),
    ("WBC", "10^3/µL", "Загальний аналіз сечі · Загальний аналіз крові", "white-blood-cell-count"),
    # Two definitions under one word: the title still chooses.
    ("Глюкоза", "ммоль/л", "Аналіз сечі загальний", "urine-glucose"),
    ("Лейкоцити", "кл/мкл", "Аналіз сечі загальний", "urine-leukocytes"),
])
def test_a_urine_title_never_refuses_a_labels_only_definition(filed, label, unit, title, expected):
    assert filed(label, unit_raw=unit, context=title) == expected


def test_a_row_level_specimen_still_binds(filed):
    assert filed("Креатинін", unit_raw="ммоль/л", specimen="сеча", context="Біохімічний аналіз") != "creatinine"
    assert filed("Кортизол", unit_raw="нмоль/л", specimen="слина") != "cortisol"
    # The title part that names the row is the row's own material.
    assert filed("Кортизол", unit_raw="мкг/24год", context="Кортизол вільний у добовій сечі") != "cortisol"
    assert filed("Кортизол", unit_raw="нмоль/л", context="Аналіз сечі загальний · Кортизол") == "cortisol"
    # A definition named for serum or plasma is not offered under a urine title.
    assert filed("Таурин", unit_raw="мкмоль/л", context="Амінокислоти в сечі") != "taurine-serum-or-plasma"
    assert filed("Таурин", unit_raw="мкмоль/л", context="Амінокислоти (скринінг в сироватці)") == "taurine-serum-or-plasma"


def test_a_learned_alias_obeys_the_same_rule(filed):
    # Not in the catalogue under this spelling: learned from a blood report.
    first = filed("Креатинін сироватки ензиматичний", unit_raw="мкмоль/л", context="Біохімічний аналіз")
    assert filed("Креатинін сироватки ензиматичний", unit_raw="мкмоль/л",
                 context="Загальний аналіз сечі · Біохімічний аналіз") == first


def test_a_material_category_still_binds_a_direct_lookup():
    assert concept_for_alias("Taurine", category="urinalysis") is None
    assert concept_for_alias("Creatinine", category="urinalysis") is None
    assert concept_for_alias("Creatinine", category="urinalysis", category_binds=False)["name"] == "Creatinine"
    assert concept_for_alias("WBC", category="urinalysis", category_binds=False)["name"] == "White blood cell count"


# --- 6: «-абс.» does not contradict a count --------------------------------------


@pytest.mark.parametrize("label,name", [
    ("Лейкоцити (WBC)-абс.", "White blood cell count"),
    ("Еритроцити (RBC)-абс.", "Red blood cell count"),
    ("Тромбоцити (PLT)-абс.", "Platelet count"),
    ("Лімфоцити (LYM)-абс.", "Lymphocytes, absolute"),
])
def test_an_absolute_suffix_resolves_to_the_count(label, name):
    assert concept_for_alias(label, "numeric")["name"] == name


def test_an_absolute_suffix_still_contradicts_a_percentage():
    assert concept_for_alias("Клітини (NEUT%)-абс.", "numeric") is None
    assert concept_for_alias("Гематокрит абс. (HCT)", "numeric") is None


# --- 7a, 7b: breast ultrasound sides ---------------------------------------------

_BREAST = """Права грудна залоза
Шкіра не змінена; товщиною 1,4 мм; грудна залоза звичайної форми;
Підшкірна жирова клітковина товщиною 3,1 мм;
Залозиста тканина товщиною 12,0 мм.
{left}
Шкіра не змінена; товщиною 1,2 мм;
Залозиста тканина товщиною 11,5 мм.
BI-RADS 2"""


def _breast(text):
    return [(row.raw_name, row.value_numeric, row.specimen) for row in parsers.parse_ultrasound(text, 1)]


@pytest.mark.parametrize("wrapped", [
    "Шкіра не змінена; товщиною 1,4 мм; грудна залоза звичайної форми;",
    "Шкіра не змінена; товщиною 1,4 мм;\nгрудна залоза звичайної форми;",
])
def test_a_breast_named_inside_a_section_does_not_end_the_side(wrapped):
    text = _BREAST.format(left="Ліва грудна залоза").replace(
        "Шкіра не змінена; товщиною 1,4 мм; грудна залоза звичайної форми;", wrapped)
    assert _breast(text) == [
        ("Breast skin thickness", 1.4, "права"),
        ("Breast subcutaneous fat thickness", 3.1, "права"),
        ("Breast glandular tissue thickness", 12.0, "права"),
        ("Breast skin thickness", 1.2, "ліва"),
        ("Breast glandular tissue thickness", 11.5, "ліва"),
        ("Breast BI-RADS category", 2.0, None),
    ]


@pytest.mark.parametrize("heading", ["Грудна залоза", "Грудна залоза:", "грудна залоза."])
def test_an_unsided_heading_on_its_own_line_still_ends_the_side(heading):
    rows = _breast(_BREAST.format(left=heading))
    assert ("Breast skin thickness", 1.2, None) in rows
    assert ("Breast glandular tissue thickness", 11.5, None) in rows
    assert ("Breast glandular tissue thickness", 12.0, "права") in rows


def test_a_sided_category_uses_the_side_of_every_other_breast_row():
    rows = _breast("Права грудна залоза. Шкіра товщиною 1 мм. BI-RADS 2.\n"
                   "Ліва грудна залоза. Шкіра товщиною 2 мм. BI-RADS 3.")
    assert rows == [
        ("Breast skin thickness", 1.0, "права"), ("Breast skin thickness", 2.0, "ліва"),
        ("Breast BI-RADS category", 2.0, "права"), ("Breast BI-RADS category", 3.0, "ліва"),
    ]


# --- 7c: an English categorical table ---------------------------------------------


def _categorical(text):
    return [(row.raw_name, row.value_text, row.unit_raw, row.reference_text)
            for row in parsers.parse_categorical_rows(text, 1)]


def test_the_whole_english_header_line_is_the_header():
    text = ("Test Result Units Reference\n"
            "C reactive protein 5.0 mg/L 0 - 5\n"
            "Glucose negative mg/dL negative\n"
            "Comment: positive results should be confirmed\n"
            "Culture result positive for E. coli\n"
            "Hepatitis B surface antigen Positive Negative\n"
            "HIV 1/2 antibodies not detected")
    assert _categorical(text) == [
        ("Glucose", "negative", "mg/dL", "negative"),
        ("Hepatitis B surface antigen", "Positive", None, "Negative"),
        ("HIV 1/2 antibodies", "not detected", None, None),
    ]


@pytest.mark.parametrize("text,found", [
    ("Test Result Units Reference", True), ("Analyte Result", True), ("Result Reference range", True),
    ("Investigation name  Results  Flag", True), ("Patient\nTest Result Units\nGlucose 5", True),
    ("the test result was", False), ("Test result: see the attached page", False),
    ("Your test result reference number is 12", False), ("Result units are SI", False),
])
def test_an_english_header_is_a_line_of_column_words(text, found):
    assert parsers.has_result_header(text) is found


def test_a_ukrainian_word_in_the_result_cell_is_read_as_before():
    text = "Показник Результат\nHBsAg (reactive control) не виявлено\nКолір жовтий жовтий"
    assert _categorical(text) == [
        ("HBsAg (reactive control)", "не виявлено", None, None), ("Колір", "жовтий", None, "жовтий"),
    ]


# --- 7d: an ambiguous bracket code -------------------------------------------------


@pytest.mark.parametrize("label", [
    "Простагландин (E2)", "Гепатит B (HB)", "Interferon regulatory factor (IRF)",
])
def test_an_ambiguous_code_does_not_rename_another_analyte(label):
    assert concept_for_alias(label) is None


@pytest.mark.parametrize("label,name", [
    ("Естрадіол (E2)", "Estradiol"), ("Estradiol, serum (E2)", "Estradiol"), ("E2", "Estradiol"),
    ("Гемоглобін (Hb)", "Hemoglobin"), ("Hemoglobin concentration (Hb)", "Hemoglobin"),
    # Not on the list: a code that names itself still carries a foreign spelling.
    ("Leukocytes (WBC)", "White blood cell count"),
])
def test_a_code_beside_its_own_name_still_resolves(label, name):
    assert concept_for_alias(label)["name"] == name


# --- 7e: urine, urea and uric acid -------------------------------------------------


@pytest.mark.parametrize("text,family", [
    ("Клітини епітелію сечового міхура", "urinalysis"), ("Кристали сечової кислоти", "urinalysis"),
    ("Сечовий осад", "urinalysis"), ("Аналіз сечі загальний", "urinalysis"), ("сеча", "urinalysis"),
    ("Сечовина", None), ("Сечова кислота", None), ("Рівень сечової кислоти", None),
    ("Сечовина (сироватка)", "hematology"),
])
def test_urine_is_named_by_the_bladder_and_the_sediment_not_by_urea(text, family):
    assert specimen_family(text) == family


def test_a_label_naming_urine_keeps_its_own_specimen_beside_blood():
    for label in ("Клітини епітелію сечового міхура", "Кристали сечової кислоти"):
        # Nothing in the catalogue says blood for it, and the label is not refused as foreign.
        assert pipeline.foreign_categories(label, "hematology") == frozenset()
    assert concept_for_alias("Сечова кислота", "numeric", specimen="hematology")["name"] == "Uric acid"
    assert concept_for_alias("Сечовина", "numeric", specimen="hematology")["name"] == "Urea"
    assert refine_definition(concept_for_alias("Сечовина", "numeric"))["name"] == "Urea"


# --- 7f: a ruling on a copy is held by the reading, not by its note -------------


@pytest.mark.parametrize("change", [
    {"note": "checked against the paper original"},
    {"observed_at": "2025-02-13T07:45:00"},
    {"specimen": "сироватка крові"},
])
def test_a_checked_row_on_a_copy_is_held_by_the_same_reading_of_the_original(tmp_path, change):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        _second_document(connection, "photo")
        _insert(connection, owner, "original", "Феритин", "ferritin", value=41.5, unit="нг/мл",
                canonical="ng/mL", status="extracted")
        _insert(connection, owner, "copy", "Феритин", "ferritin", value=41.5, unit="нг/мл", canonical="ng/mL")
        column, value = next(iter(change.items()))
        connection.execute(f"UPDATE observations SET document_id='photo', {column}=? WHERE id='copy'", (value,))
        rows, _doses = _copy_rows_held_by_primary(connection, "photo", "doc-1")
        assert "copy" in {row["id"] for row in rows}


@pytest.mark.parametrize("change", [
    {"value_numeric": 42.5}, {"comparator": "<"}, {"observed_at": "2025-02-14"}, {"unit_raw": "мкг/л"},
])
def test_a_checked_row_the_original_does_not_hold_still_refuses_the_duplicate(tmp_path, change):
    settings, owner, _ = build(tmp_path)
    with connect(settings) as connection:
        _second_document(connection, "photo")
        _insert(connection, owner, "original", "Феритин", "ferritin", value=41.5, unit="нг/мл",
                canonical="ng/mL", status="extracted")
        _insert(connection, owner, "copy", "Феритин", "ferritin", value=41.5, unit="нг/мл", canonical="ng/mL")
        column, value = next(iter(change.items()))
        connection.execute(f"UPDATE observations SET document_id='photo', {column}=? WHERE id='copy'", (value,))
        if column == "unit_raw":
            connection.execute("UPDATE observations SET unit_canonical='ug/L' WHERE id='copy'")
        with pytest.raises(DuplicateRefused) as refusal:
            _copy_rows_held_by_primary(connection, "photo", "doc-1")
        assert refusal.value.args[0] == "dup.error_ruled"

