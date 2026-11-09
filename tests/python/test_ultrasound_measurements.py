"""Ultrasound, echo, duplex and soft-tissue sizes the protocols print (sandbox audit 2026-11-06,
verdicts B and C), plus the visit temperature and the culture specimen read in the same pass.

Every fixture is invented text laid out the way the clinic's report lays it out; no number
below comes from a real record.
"""

import json

import pytest

from anamna.ingest.concepts import concept_for_alias, stable_concept_id
from anamna.ingest.parsers import parse_document
from anamna.locales import CONCEPT_NAMES_UK
from anamna.reference import LIBRARY_PATH


def page(text, number=1, ocr=""):
    return {"page_number": number, "native_text": text, "ocr_text": ocr}


def rows_of(vendor, clinical_type, pages):
    return [
        (row.raw_name, row.comparator, row.value_numeric, row.unit_raw, row.specimen)
        for row in parse_document(vendor, clinical_type, pages, age_years=40, sex="male")
    ]


EXPERT_ABDOMEN_1 = """ПРОТОКОЛ
УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ органів черевної порожнини
Печінка збільшена в розмірах:
Права частка: Косий вертикальний (по середньо-ключичній лінії) 158.2 мм.
Ліва частка: 61.4 мм.
Ворітна вена в ділянці воріт печінки не розширена, до 8.7мм.
Холедох на всьому проміжку нерозширений 3.4 мм. (норма 7 мм).
Жовчевий міхур розмірами: 34.2 * 72 мм. Форма: грушевидна.
Підшлункова залоза
Розміри: головка 24.5 мм; тіло 17мм; хвіст 21.3мм;
Діаметр селезінкової вени на рівні тіла підшлункової залози до 6.1 мм (норма до 8 мм).
Права нирка
Розмірами: 111.6 * 58.2мм. Товщина паренхіми до 15мм.
Конкременти не виявлені. На рівні чашок-поодинокі кристали солей 1мм-2мм.
Ліва нирка
Розмірами: 113.4 * 52 мм. Товщина паренхіми до 16.2мм.
Сечовий міхур:
Форма: плоско-округла"""

EXPERT_ABDOMEN_2 = """3
Розміром: 41 * 52.5 * 49мм.; V= 48см .
Стінка не потовщена - 2.5 мм. Внутрішньопорожнинних утворів не виявлено.
Селезінка
Розмірами: 108 * 39.6 мм., не збільшена.
ВИСНОВОК:"""


def test_expert_abdominal_protocol_yields_every_printed_size():
    rows = rows_of("Expert Hospital", "ultrasound", [page(EXPERT_ABDOMEN_1), page(EXPERT_ABDOMEN_2, 2)])
    new = [row for row in rows if row[0] not in {"Liver craniocaudal size", "Common bile duct diameter", "Bladder wall thickness"}]
    assert new == [
        ("Liver left lobe size", None, 61.4, "мм", "ліва частка"),
        ("Portal vein diameter", "≤", 8.7, "мм", None),
        # Sorted, not printed order: the larger figure is the length.
        ("Gallbladder length", None, 72.0, "мм", None),
        ("Gallbladder width", None, 34.2, "мм", None),
        ("Pancreatic head size", None, 24.5, "мм", None),
        ("Pancreatic body size", None, 17.0, "мм", None),
        ("Pancreatic tail size", None, 21.3, "мм", None),
        ("Splenic vein diameter", "≤", 6.1, "мм", None),
        ("Kidney length", None, 111.6, "мм", "права"),
        ("Kidney width", None, 58.2, "мм", "права"),
        ("Renal parenchymal thickness", "≤", 15.0, "мм", "права"),
        ("Largest renal salt crystal size", None, 2.0, "мм", "права"),
        ("Kidney length", None, 113.4, "мм", "ліва"),
        ("Kidney width", None, 52.0, "мм", "ліва"),
        ("Renal parenchymal thickness", "≤", 16.2, "мм", "ліва"),
        ("Spleen length", None, 108.0, "мм", None),
        ("Spleen thickness", None, 39.6, "мм", None),
        # The page break fell inside «Сечовий міхур»: page 2's «V= 48см³» (the
        # text layer drops the ³) is still the bladder's volume, not a length.
        ("Urinary bladder volume", None, 48.0, "см3", None),
    ]
    by_name = {item.raw_name: item for item in parse_document("Expert Hospital", "ultrasound", [page(EXPERT_ABDOMEN_1)])}
    vein = by_name["Splenic vein diameter"]
    assert (vein.reference_text, vein.reference_high) == ("норма до 8 мм", 8.0)
    # The evidence names the organ, not just «Розмірами: …».
    assert by_name["Gallbladder length"].evidence_text == "Жовчевий міхур розмірами: 34.2 * 72 мм"
    assert by_name["Kidney length"].evidence_text == "Ліва нирка Розмірами: 113.4 * 52 мм"


