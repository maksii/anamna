"""Measured values printed in clinic visit notes, consultations and ECG reports.

The pipeline used to read numbers only out of laboratory-style documents, so a
consultation contributed its written conclusion and nothing else: five
primary-care notes' temperature, pulse, breathing rate and saturation, a
cardiologist's weight, height, BMI and both arms' blood pressure, and an ECG's
interval table were in the record as page text and nowhere else.

The samples are the real lines from those Veselka (Doctor ELEKS) documents,
with the patient's name and date of birth replaced.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from anamna.db import connect
from anamna.ingest import pipeline
from anamna.ingest.classifier import Classification
from anamna.ingest.parsers import parse_document
from anamna.reference import canonical_unit

from test_rescan import build


PRIMARY_CARE = """Дата взаємодії: 08.01.2026 8:32* Клас Первинна медична Тип взаємодії:Взаємодія в закладі
ПІБ пацієнта: Іваненко Іван Іванович Стать: Чоловіча
Дата народження: 01.01.1990 Вік: 36 років
Об’єктивний стан:
Загальний стан: задовільний. Вага: кг. Зріст: см Температура: 36,5 ° C
Шкіра і підшкірно‐жирова клітковина: S31 ‐ Часткове медичне обстеження Шкіра:
нормі. Включення: відсутні. Частота дихання: 17 /хв SpO2: 97 % Дихання: вільне.
Серцево‐судинна система: ЧСС: 81 уд/хв. Тони серця: звучні, ритмічні .
При підвищенні температури тіла понад 38,5 приймати жарознижуючі Нурофен 400 мг ‐ 1
"""

CARDIOLOGY = """Консультація лікаря‐кардіолога
Дата візиту: 09.08.2026
ПІБ пацієнта: Іваненко Іван Іванович Дата народження: 01.01.1990
Скарги: зміни у лабораторних показниках
Лабораторна діагностика за 04.08.2026р
Глюкоза 5,95, глікований гемоглобін 5,26
Ліпідограма: заг холестерин 7,22, ЛПДНЩ 1,09, ЛПНЩ 5,54, аполіпопротеїн В 1,49, КА 5,50
Печінкові та ниркові проби норма.
ГХ тривало. На постійній основі приймає Діокор 160
Обстеження
Вага тіла 110 кг.
Зріст тіла 186 см.
Індекс маси тіла ﴾ІМТ﴿ [Співвідношення] 31,8
Об’єктивний стан:
Загальний стан: задовільний.
Життєві показники
Температура тіла А. Т. ЧСС ЧД Сатурація
36,6 ˚С мм.рт.ст 62 уд/в 16 хв 98 %
АТ: права рука 120/80 мм.рт.ст.‐ ліва рука 120/80 мм.рт.ст. Тони серця: звучні, ритмічні . Периферичні набряки: відсутні.
Діокор 160 1 табл 1р/д під контролем АТ
Обмеження солі до 3 г/д
"""

ECG = """Електрокардіограма
Дата візиту: 09.08.2026
ОПИС:
ЧСС PQ QRS QT QTc ﴾Bazett﴿ QTc ﴾Sagie/Framingham﴿
66 уд/хв 140 мсек 80 мсек 380 мсек 399 мсек 394 мсек
Ритм: синусовий
Висновок: Синусовий ритм з ЧСС 66 уд/хв, вольтаж збережений. ЕВС ‐ лівограма, поза тим ‐ ЕКГ в межах
"""


def pages(text: str) -> list[dict[str, object]]:
    return [{"page_number": 1, "native_text": text, "ocr_text": None}]


def read(text: str, clinical_type: str = "consultation") -> list[tuple[str, float, str | None, str | None]]:
    return [
        (item.raw_name, item.value_numeric, item.unit_raw, item.specimen)
        for item in parse_document("Veselka", clinical_type, pages(text))
    ]


def test_a_primary_care_note_yields_its_four_vitals_and_nothing_for_empty_fields():
    assert read(PRIMARY_CARE) == [
        ("Температура", 36.5, "° C", None),
        ("Частота дихання", 17.0, "/хв", None),
        ("SpO2", 97.0, "%", None),
        ("ЧСС", 81.0, "уд/хв", None),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "Загальний стан: задовільний. Вага: кг. Зріст: см",
        "Загальний стан: задовільний. Зріст: см Температура:",
        "Вага",
        # Advice, not a reading: no colon, and the wrong form of the word.
        "При підвищенні температури тіла понад 38,5 приймати жарознижуючі",
        # A conclusion restating the table above it.
        "Висновок: Синусовий ритм з ЧСС 66 уд/хв, вольтаж збережений.",
        # A drug dose and a salt limit are not body measurements.
        "Діокор 160 1 табл 1р/д під контролем АТ",
    ],
)
def test_empty_fields_and_prose_yield_nothing(line):
    assert read(line) == []


def test_the_cardiology_note_reads_its_measurements_and_not_the_lab_values_it_quotes():
    found = read(CARDIOLOGY)
    assert found == [
        ("Вага тіла", 110.0, "кг", None),
        ("Зріст тіла", 186.0, "см", None),
        ("Індекс маси тіла (ІМТ)", 31.8, None, None),
        ("Температура тіла", 36.6, "˚С", None),
        ("ЧСС", 62.0, "уд/в", None),
        ("ЧД", 16.0, "хв", None),
        ("Сатурація", 98.0, "%", None),
        ("Систолічний артеріальний тиск", 120.0, "мм.рт.ст.", "права рука"),
        ("Діастолічний артеріальний тиск", 80.0, "мм.рт.ст.", "права рука"),
        ("Систолічний артеріальний тиск", 120.0, "мм.рт.ст.", "ліва рука"),
        ("Діастолічний артеріальний тиск", 80.0, "мм.рт.ст.", "ліва рука"),
    ]
    # The quoted glucose, HbA1c and lipid figures are another laboratory's
    # results, already in the record from that laboratory's own report.
    values = {value for _, value, _, _ in found}
    assert not values & {5.95, 5.26, 7.22, 1.09, 5.54, 1.49, 5.50, 160.0, 3.0}


def test_the_empty_blood_pressure_cell_is_skipped_and_the_columns_stay_aligned():
    """«мм.рт.ст» with no number under «А. Т.»: the pulse must not slide left."""
    found = {name: (value, unit) for name, value, unit, _ in read(CARDIOLOGY)}
    assert found["ЧСС"] == (62.0, "уд/в")
    assert found["ЧД"] == (16.0, "хв")


def test_the_ecg_table_reads_rate_and_intervals_with_the_qtc_formula_named():
    assert read(ECG, "clinical_report") == [
        ("ЧСС (ЕКГ)", 66.0, "уд/хв", None),
        ("PQ", 140.0, "мсек", None),
        ("QRS", 80.0, "мсек", None),
        ("QT", 380.0, "мсек", None),
        ("QTc (Bazett)", 399.0, "мсек", None),
        ("QTc (Sagie/Framingham)", 394.0, "мсек", None),
    ]
    # Filed as an ECG by a classifier, the same table is still read.
    assert len(read(ECG, "electrocardiogram")) == 6


def test_a_table_whose_cells_do_not_fit_their_columns_is_not_read():
    assert read("ЧСС PQ QRS\n66 уд/хв 140 % 80 мсек", "clinical_report") == []
    assert read("ЧСС PQ QRS\n66 уд/хв 140 мсек", "clinical_report") == []


def test_values_are_dated_by_the_visit_and_carry_their_printed_lines():
    items = parse_document("Veselka", "consultation", pages(CARDIOLOGY))
    assert {item.observed_at for item in items} == {"2026-08-09"}
    by_name = {item.raw_name: item for item in items}
    assert by_name["Вага тіла"].evidence_text == "Вага тіла 110 кг."
    assert by_name["Сатурація"].evidence_text == (
        "Температура тіла А. Т. ЧСС ЧД Сатурація\n36,6 ˚С мм.рт.ст 62 уд/в 16 хв 98 %"
    )
    assert by_name["Індекс маси тіла (ІМТ)"].value_printed == "31,8"
    primary = parse_document("Veselka", "consultation", pages(PRIMARY_CARE))
    assert {item.observed_at for item in primary} == {"2026-01-08"}


@pytest.mark.parametrize(
    ("printed", "library"),
    [("° C", "°C"), ("˚С", "°C"), ("уд/в", "bpm"), ("уд/хв", "bpm"),
     ("мм.рт.ст.", "mmHg"), ("мм.рт.ст", "mmHg"), ("мсек", "ms"), ("кг", "kg"), ("см", "cm")],
)
def test_printed_units_fold_onto_the_library_unit(printed, library):
    assert canonical_unit(printed) == canonical_unit(library)


def test_bare_minutes_are_breaths_per_minute_only_under_the_respiratory_rate():
    assert pipeline.stored_unit("хв", "breaths/min", "resting-respiratory-rate") == "breaths/min"
    assert pipeline.stored_unit("/хв", "breaths/min", "resting-respiratory-rate") == "breaths/min"
    assert canonical_unit("хв") == "min"


def _consultation(title: str = "Консультація лікаря-кардіолога") -> Classification:
    return Classification(
        vendor="Veselka", website=None, clinical_type="consultation", title=title,
        report_date="2026-08-09", order_identifier=None, status="final",
        extraction_strategy="native_text", confidence=0.9, notes=None,
    )


def _stored(settings) -> list[tuple]:
    with connect(settings) as connection:
        return sorted(
            (row["concept_id"], row["raw_name"], row["value_numeric"], row["unit_raw"],
             row["unit_canonical"], row["specimen"], row["observed_at"], row["page_number"],
             row["verification_status"])
            for row in connection.execute("SELECT * FROM observations WHERE document_id='doc-1'")
        )


def test_a_rescan_files_each_value_under_its_concept_and_a_second_rescan_changes_nothing(
    tmp_path: Path, monkeypatch
):
    settings, user_id, _ = build(tmp_path)
    klass = _consultation()
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            pages=[{**pages(CARDIOLOGY)[0], "native_text_sha256": "sha-1",
                    "extraction_method": "native_pdf_text", "native_char_count": len(CARDIOLOGY),
                    "image_count": 0}],
            mime_type="application/pdf", page_count=1, content_hash="content-hash",
            classification=klass, per_page=[klass],
        ),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    first = _stored(settings)
    pipeline.reingest_document(settings, user_id, "doc-1")
    assert _stored(settings) == first

    concepts = Counter(row[0] for row in first)
    assert concepts == Counter({
        "body-weight": 1, "body-height": 1, "body-mass-index": 1, "body-temperature": 1,
        "pulse-rate": 1, "resting-respiratory-rate": 1, "oxygen-saturation-spo2": 1,
        "systolic-blood-pressure": 2, "diastolic-blood-pressure": 2,
    })
    # Provisional until a person checks them, dated by the visit.
    assert {row[8] for row in first} == {"extracted"}
    assert {row[6] for row in first} == {"2026-08-09"}
    by_concept = {row[0]: row for row in first}
    assert by_concept["resting-respiratory-rate"][4] == "breaths/min"
    assert by_concept["body-mass-index"][4] == "kg/m²"
    assert {row[5] for row in first if row[0] == "systolic-blood-pressure"} == {"права рука", "ліва рука"}


def test_ecg_intervals_resolve_to_their_own_concepts(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    klass = replace(_consultation("Електрокардіограма (ЕКГ)"), clinical_type="clinical_report")
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            pages=[{**pages(ECG)[0], "native_text_sha256": "sha-1", "extraction_method": "native_pdf_text",
                    "native_char_count": len(ECG), "image_count": 0}],
            mime_type="application/pdf", page_count=1, content_hash="content-hash",
            classification=klass, per_page=[klass],
        ),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    assert {row[0]: row[2] for row in _stored(settings)} == {
        "ecg-heart-rate": 66.0, "pr-interval": 140.0, "qrs-duration": 80.0,
        "qt-interval": 380.0, "qtc-bazett": 399.0, "qtc-framingham": 394.0,
    }
