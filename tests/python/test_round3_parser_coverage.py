"""Synthetic source-completeness regressions; separate results keep identity."""
from dataclasses import replace

import pytest

from anamna.ingest import parsers


def _result(**changes):
    result = parsers.ParsedObservation(
        raw_name="Hemoglobin", value_numeric=100, value_text=None,
        comparator=None, unit_raw="g/L", reference_text=None,
        reference_low=None, reference_high=None, page_number=1,
        evidence_text="Synthetic hemoglobin result", confidence=0.9,
    )
    return replace(result, **changes)


def test_equal_numeric_limits_on_the_same_page_are_distinct_results():
    rows = parsers.parse_document("Synthetic lab", "laboratory", [{
        "page_number": 1,
        "native_text": "Hemoglobin <100 g/L\nHemoglobin >100 g/L",
    }])
    assert {(row.value_numeric, row.comparator) for row in rows} == {(100, "<"), (100, ">")}


@pytest.mark.parametrize("changes", [
    {"comparator": "<"}, {"comparator": ">="},
    {"observed_at": "2025-01-01T09:00:00+02:00"},
    {"unit_raw": "g/dL"}, {"value_text": "reported text"},
    {"specimen": "serum"}, {"section": "second sample"},
])
def test_deduplication_never_discards_a_distinct_source_quantity(changes):
    first = _result()
    second = _result(**changes)
    assert parsers._distinct_rows([first, second]) == [first, second]


def test_native_and_ocr_repetition_of_the_same_result_is_still_deduplicated():
    first = _result()
    second = replace(first, extraction_method="embedded_image_ocr_parser", confidence=0.8)
    assert parsers._distinct_rows([first, second]) == [first]


def test_absent_and_empty_text_are_not_extra_measurements():
    first = _result()
    assert parsers._distinct_rows([first, _result(value_text="")]) == [first]


def test_glued_value_artifact_is_still_removed_when_its_unit_is_wrong():
    first = _result()
    artifact = _result(raw_name="Hemoglobin 100", unit_raw="%")
    assert parsers._distinct_rows([first, artifact]) == [first]


def test_glued_label_filter_does_not_override_a_different_limit_or_time():
    first = _result()
    second = _result(raw_name="Hemoglobin 100", comparator="<")
    third = _result(raw_name="Hemoglobin 100", observed_at="2025-01-01T10:00:00Z")
    assert parsers._distinct_rows([first, second, third]) == [first, second, third]


@pytest.mark.parametrize("name", [
    "CA 125", "Interleukin 6", "Інтерлейкін 6", "Вітамін B 12",
    "Immunoglobulin G 4",
])
def test_zero_padded_result_never_consumes_a_numbered_assay_name(name):
    row, = parsers.parse_unit_rows(f"{name} 050 pg/mL", 1)
    assert row.raw_name == name and row.value_numeric == 50


def test_separated_cell_count_still_joins_its_thousands_group():
    row, = parsers.parse_unit_rows("Тромбоцити 250 000 кл/мкл", 1)
    assert row.raw_name == "Тромбоцити" and row.value_numeric == 250000


@pytest.mark.parametrize("name", ["Prothrombin time", "Thrombin time"])
@pytest.mark.parametrize("unit", ["s", "с"])
def test_seconds_are_preserved_outside_a_provider_specific_layout(name, unit):
    row, = parsers.parse_unit_rows(f"{name} 14 {unit}", 1)
    assert row.raw_name == name and row.value_numeric == 14 and row.unit_raw == unit


def test_latin_seconds_do_not_enable_antibiotic_disk_potencies():
    assert parsers.parse_unit_rows("Amikacin 30 µg", 1) == []
    assert parsers.parse_unit_rows("Amikacin 30 S", 1) == []


def test_single_letter_seconds_never_consume_an_analyte_name_suffix():
    row, = parsers.parse_unit_rows("Vitamin C 50 µmol/L", 1)
    assert row.raw_name == "Vitamin C" and row.unit_raw == "µmol/L"