def test_volume_on_a_page_without_the_bladder_heading_is_not_read_as_bladder():
    alone = rows_of("Expert Hospital", "ultrasound", [page(EXPERT_ABDOMEN_2, 2)])
    assert not any(row[0] == "Urinary bladder volume" for row in alone)


def test_expert_blank_form_underscores_and_unlabelled_bladder_axes():
    text = """Печінка незначно збільшена в розмірах:
Права частка: Косий вертикальний (по середньо-ключичній лінії) _150_ мм.
Ліва частка: __64 мм.
Ворітна вена в ділянці воріт печінки не розширена, до _11_ мм.
Жовчевий міхур розмірами: _70_ х _25_ мм. Форма: грушевидна;
Підшлункова залоза
Розміри: головка 21__ мм; тіло 14__ мм; хвіст _20_ мм;
Селезінка
Розмірами: _104_ х _40_ мм., не збільшена.
Сечовий міхур:
Розміром: _70_ х 80__ х _85_ мм.;"""
    rows = rows_of("Expert Hospital", "ultrasound", [page(text)])
    assert ("Liver left lobe size", None, 64.0, "мм", "ліва частка") in rows
    assert ("Portal vein diameter", "≤", 11.0, "мм", None) in rows
    assert ("Gallbladder width", None, 25.0, "мм", None) in rows
    assert ("Pancreatic body size", None, 14.0, "мм", None) in rows
    assert ("Spleen length", None, 104.0, "мм", None) in rows
    # Three bladder figures with no axis named and no volume printed: nothing is guessed.
    assert not any(row[0].startswith("Urinary bladder") for row in rows)


def test_veselka_abdominal_template_lands_on_the_same_concepts():
    text = """УЗД органів черевної порожнини
Печінка: розміри: Права доля 131,0 мм, Ліва доля 66,5 мм. ехогенність паренхіми: незначно підвищена,
Жовчевий міхур розміри: 70,4 х 28,1 мм; ; розташований: типово ;
Підшлункова залоза: розміри: головка 25,0 мм, тіло 18,0 мм, хвіст 22,0 мм. не збільшена;
Селезінка: розміри: 110,2 х 50,3 мм; Не збільшена структура: однорідна;
Права нирка: розміри: 118,5 х 60,7 мм розміщення: типове; контур: чіткий та рівний; паренхіма:
товщиною 18,6 мм ехогенність паренхіми: звичайна;
Ліва нирка: розміри: 116,1 х 58,9 мм розміщення: типове; контур: чіткий та рівний; паренхіма:
товщиною 17,1 мм ехогенність паренхіми: звичайна;
Сечовий міхур: наповнений: достатньо; об'ємом до 350,0 мл форма: діжкоподібна; стінка: гомогенна,
товщиною 3,0 мм; контур: чіткий та рівний;"""
    rows = rows_of("Veselka", "ultrasound", [page(text)])
    for expected in [
        ("Liver left lobe size", None, 66.5, "мм", "ліва частка"),
        ("Gallbladder length", None, 70.4, "мм", None),
        ("Pancreatic tail size", None, 22.0, "мм", None),
        ("Spleen thickness", None, 50.3, "мм", None),
        ("Kidney width", None, 60.7, "мм", "права"),
        ("Renal parenchymal thickness", None, 17.1, "мм", "ліва"),
        ("Urinary bladder volume", "≤", 350.0, "мл", None),
        ("Bladder wall thickness", None, 3.0, "мм", None),
    ]:
        assert expected in rows, expected


