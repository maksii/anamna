"""Measured values in Expert Hospital's in-app visit records and protocols.

Expert's records are typed freehand and composed into a PDF that wraps long
sentences wherever the width runs out.  Every form below was printed in an
imported record and read as nothing: «АТ-135\\80», «ЧСС-75\\хв», «за хв»,
«Зріст 185 см» with no colon, «Зріст _185___» (a form's blank), «37*С», ECG
intervals in seconds, a reading wrapped over two lines, an echo label wrapped
around its value, and a duplex row whose side is printed after the flow text.

The samples are the real lines with the patient's name, date of birth and the
doctor's name removed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

import anamna.health  # noqa: F401  -- merges UNIT_SYNONYMS into canonical_unit
from anamna.db import connect
from anamna.ingest import pipeline
from anamna.ingest.classifier import Classification
from anamna.ingest.parsers import parse_document
from anamna.reference import canonical_unit

from test_rescan import build


CARDIOLOGY = """Консультація кардіолога
Дата: 13.02.2025
Огляд:
Об'єктивно:шкірні покриви блідо-рожеві,чисті.Аускультативно:над легенями
везикулярне дихання,тони серця
звучні,ритмічні.АТ-135\\80мм.рт.ст,ЧСС-75\\хв.Набряки на нижніх кінцівках відсутні.
ЕКГ:ритм синусовий,правильний,ЧСС-85\\хв,лівограма,PQ-0.20с,QRS-0.08с.без
гострих коронарних змін
Рекомендації:
Контроль АТ
Діокор 12.5\\160мг 1т 1р зранку
Аторис 20мг 1т 1р ввечері
контроль ліпідограми через 8 тижнів
"""

ANAESTHESIA_BLANKS = """Консультація анестезіолога
Дата: 16.09.2025
Анамнез:
Приймає постійно препарати ____діокор 160 мг, аторіс 20 мгмоваліс 15 мг_____
Огляд:
загальний стан задовільний. Язик вологий. Малампаті __1_. Будова тіла
_______нормотснеічна ________. Варикозно розширених вен немає. Шия звичайна.
Зріст _185___. Вага ___109__ кг. В легенях аускультативно дихання везикулярне,
хрипів немає. ЧДД18 за хвилину. Тони серця ритмічні, гучні. ЧСС 70 за хв.
Гемодинаміка стабільна. АТ 120\\80 мм рт ст. Живіт мякий , безболісний.
самостійне. Стілець в нормі. Нервово-психічний статус без особливостей. Ступень
операційного риску ASA __2_/ Планується Інгаляційна анестезія.
"""

ANAESTHESIA_WRAPPED = """Консультація анестезіолога
Дата: 05.11.2025
Анамнез:
ГХ І ст 2 ст ризик помірний, застудні. Палить 20 цигарок на день. Приймає постійно препарати
діокор 160 мг, вітаміни
Огляд:
Варикозно розширених вен немає. Шия звичайна. Зріст 185 см, вага 109 кг.
В легенях аускультативно дихання везикулярне,хрипів немає. ЧД 15 за хвилину.
Сог тони ритмічні,приглушени. ЧСС 68 за хв. Гемодинаміка стабільна . АТ 120/80
мм рт ст. Живіт м"який,безбольосний при пальпації. Перистальтика
Рекомендації:
2)не пити за 3 години до операції
3)не їсти за 12 годин до операції
"""

THERAPIST_WRAPPED = """Консультація терапевта
Дата: 08.04.2023
Огляд:
слизові зіву блідо-рожеві, ЧД - 16/хв, SpO2 - 98%, тони серця звучні, ритмічні, ЧСС -
78/хв., АТ - 95/60 мм.рт.ст.
Живіт не болючий.
"""

THERAPIST_TEMPERATURE = """Консультація терапевта
Дата: 01.01.2024
Огляд:
Мигдалики не зібльшені, підщелепний лімфовузол злегка збільшений справа.
Температура тіла 37*С
Призначення:
Дексалгін саше: по 1 саше, 3 раз в 1 День (дні), 01.01.2024–07.01.2024, на курс 21
саше
"""

ECHO = """ПРОТОКОЛ
УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ СЕРЦЯ
Виміри Межі норми
Правий шлуночок 2.5 0,9 – 2,6 см
Міжшлуночкова перетинк 1.1 0,6 – 1,1 см
а, діастола
Лівий шлуночок, діастола 4.7 3,5 – 5,7 см
Стінка ЛШ, діастола 1.0 0,6 – 1,1 см
Фракція викиду Понад 55% Понад 55%
Діаметр висхідної аорти 2.8 2,0 – 3,7 см
Діаметр аорти на рівні 3.2 2,4-3,9 см
синусів Вальсальви
Ліве передсердя 3.3 1,9 – 4,0 см
Індекс маси міокарда ЛШ 43-95 г/м2 (жінки)
178 49-115 г/м2
(чоловіки)
Клапани серця:
Мітральний Аортальний Тристулковий Легеневий
Недостатність - - тривіальна тривіальна
Додаткові дані ΔР мах мм.рт.ст ΔР мах мм. ΔР мах 3 мм.рт.с Tасс 128 мсек
ΔР сер мм.рт.ст рт.ст т
ΔР сер мм.р
т.ст
Висновок: Лівий шлуночок не розширений, стінки не потовщені.
Дата дослідження: 13.02.2025
"""

DUPLEX = """Ультразвукове обстеження
гілок дуги аорти
Артеріальний псш Кровоплин, хід судини,
сегмент см/сек інші особливості
Загальна сонна артерія, 108 Кровоплин магістральний, хід
права правильний
Внутрішня сонна артерія, 78 Кровоплин магістральний, хід
права правильний
Зовнішня сонна артерія, 114 Кровоплин магістральний, хід
права правильний
Хребцева артерія права, 45 Кровоплин магістральний, хід
почат. сегмент рівний. D=3,4 мм
Хребцева артерія права, ди 49 Кровоплин магістральний, хід
ст. сегмент рівний
Загальна сонна артерія, 107 Кровоплин магістральний, хід
ліва правильний
Внутрішня сонна артерія, 84 Кровоплин магістральний, хід
ліва правильний
Зовнішня сонна артерія, 110 Кровоплин магістральний, хід
ліва правильний
Хребцева артерія ліва, 41 Кровоплин магістральний, хід
почат. сегмент правильний D=3,6 мм
Хребцева артерія ліва, 49 Кровоплин магістральний, хід
дист. сегмент правильний
Дистальні відділи плечоголовного стовбура, проксимальні відділи Заг СА, ВСА, ЗовС
А, ХА в екстракраніальних відділах візуалізовані. Прохідні. Диференціювання КІМ на шари збережене. КІМ
справа 0,5 мм, КІМ зліва 0,5 мм. Просвіти усіх артерій вільні.
Транскраніальне дуплексне сканування
Артерії Vps, см/с
ПМА права 102 N-87-95
ПМА ліва 99 N-87-95
СМА права 126 N-109-116
СМА ліва 128 N-109-116
ХА (V4) права 68 N-63-69
ХА(V4) ліва 71 N-63-69
Базилярна 77 N-70-78
Заключення: на момент огляду ознак гемодинамічних розладів по сонних
Дата: 13.05.2023
"""


def read(text: str, clinical_type: str = "consultation"):
    pages = [{"page_number": 1, "native_text": text, "ocr_text": None}]
    return [
        (item.raw_name, item.value_numeric, item.unit_raw, item.specimen)
        for item in parse_document("Expert", clinical_type, pages)
    ]


def test_backslash_readings_unspaced_dashes_and_ecg_intervals_in_seconds():
    assert read(CARDIOLOGY) == [
        ("ЧСС", 75.0, "уд/хв", None),
        ("Систолічний артеріальний тиск", 135.0, "мм.рт.ст", None),
        ("Діастолічний артеріальний тиск", 80.0, "мм.рт.ст", None),
        # The ECG's rate is kept apart from the counted pulse, as the table form is.
        ("ЧСС (ЕКГ)", 85.0, "уд/хв", None),
        ("PQ", 200.0, "мсек", None),
        ("QRS", 80.0, "мсек", None),
    ]


def test_form_blanks_glued_labels_and_per_minute_in_words():
    assert read(ANAESTHESIA_BLANKS) == [
        ("Зріст", 185.0, "см", None),
        ("Вага", 109.0, "кг", None),
        ("ЧД", 18.0, "/хв", None),
        ("ЧСС", 70.0, "уд/хв", None),
        ("Систолічний артеріальний тиск", 120.0, "мм рт ст.", None),
        ("Діастолічний артеріальний тиск", 80.0, "мм рт ст.", None),
    ]


def test_clause_labels_without_a_colon_and_a_pressure_whose_unit_wrapped():
    found = read(ANAESTHESIA_WRAPPED)
    assert found == [
        ("вага", 109.0, "кг", None),
        ("Зріст", 185.0, "см", None),
        ("ЧД", 15.0, "/хв", None),
        ("ЧСС", 68.0, "уд/хв", None),
        ("Систолічний артеріальний тиск", 120.0, "мм рт ст.", None),
        ("Діастолічний артеріальний тиск", 80.0, "мм рт ст.", None),
    ]
    # Neither the cigarettes, the hours of fasting nor the dose is a measurement.
    assert not {value for _, value, _, _ in found} & {20.0, 2.0, 3.0, 12.0, 160.0}


def test_a_label_wrapped_away_from_its_value_is_read_once():
    found = read(THERAPIST_WRAPPED)
    assert ("ЧСС", 78.0, "уд/хв", None) in found
    assert Counter(name for name, *_ in found) == Counter({
        "ЧД": 1, "SpO2": 1, "ЧСС": 1, "Систолічний артеріальний тиск": 1, "Діастолічний артеріальний тиск": 1,
    })
    wrapped = next(item for item in parse_document(
        "Expert", "consultation", [{"page_number": 1, "native_text": THERAPIST_WRAPPED, "ocr_text": None}]
    ) if item.raw_name == "ЧСС")
    assert wrapped.evidence_text.endswith("ЧСС -\n78/хв., АТ - 95/60 мм.рт.ст.")


def test_a_temperature_typed_with_an_asterisk_for_the_degree():
    assert read(THERAPIST_TEMPERATURE) == [("Температура тіла", 37.0, "*С", None)]


@pytest.mark.parametrize(
    "line",
    [
        # Not at the start of a clause: a target or a conclusion, not a reading.
        "Контроль ЧСС 60 за хв",
        "Синусовий ритм з ЧСС 66 уд/хв, вольтаж збережений.",
        # A range, and a weight that does not end its clause.
        "ЧСС-60-90 уд/хв норма",
        "Вага - 61 при нормі 50",
        # A seconds value outside any interval's limits.
        "ЕКГ: PQ-2.0с",
    ],
)
def test_loose_labels_still_reject_prose(line):
    assert read(line) == []


@pytest.mark.parametrize(
    "text",
    [CARDIOLOGY, ANAESTHESIA_BLANKS, ANAESTHESIA_WRAPPED, THERAPIST_WRAPPED, THERAPIST_TEMPERATURE],
)
def test_every_new_unit_folds_onto_its_concepts_unit(text):
    library = {"ЧСС": "bpm", "ЧСС (ЕКГ)": "bpm", "PQ": "ms", "QRS": "ms", "Зріст": "cm", "Вага": "kg",
               "вага": "kg", "Температура тіла": "°C", "Систолічний артеріальний тиск": "mmHg",
               "Діастолічний артеріальний тиск": "mmHg", "SpO2": "%"}
    for name, _, unit, _ in read(text):
        if name == "ЧД":
            assert pipeline.stored_unit(unit, "breaths/min", "resting-respiratory-rate") == "breaths/min"
        else:
            assert canonical_unit(unit) == canonical_unit(library[name]), (name, unit)


def test_the_echo_reads_labels_wrapped_around_their_value_and_the_cut_tricuspid_unit():
    rows = {name: (value, unit, specimen) for name, value, unit, specimen in read(ECHO, "ultrasound")}
    assert rows["Interventricular septal thickness, diastole"] == (1.1, "см", None)
    assert rows["Aortic root diameter at the sinuses of Valsalva"] == (3.2, "см", None)
    assert rows["Tricuspid valve peak pressure gradient"] == (3.0, "мм.рт.ст.", None)
    assert canonical_unit("мм.рт.ст.") == canonical_unit("mmHg")
    # Unchanged: the LV mass index row and the six rows that never wrapped.
    assert rows["Left ventricular mass index"] == (178.0, "г/м2", None)
    assert len(rows) == 11
    items = {item.raw_name: item for item in parse_document(
        "Expert", "ultrasound", [{"page_number": 1, "native_text": ECHO, "ocr_text": None}]
    )}
    septum = items["Interventricular septal thickness, diastole"]
    assert (septum.reference_low, septum.reference_high) == (0.6, 1.1)
    assert septum.evidence_text == "Міжшлуночкова перетинк 1.1 0,6 – 1,1 см а, діастола"
    assert items["Aortic root diameter at the sinuses of Valsalva"].reference_text == "2,4-3,9 см"


def test_a_wrapped_echo_tail_that_completes_no_label_is_not_taken():
    text = "Виміри Межі норми\nМіжшлуночкова перетинк 1.1 0,6 – 1,1 см\nсистола\n"
    assert read(text, "ultrasound") == []


def test_the_duplex_carotid_rows_take_the_side_printed_after_the_flow_text():
    found = read(DUPLEX, "ultrasound")
    assert len(found) == 21
    carotid = [(name, value, specimen) for name, value, _, specimen in found if "carotid artery" in name]
    assert carotid == [
        ("Peak systolic velocity, common carotid artery", 108.0, "права"),
        ("Peak systolic velocity, internal carotid artery", 78.0, "права"),
        ("Peak systolic velocity, external carotid artery", 114.0, "права"),
        ("Peak systolic velocity, common carotid artery", 107.0, "ліва"),
        ("Peak systolic velocity, internal carotid artery", 84.0, "ліва"),
        ("Peak systolic velocity, external carotid artery", 110.0, "ліва"),
    ]
    assert {unit for name, _, unit, _ in found if "carotid artery" in name} == {"см/сек"}


def _consultation() -> Classification:
    return Classification(
        vendor="Expert", website=None, clinical_type="consultation", title="Консультація кардіолога",
        report_date="2025-02-13", order_identifier=None, status="final",
        extraction_strategy="native_text", confidence=0.9, notes=None,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (CARDIOLOGY, {"pulse-rate": 1, "ecg-heart-rate": 1, "pr-interval": 1, "qrs-duration": 1,
                      "systolic-blood-pressure": 1, "diastolic-blood-pressure": 1}),
        (ANAESTHESIA_BLANKS, {"body-height": 1, "body-weight": 1, "resting-respiratory-rate": 1, "pulse-rate": 1,
                              "systolic-blood-pressure": 1, "diastolic-blood-pressure": 1}),
        (ANAESTHESIA_WRAPPED, {"body-height": 1, "body-weight": 1, "resting-respiratory-rate": 1, "pulse-rate": 1,
                               "systolic-blood-pressure": 1, "diastolic-blood-pressure": 1}),
        (THERAPIST_TEMPERATURE, {"body-temperature": 1}),
    ],
)
def test_each_new_value_files_under_its_concept(tmp_path: Path, monkeypatch, text, expected):
    settings, user_id, _ = build(tmp_path)
    klass = _consultation()
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            pages=[{"page_number": 1, "native_text": text, "ocr_text": None, "native_text_sha256": "sha-1",
                    "extraction_method": "native_pdf_text", "native_char_count": len(text), "image_count": 0}],
            mime_type="application/pdf", page_count=1, content_hash="content-hash",
            classification=klass, per_page=[replace(klass)],
        ),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        concepts = Counter(row[0] for row in connection.execute(
            "SELECT concept_id FROM observations WHERE document_id='doc-1'"
        ))
    assert concepts == Counter(expected)