@pytest.mark.parametrize("header", [
    "Test Result Reference range", "Analyte Result Units", "Investigation Result Reference",
])
def test_english_categorical_results_survive_the_same_source_path_as_numeric_rows(header):
    rows = parsers.parse_document("Synthetic lab", "laboratory", [{
        "page_number": 1,
        "native_text": header + "\nHepatitis B surface antigen Negative\nHepatitis C antibodies Not detected",
    }])
    assert [(row.raw_name, row.value_text) for row in rows] == [
        ("Hepatitis B surface antigen", "Negative"),
        ("Hepatitis C antibodies", "Not detected"),
    ]


def test_english_qualitative_reference_and_footer_are_not_extra_results():
    rows = parsers.parse_document("Synthetic lab", "laboratory", [{
        "page_number": 1,
        "native_text": "Test Result Reference\nHepatitis B surface antigen Positive Negative\n"
                       "Results are not a diagnosis\nReference Negative",
    }])
    assert len(rows) == 1
    assert rows[0].value_text == "Positive" and rows[0].reference_text == "Negative"


def _breast_rows(text):
    return [row for row in parsers.parse_ultrasound(text, 1) if row.raw_name == "Breast BI-RADS category"]


def test_separately_labelled_breast_assessments_keep_both_values_and_sides():
    rows = _breast_rows("Права грудна залоза. BI-RADS 2.\nЛіва грудна залоза. BI-RADS 3.")
    assert [(row.value_numeric, row.specimen) for row in rows] == [(2, "права"), (3, "ліва")]


def test_equal_bilateral_categories_are_still_two_separately_labelled_assessments():
    rows = _breast_rows("Права грудна залоза. BI-RADS 2.\nЛіва грудна залоза. BI-RADS 2.")
    assert [(row.value_numeric, row.specimen) for row in rows] == [(2, "права"), (2, "ліва")]


def test_single_overall_breast_category_does_not_acquire_the_last_breasts_side():
    row, = _breast_rows("Права грудна залоза.\nЛіва грудна залоза.\nВисновок: BI-RADS 2.")
    assert row.value_numeric == 2 and row.specimen is None


def test_bilateral_categories_do_not_consume_an_additional_overall_assessment():
    rows = _breast_rows("Права грудна залоза. BI-RADS 2.\nЛіва грудна залоза. BI-RADS 3.\nВисновок: BI-RADS 3.")
    assert [(row.value_numeric, row.specimen) for row in rows] == [(2, "права"), (3, "ліва"), (3, None)]


def test_an_unsided_breast_heading_ends_the_previous_side_scope():
    rows = parsers.parse_ultrasound(
        "Права грудна залоза. Шкіра товщиною 1 мм.\n"
        "Грудна залоза. Підшкірна жирова клітковина товщиною 8 мм.", 1,
    )
    skin, = [row for row in rows if row.raw_name == "Breast skin thickness"]
    fat, = [row for row in rows if row.raw_name == "Breast subcutaneous fat thickness"]
    assert skin.specimen == "права"
    assert fat.specimen is None
    assert fat.note == "Laterality could not be established from source text."


def test_an_unreadable_breast_side_does_not_imply_the_opposite_side():
    rows = parsers.parse_ultrasound(
        "Ліва грудна залоза. Шкіра товщиною 1 мм.\n"
        "Грудна залоза. Шкіра товщиною 2 мм.", 1,
    )
    skin = [row for row in rows if row.raw_name == "Breast skin thickness"]
    assert [(row.value_numeric, row.specimen) for row in skin] == [(1, "ліва"), (2, None)]


def test_unsided_breast_heading_cannot_create_bilateral_category_evidence():
    rows = _breast_rows("Права грудна залоза. BI-RADS 2.\nГрудна залоза. BI-RADS 3.")
    assert [(row.value_numeric, row.specimen) for row in rows] == [(2, None), (3, None)]