def test_thyroid_isthmus_lobe_length_and_ti_rads_per_lobe():
    text = """Розміри : перешийок 4.8 мм.
Права частка : 14.2 / 16.9 / 44мм. Об’єм : 5.5 N- 7.5 cm3
Ліва частка : 15.0 / 15.7 / 42.6 мм. Об’єм : 5.1 N- 7.5 cm3
Вогнищеві утвори :в правій частці візуалізуються поодинокі анехогенні утвори, розмірами від 1-2мм
Оцінка за шкалою TI-RADS :
Права частка - 3 категорія
Ліва частка - 1 категорія"""
    rows = [row for row in rows_of("Expert Hospital", "ultrasound", [page(text)]) if row[0] != "Thyroid volume"]
    assert rows == [
        ("Thyroid isthmus thickness", None, 4.8, "мм", None),
        ("Thyroid lobe length", None, 44.0, "мм", "Права частка"),
        ("Thyroid lobe length", None, 42.6, "мм", "Ліва частка"),
        ("Thyroid TI-RADS category", None, 3.0, None, "Права частка"),
        ("Thyroid TI-RADS category", None, 1.0, None, "Ліва частка"),
    ]


ECHO = """Виміри Межі норми
Правий шлуночок 2.2 0,9 – 2,6 см
Міжшлуночкова перетинка, діастола 0.9 0,6 – 1,1 см
Лівий шлуночок, діастола 5.0 3,5 – 5,7 см
Стінка ЛШ, діастола 0.8 0,6 – 1,1 см
Фракція викиду Понад 55% Понад 55%
Діаметр висхідної аорти 3.0 2,0 – 3,7 см
Діаметр аорти на рівні синусів Вальсальви 3.4 2,4-3,9 см
Ліве передсердя 3.6 1,9 – 4,0 см
Клапани серця:
Мітральний Аортальний Тристулковий Легеневий
Додаткові дані ΔР мах мм.рт.ст ΔР мах мм.рт.ст ΔР мах 4 мм.рт.ст Tасс 131 мсек
ΔР сер мм.рт.ст ΔР сер мм.рт.ст"""


def test_echo_table_and_valve_doppler_row():
    found = parse_document("Expert Hospital", "ultrasound", [page(ECHO)], age_years=40, sex="male")
    rows = {row.raw_name: row for row in found}
    assert len(rows) == len(found) == 10
    septum = rows["Interventricular septal thickness, diastole"]
    assert (septum.value_numeric, septum.unit_raw, septum.reference_low, septum.reference_high) == (0.9, "см", 0.6, 1.1)
    assert rows["Aortic root diameter at the sinuses of Valsalva"].value_numeric == 3.4
    assert rows["Left atrial diameter"].value_numeric == 3.6
    fraction = rows["Left ventricular ejection fraction"]
    # «Понад 55%» is a lower limit, stored with its comparator and read as
    # within the identical printed norm (not as «low» for equalling it).
    assert (fraction.comparator, fraction.value_numeric, fraction.unit_raw) == (">", 55.0, "%")
    assert (fraction.reference_low, fraction.reference_low_inclusive, fraction.vendor_interpretation) == (55.0, False, "within_vendor_range")
    # Column 3 is the tricuspid valve, column 4 the pulmonary; the blank mitral
    # and aortic cells yield nothing.
    gradient = rows["Tricuspid valve peak pressure gradient"]
    assert (gradient.value_numeric, gradient.unit_raw) == (4.0, "мм.рт.ст")
    assert (rows["Pulmonary artery acceleration time"].value_numeric, rows["Pulmonary artery acceleration time"].unit_raw) == (131.0, "мсек")


