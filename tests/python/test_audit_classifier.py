"""A results table that mentions another kind of document is still a results table.

Every text below is synthetic -- invented patient, invented numbers -- shaped
like the page it stands for.
"""

from __future__ import annotations

import pytest

from anamna.ingest.classifier import classify_document


def page(text: str, number: int = 1) -> dict[str, object]:
    return {"page_number": number, "native_text": text, "ocr_text": "", "native_char_count": len(text), "image_count": 0}


def classify(text: str, filename: str = "2025-01-01__vendor__report__0001.pdf") -> str:
    return classify_document(filename, "application/pdf", [page(text)]).clinical_type


RESULTS = (
    "Показник Результат Одиниці Референтні значення\n"
    "Гемоглобін 140 г/л 130 - 160\n"
    "Глюкоза 5,2 ммоль/л 4,1 - 5,9\n"
    "Креатинін 80 мкмоль/л 62 - 106\n"
    "Холестерин 4,8 ммоль/л 0 - 5,2\n"
)

# Each note is a sentence a lab writes under its own results table.  Alone (no
# table), each one is the kind the classifier has always given it.
CONSULTATION_NOTE = "Примітка: рекомендована консультація невролога."
PATHOLOGY_NOTE = "Примітка: після біопсії рекомендовано контроль."
MRI_NOTE = "Примітка: МРТ головного мозку рекомендовано."
ULTRASOUND_NOTE = "УЗД органів черевної порожнини рекомендовано."


@pytest.mark.parametrize(
    "note",
    [CONSULTATION_NOTE, PATHOLOGY_NOTE, MRI_NOTE, ULTRASOUND_NOTE],
)
def test_results_table_with_a_mention_of_another_kind_is_laboratory(note):
    assert classify(RESULTS + note + "\n") == "laboratory"


def test_the_same_notes_without_a_results_table_keep_their_kinds():
    assert classify("Скарги: головний біль.\nЗ огляду: стан задовільний.\n" + CONSULTATION_NOTE) == "consultation"
    assert classify("Діагноз: поліп шлунка. Стан після біопсії, атипії немає.") == "pathology"
    assert classify("МРТ головного мозку: без патологічних змін.\nВисновок: норма.") == "radiology_mri"
    assert (
        classify("УЗД органів черевної порожнини\nПечінка без змін.\nЖовчний міхур без конкрементів.")
        == "ultrasound"
    )


def test_three_rows_stay_below_the_threshold_and_a_consultation_stays_one():
    three = (
        "Показник Результат Одиниці Референтні значення\n"
        "Гемоглобін 140 г/л 130 - 160\n"
        "Глюкоза 5,2 ммоль/л 4,1 - 5,9\n"
        "Креатинін 80 мкмоль/л 62 - 106\n"
    )
    assert classify(three + "Консультація невролога\n" + CONSULTATION_NOTE + "\n") == "consultation"


def test_ultrasound_measurement_table_stays_ultrasound():
    # Six dimensions in millimetres: none is a unit the row parser reads, so no
    # results table exists to count.
    measurements = (
        "Товщина правої долі 15 мм\n"
        "Товщина лівої долі 14 мм\n"
        "Ширина правої долі 48 мм\n"
        "Ширина лівої долі 45 мм\n"
        "Довжина правої долі 52 мм\n"
        "Довжина лівої долі 50 мм\n"
    )
    assert classify("УЗД щитоподібної залози\n" + measurements) == "ultrasound"


def test_ultrasound_with_a_results_header_and_mostly_volume_rows_stays_ultrasound():
    # The header and four rows the parser does read, all in millilitres: a
    # length-and-volume table, read as a measurement table.
    text = (
        "УЗД сечового міхура\n"
        "Результат дослідження:\n"
        "Об'єм сечового міхура 120 мл 0 - 500\n"
        "Залишковий об'єм 12 мл 0 - 50\n"
        "Об'єм простати 25 мл 10 - 30\n"
        "Об'єм правої нирки 180 мл 150 - 250\n"
    )
    assert classify(text) == "ultrasound"


def test_a_fixed_discharge_summary_keeps_its_kind_over_a_results_table():
    text = (
        "Виписка із медичної карти амбулаторного (стаціонарного) хворого\n"
        + RESULTS
        + CONSULTATION_NOTE
        + "\n"
    )
    assert classify(text) == "clinical_report"