DUPLEX = """Артеріальний сегмент ПШК см/сек Кровоплин, хід судини, інші особливості
Загальна сонна артерія, права 80 N=50-104 Кровоплин магістральний, хід правильний
Внутрішня сонна артерія, права 61 N=37-105 Кровоплин магістральний, хід правильний
Зовнішня сонна артерія, права 64 N=32-100 Кровоплин магістральний, хід правильний
Загальна сонна артерія, ліва 85 N=50-104 Кровоплин магістральний, хід правильний
Внутрішня сонна артерія, ліва 63 N=37-105 Кровоплин магістральний, хід правильний
Зовнішня сонна артерія, ліва 66 N=32-100 Кровоплин магістральний, хід правильний
Кровоплин магістральний, хід рівний , D=
Хребцева артерія ПРАВА 41 N=20-61
3.6 мм (N 2,5-4,4 мм)
Кровоплин магістральний, хід рівний, D= 3.4
Хребцева артерія ЛІВА 36 N=20-61
мм (N 2,5-4,4 мм)
Дистальні відділи плечоголовного стовбура візуалізовані."""

DUPLEX_WRAPPED = """Загальна сонна артерія, Кровоплин магістральний, хід
80 N=50-104
права правильний
Внутрішня сонна Кровоплин магістральний, хід
61 N=37-105
артерія, права правильний
Зовнішня сонна артерія, Кровоплин магістральний, хід
66 N=32-100
ліва правильний
Кровоплин магістральний, хід
Хребцева артерія ПРАВА 41 N=20-61
рівний , D= 3.6 мм (N 2,5-4,4 мм)
Кровоплин магістральний, хід
Хребцева артерія ЛІВА 36 N=20-61
рівний, D= 3.4 мм (N 2,5-4,4 мм)"""


def test_duplex_vessels_sides_and_the_vertebral_diameter_wrapped_around_its_psv():
    rows = [row for row in rows_of("Expert Hospital", "ultrasound", [page(DUPLEX)]) if "common carotid" not in row[0]]
    assert rows == [
        ("Peak systolic velocity, internal carotid artery", None, 61.0, "см/сек", "права"),
        ("Peak systolic velocity, external carotid artery", None, 64.0, "см/сек", "права"),
        ("Peak systolic velocity, internal carotid artery", None, 63.0, "см/сек", "ліва"),
        ("Peak systolic velocity, external carotid artery", None, 66.0, "см/сек", "ліва"),
        ("Peak systolic velocity, vertebral artery", None, 41.0, "см/сек", "права"),
        ("Vertebral artery diameter", None, 3.6, "мм", "права"),
        ("Peak systolic velocity, vertebral artery", None, 36.0, "см/сек", "ліва"),
        ("Vertebral artery diameter", None, 3.4, "мм", "ліва"),
    ]
    diameter = next(row for row in parse_document("Expert Hospital", "ultrasound", [page(DUPLEX)]) if row.raw_name == "Vertebral artery diameter")
    assert (diameter.reference_text, diameter.reference_low, diameter.reference_high) == ("N 2,5-4,4 мм", 2.5, 4.4)


def test_duplex_wrapped_layout_keeps_vessel_and_side():
    rows = rows_of("Expert Hospital", "ultrasound", [page(DUPLEX_WRAPPED)])
    assert ("Peak systolic velocity, internal carotid artery", None, 61.0, "см/сек", "права") in rows
    assert ("Peak systolic velocity, external carotid artery", None, 66.0, "см/сек", "ліва") in rows
    assert ("Vertebral artery diameter", None, 3.6, "мм", "права") in rows
    assert ("Vertebral artery diameter", None, 3.4, "мм", "ліва") in rows


def test_soft_tissue_lesion_two_diameters_under_the_named_site():
    expert = """Локалізація патологічного процесу – в проекції дельтоподібного мязу праворуч
Особливості обстеження – підшкірно , на глибині 3.1мм візуалізується гіперехогенний утвір з чітким
контуром, аваскулярний, розміром 6.4 * 11.2мм
ЗАКЛЮЧЕННЯ: Ліпома"""
    assert rows_of("Expert Hospital", "ultrasound", [page(expert)]) == [
        ("Soft tissue lesion largest diameter", None, 11.2, "мм", "в проекції дельтоподібного мязу праворуч"),
        ("Soft tissue lesion smaller diameter", None, 6.4, "мм", "в проекції дельтоподібного мязу праворуч"),
    ]
    veselka = """УЗД ПРИЦІЛЬНО
В ділянці 'інтересу' ﴾верхня третина правого стегна﴿ візуалізується гіперехогенне утворення розмірами
12,3х5,2мм,відстань від поверхні шкіри становить 2,1 м,контури утворення чіткі"""
    # The depth is printed with a unit no depth can have, and is never read.
    assert rows_of("Veselka", "ultrasound", [page(veselka)]) == [
        ("Soft tissue lesion largest diameter", None, 12.3, "мм", "верхня третина правого стегна"),
        ("Soft tissue lesion smaller diameter", None, 5.2, "мм", "верхня третина правого стегна"),
    ]


def test_temperature_measured_at_the_visit_inside_a_diagnosis():
    note = """Попередній діагноз:
Загострення вертеброгенної люмбалгії.
Субфебрильна Т (37.4 ­на прийомі)
Призначене лікування:
1. Еторікоксиб 90 мг 1 т після обіду 7 днів"""
    rows = parse_document("St. Paraskeva Medical Center", "consultation", [page(note)])
    assert [(row.raw_name, row.value_numeric, row.unit_raw) for row in rows] == [("Температура тіла", 37.4, "°C")]
    assert concept_for_alias(rows[0].raw_name)["name"] == "Body temperature"
    # Without «на прийомі» it is history, not a reading; a dose is never one.
    for text in ("Субфебрильна Т (37.4) три тижні тому", "Аркоксія 90 мг на прийомі", "Т (37.4 на прийомі)"):
        assert parse_document("St. Paraskeva Medical Center", "consultation", [page(text)]) == []


def test_culture_rows_take_the_specimen_printed_above_them():
    ocr = """Матеріал: мазок із носа
Результат дослідження
Мікроорганізм Кількість
Дріжджові та плісняві гриби не виявлено
Аеробна мікрофлора
Чутливість визначена до наступних препаратів
Меропенем чутливий"""
    rows = parse_document("Expert Hospital", "microbiology", [page("БАКПОСІВ", ocr=ocr)])
    assert rows and {row.specimen for row in rows} == {"мазок із носа"}


NEW_CONCEPTS = [
    "Liver left lobe size", "Portal vein diameter", "Gallbladder length", "Gallbladder width",
    "Pancreatic head size", "Pancreatic body size", "Pancreatic tail size", "Splenic vein diameter",
    "Kidney length", "Kidney width", "Renal parenchymal thickness", "Largest renal salt crystal size",
    "Urinary bladder volume", "Spleen length", "Spleen thickness", "Thyroid isthmus thickness",
    "Thyroid lobe length", "Thyroid TI-RADS category", "Right ventricular diameter",
    "Interventricular septal thickness, diastole", "Left ventricular end-diastolic diameter",
    "Left ventricular posterior wall thickness, diastole", "Left ventricular ejection fraction",
    "Ascending aorta diameter", "Aortic root diameter at the sinuses of Valsalva", "Left atrial diameter",
    "Tricuspid valve peak pressure gradient", "Pulmonary artery acceleration time",
    "Peak systolic velocity, internal carotid artery", "Peak systolic velocity, external carotid artery",
    "Peak systolic velocity, vertebral artery", "Vertebral artery diameter",
    "Soft tissue lesion largest diameter", "Soft tissue lesion smaller diameter",
]
ANALYTES = {entry["concept_id"]: entry for entry in json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))["analytes"]}


@pytest.mark.parametrize("name", NEW_CONCEPTS)
def test_every_new_measurement_maps_names_itself_in_ukrainian_and_has_guidance(name):
    definition = concept_for_alias(name)
    assert definition is not None and definition["name"] == name
    assert CONCEPT_NAMES_UK.get(name)
    entry = ANALYTES[stable_concept_id(name)]
    assert entry["source_ids"] and entry["regions_covered"]
    assert entry["kind"] != "no_universal_target" or entry.get("no_target_reason")
