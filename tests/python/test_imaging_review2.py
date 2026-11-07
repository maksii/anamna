"""Pelvic, breast, thyroid, duplex, transcranial, EEG and breath-test readers (sandbox audit
review 2, 2026-11-07, verdicts G and H and the photo triage).

Every fixture is invented text laid out the way the clinic's report lays it out; no name or
number below comes from a real record.
"""

import json

import pytest

from anamna.health import _conclusion_span, _study_for, display_unit
from anamna.i18n import set_locale
from anamna.ingest.classifier import _vendor
from anamna.ingest.concepts import concept_for_alias, stable_concept_id
from anamna.ingest.parsers import parse_document
from anamna.locales import CONCEPT_NAMES_UK
from anamna.reference import LIBRARY_PATH, canonical_unit


def page(text, number=1, ocr="", words=None):
    item = {"page_number": number, "native_text": text, "ocr_text": ocr}
    if words is not None:
        item["words"] = words
    return item


def rows_of(clinical_type, pages):
    return [
        (row.raw_name, row.comparator, row.value_numeric if row.value_numeric is not None else row.value_text, row.specimen)
        for row in parse_document("", clinical_type, pages, age_years=35, sex="female")
    ]


def by_name(rows, name):
    return [row for row in rows if row[0] == name]


# MD Clinics: two columns of ovaries, its semicolons written as U+037E.
MD_PELVIC = """УЗД органів малого тазу у жінок
Дата обстеження: 02.03.2020
День МЦ: 21
Матка :
Тіло матки: довжина 50,0 мм; передньо-задній розмір 40,0 мм; поперечний розмір 48,0 мм.
Ендометрій
Візуалізується на всьому проміжку.
Товщина в передньо-задньому напрямку 11,0 мм
Структура відповідає фазі секреції.
Шийка матки: довжина 38,0 мм; товщина 27,0 мм;
Праві додатки Ліві додатки
Правий яєчник візуалізується чітко. Лівий яєчник візуалізується чітко.
Розміри: 33,0 х 29,0 х 31,0 мм. Розміри: 41,0 х 30,0 х 36,0 мм.
Розташування: типове. Розташування: типове.
Контури чіткі. Контури чіткі.
Структура: містить 12 антральних Структура: містить анехогенний утвір
фолікулів розміром 24 мм
Права маткова труба не візуалізується.
Висновок: Персистенція фолікула зліва."""

MD_PELVIC_WRAP = """УЗД органів малого тазу у жінок
Праві додатки Ліві додатки
Правий яєчник візуалізується чітко. Лівий яєчник візуалізується чітко.
Розміри: 30,0 х 38,0 х 24,0 мм. Розміри: 50,0 х 34,0 х 39,0 мм.
Структура: фолікулярна, містить жовте Структура: містить анехогенний утвір
тіло 19 мм розміром 25 х 23 мм і найбільший фолікул 15 мм
Права маткова труба не візуалізується.
Висновок: УЗ - ознаки кісти лівого яєчника."""


def test_md_clinics_pelvic_ultrasound_reads_uterus_cervix_endometrium_and_both_columns():
    items = parse_document("MD Clinics", "ultrasound", [page(MD_PELVIC)])
    rows = [(row.raw_name, row.value_numeric, row.specimen) for row in items]
    assert ("Uterine body length", 50.0, None) in rows
    assert ("Uterine body anteroposterior diameter", 40.0, None) in rows
    assert ("Uterine body width", 48.0, None) in rows
    assert ("Cervical length", 38.0, None) in rows and ("Cervical thickness", 27.0, None) in rows
    # Three unlabelled dimensions: the largest is the length.
    assert ("Ovary length", 33.0, "права") in rows and ("Ovary length", 41.0, "ліва") in rows
    # «фолікулів» finishes the right column, «розміром 24 мм» the left one.
    assert ("Antral follicle count", 12.0, "права") in rows
    assert ("Ovarian cyst largest diameter", 24.0, "ліва") in rows
    endometrium = next(item for item in items if item.raw_name == "Endometrial thickness")
    assert endometrium.value_numeric == 11.0
    assert endometrium.note == "День МЦ: 21; відповідає фазі секреції"
    # The cyst is never a soft-tissue lesion.
    assert not [row for row in rows if row[0].startswith("Soft tissue")]


def test_md_clinics_wrap_line_carries_both_columns():
    rows = rows_of("ultrasound", [page(MD_PELVIC_WRAP)])
    assert ("Corpus luteum diameter", None, 19.0, "права") in rows
    assert ("Ovarian cyst largest diameter", None, 25.0, "ліва") in rows
    assert ("Ovarian cyst smaller diameter", None, 23.0, "ліва") in rows
    assert ("Largest ovarian follicle diameter", None, 15.0, "ліва") in rows


INMED_PELVIC = """ОБСТЕЖЕННЯ ОРГАНІВ МАЛОГО ТАЗУ
Остання менструація: 01.01.2020 р. Ha 7 день менструального циклу.
Розміром: довж. 48 мм, передньо-задн. 36 мм, ширина 47 мм
Міометрій: структура неоднорідна; по передній стінці візуалізується
інтрамуральний вузол розміром 9 мм; в дні інтрамуральний вузол розміром 5х4 мм.
ендометрій однорідний, товщиною 4,2 мм, відповідає I фазі МЦ.
Правий яйник розташований типово. Розмірами 34 x 21 мм; Нормальної будови.
Містить фолікули до 12 мм;
O-RADS 1
Лівий яйник розташований типово. Розмірами 46 x 27 мм; Містить домінуючий
фолікул 18 мм; рідинне утворення з однорідним вмістом, аваскулярне, розміром 31x24 мм;
поруч, дрібне рідинне утворення, аваскулярне, розміром 11х7 мм; рідинне утворення
з вмістом по типу матового скла, розміром З0ха6 мм; рідинний утвір діаметром 287 мм; O-RADS 2
Шийка матки розміром 29 х 24 мм, без особливостей.
Заключення:
УЗ-ознаки кистозних змін лівого яйника (O-RADS 2)."""


def test_inmed_pelvic_sides_categories_lesions_and_paper_errors():
    rows = rows_of("diagnostic_image", [page("", ocr=INMED_PELVIC)])
    assert ("Uterine body length", None, 48.0, None) in rows
    assert ("Uterine lesion largest diameter", None, 9.0, "міометрій, передня стінка") in rows
    assert ("Uterine lesion largest diameter", None, 5.0, "міометрій, дно") in rows
    assert ("Cervical length", None, 29.0, None) in rows
    assert ("Ovary length", None, 34.0, "права") in rows
    assert ("Largest ovarian follicle diameter", "≤", 12.0, "права") in rows
    assert ("Largest ovarian follicle diameter", None, 18.0, "ліва") in rows
    assert by_name(rows, "Ovarian O-RADS category") == [
        ("Ovarian O-RADS category", None, 1.0, "права"), ("Ovarian O-RADS category", None, 2.0, "ліва"),
    ]
    # Two cysts in one ovary are two lesions; an OCR-garbled size and a size
    # no ovary can hold are not read at all.
    assert by_name(rows, "Ovarian cyst largest diameter") == [
        ("Ovarian cyst largest diameter", None, 31.0, "ліва"), ("Ovarian cyst largest diameter", None, 11.0, "ліва, 2"),
    ]
    item = next(item for item in parse_document("", "diagnostic_image", [page("", ocr=INMED_PELVIC)])
                if item.raw_name == "Endometrial thickness")
    assert item.note == "День МЦ: 7; відповідає I фазі МЦ"


def test_perinatal_centre_template():
    text = """Ультразвукове обстеження матки з додатками
Розміри: довжина 55 мм. передньо-задній 40 мм. Ширина 45 мм.
Структура шийки матки: 30х23 мм, без особливостей.
Праві додатки: розміри 31 мм. 20 мм. 24 мм. достатня кількість фолікулів
Ліві додатки: розміри 50 мм. 31 мм. 44 мм.
День менструального циклу: 5
Заключення Кисти лівого яйника"""
    rows = rows_of("ultrasound", [page(text)])
    assert ("Uterine body width", None, 45.0, None) in rows
    assert ("Cervical length", None, 30.0, None) in rows
    assert ("Ovary length", None, 31.0, "права") in rows and ("Ovary length", None, 50.0, "ліва") in rows


BREAST = """Огляд грудних залоз
Права грудна залоза
Шкіра не змінена; товщиною 1,4 мм;
Підшкірна жирова клітковина товщиною 3,1 мм;
Залозиста тканина товщиною 12,0 мм.
Виявлено на 10 год, 12 мм від ареоли, на глибині 4 мм від поверхні шкіри
візуалізується гіпоехогенне утворення, з чітким рівним контуром, розміром 7,5x4,5 мм,
аваскулярне; на 8 годину проста киста, діаметром 5 мм.
Ліва грудна залоза
Шкіра не змінена; товщиною 1,2 мм;
Залозиста тканина товщиною 11,5 мм.
Виявлено на 12 год кілька простих кист, діаметром до 4 мм; на 3 год скупчення кист, загальним розміром 12,0x6,0 мм;
на 2 год проста киста розміром 7х3 мм.
BI-RADS 2 - контрольне обстеження
Заключення: ультразвукові ознаки фіброаденоми правої грудної залози."""


def test_breast_ultrasound_sides_lesion_cysts_and_bi_rads():
    items = parse_document("", "ultrasound", [page(BREAST)])
    rows = [(row.raw_name, row.comparator, row.value_numeric, row.specimen) for row in items]
    assert ("Breast skin thickness", None, 1.4, "права") in rows
    assert ("Breast subcutaneous fat thickness", None, 3.1, "права") in rows
    assert ("Breast glandular tissue thickness", None, 11.5, "ліва") in rows
    assert ("Breast lesion largest diameter", None, 7.5, "права") in rows
    assert ("Breast lesion smaller diameter", None, 4.5, "права") in rows
    assert next(item for item in items if item.raw_name == "Breast lesion largest diameter").note == "10 год"
    # The cluster's 12 mm is not a cyst; the largest single cyst is 7 mm.
    assert ("Largest breast cyst diameter", None, 5.0, "права") in rows
    assert ("Largest breast cyst diameter", None, 7.0, "ліва") in rows
    assert ("Breast BI-RADS category", None, 2.0, None) in rows
    assert not [row for row in rows if row[0].startswith("Soft tissue")]


def test_inmed_thyroid_volumes_and_ti_rads_but_never_a_quoted_volume():
    text = """Огляд щитоподібної залози
Розміри правої частки: 16,0 х 15,0 х 45,0 Об'єм 5,70 см. куб.
Розміри лівої частки: 15,0 хі 3,0 x 43,0 Об'єм 4,60 см. куб.
Перешийок 2,4 мм.
Сумарний об'єм 10,30 см. куб.
Заключення: Структурних змін не виявлено.
TI-RADS 1"""
    rows = rows_of("diagnostic_image", [page("", ocr=text)])
    assert ("Thyroid volume", None, 5.7, "Права частка") in rows
    assert ("Thyroid volume", None, 4.6, "Ліва частка") in rows
    assert ("Thyroid volume", None, 10.3, "Сумарний") in rows
    assert ("Thyroid lobe length", None, 45.0, "Права частка") in rows
    # A garbled dimension costs the lobe its length, never a wrong one.
    assert ("Thyroid lobe length", None, 43.0, "Ліва частка") not in rows
    assert ("Thyroid isthmus thickness", None, 2.4, None) in rows
    assert ("Thyroid TI-RADS category", None, 1.0, None) in rows
    quoted = "Анамнез хвороби\nУЗД ЩЗ: об'єм 10,9 см3, без патологічних змін"
    assert by_name(rows_of("ultrasound", [page(quoted)]), "Thyroid volume") == []


EXPERT_DUPLEX = """Артеріальний сегмент псш Кровоплин, хід судини, інші
см/сек особливості
Загальна сонна артерія, права 101 Кровоплин магістральний, хід правильний
Внутрішня сонна артерія, права 72 Кровоплин магістральний, хід правильний
Хребцева артерія права, почат. 44 Кровоплин магістральний, хід рівний. D=3,3
сегмент мм
Хребцева артерія права, дист. 47 Кровоплин магістральний, хід рівний
сегмент
Загальна сонна артерія, ліва 99 Кровоплин магістральний, хід правильний
Дистальні відділи плечоголовного стовбура візуалізовані. КІМ справа 0,6 мм.
Транскраніальне дуплексне сканування
Артерії Vps, см/с
ПМА права 97 N-87-95
СМА ліва 120 N-109-116
ХА(V4) права 66 N-63-69
Базилярна 75 N-70-78"""

EXPERT_DUPLEX_WRAPPED = """Артеріальний псш Кровоплин, хід судини,
сегмент см/сек інші особливості
Загальна сонна артерія, Кровоплин магістральний, хід
101
права правильний
Хребцева артерія ліва, Кровоплин магістральний, хід
42
почат. сегмент правильний D=3,5 мм
Хребцева артерія ліва, Кровоплин магістральний, хід
48
дист. сегмент правильний
Дистальні відділи плечоголовного стовбура візуалізовані."""


def test_expert_duplex_without_norms_and_the_transcranial_table():
    rows = rows_of("ultrasound", [page(EXPERT_DUPLEX)])
    assert ("Peak systolic velocity, common carotid artery", None, 101.0, "права") in rows
    assert ("Peak systolic velocity, internal carotid artery", None, 72.0, "права") in rows
    assert ("Peak systolic velocity, common carotid artery", None, 99.0, "ліва") in rows
    assert ("Peak systolic velocity, vertebral artery", None, 44.0, "права, початковий сегмент") in rows
    assert ("Peak systolic velocity, vertebral artery", None, 47.0, "права, дистальний сегмент") in rows
    assert ("Vertebral artery diameter", None, 3.3, "права") in rows
    assert ("Peak systolic velocity, anterior cerebral artery", None, 97.0, "права") in rows
    assert ("Peak systolic velocity, middle cerebral artery", None, 120.0, "ліва") in rows
    assert ("Peak systolic velocity, intracranial vertebral artery (V4)", None, 66.0, "права") in rows
    assert ("Peak systolic velocity, basilar artery", None, 75.0, None) in rows
    basilar = next(item for item in parse_document("Expert Hospital", "ultrasound", [page(EXPERT_DUPLEX)])
                   if item.raw_name == "Peak systolic velocity, basilar artery")
    assert (basilar.reference_low, basilar.reference_high, basilar.unit_raw) == (70.0, 78.0, "см/с")
    wrapped = rows_of("ultrasound", [page(EXPERT_DUPLEX_WRAPPED)])
    assert ("Peak systolic velocity, common carotid artery", None, 101.0, "права") in wrapped
    assert ("Peak systolic velocity, vertebral artery", None, 42.0, "ліва, початковий сегмент") in wrapped
    assert ("Peak systolic velocity, vertebral artery", None, 48.0, "ліва, дистальний сегмент") in wrapped
    assert ("Vertebral artery diameter", None, 3.5, "ліва") in wrapped


def test_inmed_duplex_prose():
    text = """УЗД гілок дуги аорти
Товщина медіа-інтімального комплексу: справа 0,5-0,6 мм; зліва 0,6-0,7 мм.
Права внутрішня яремна вена 11 мм. (N до 14 мм)
Загальна сонна артерія: швидкість справа 95 см/с; зліва 104 см/с.
Проксимальний відділ внутрішньої сонної артерії: швидкість справа 101 см/с, зліва 99 см/с.
Діаметр правої вертебральної артерії: у сегменті V2 - 3,5 мм
Швидкість у початковому сегменті 52 см/с, RI 0,61, швидкість у дистальному сегменті 66 см/с."""
    items = parse_document("InMed", "ultrasound", [page(text)])
    rows = [(row.raw_name, row.value_numeric, row.specimen) for row in items]
    assert ("Peak systolic velocity, common carotid artery", 104.0, "ліва") in rows
    assert ("Peak systolic velocity, internal carotid artery", 101.0, "права") in rows
    assert ("Vertebral artery diameter", 3.5, "права") in rows
    assert ("Peak systolic velocity, vertebral artery", 52.0, "права, початковий сегмент") in rows
    assert ("Peak systolic velocity, vertebral artery", 66.0, "права, дистальний сегмент") in rows
    assert ("Vertebral artery resistive index", 0.61, "права, початковий сегмент") in rows
    vein = next(item for item in items if item.raw_name == "Internal jugular vein diameter")
    assert (vein.value_numeric, vein.specimen, vein.reference_high) == (11.0, "права", 14.0)
    # A range is two numbers, not one intima-media thickness.
    assert not [row for row in rows if row[0] == "Carotid intima-media thickness"]


def test_gallbladder_emptying_test_and_its_result_on_the_next_sheet():
    first = """Проведено пробу з жовчогінним сніданком.
-натще 60х21х24 мм, об'єм 16,2 см.куб.;
- чепез 15 хв 55x20x20 мм, об'єм 11,4 см.куб.
-через 45 хв 50х15х14 мм, об'єм 5,5 см.куб."""
    rows = rows_of("ultrasound", [page("", ocr=first)])
    assert by_name(rows, "Gallbladder volume") == [
        ("Gallbladder volume", None, 16.2, "натще"), ("Gallbladder volume", None, 11.4, "через 15 хв"),
        ("Gallbladder volume", None, 5.5, "через 45 хв"),
    ]
    second = "Жовчевий міхур після харчового навантаження скоротився на 66%, що свідчить про нормокінетичний стан (норма 40-70%)"
    fraction = next(item for item in parse_document("", "ultrasound", [page("", ocr=second)])
                    if item.raw_name == "Gallbladder ejection fraction")
    assert (fraction.value_numeric, fraction.reference_low, fraction.reference_high) == (66.0, 40.0, 70.0)


EEG = """Висновок ЕЕГ
Домінує альфа‐ритм із середньою частотою 10 Гц та амплітудою до 120 мкВ, поширений
дифузно. Бета‐ритм реєструється з середньою частотою 18,5 Гц та амплітудою до 15 мкВ.
Тета‐ритм з середньою частотою 5,5 Гц та амплітудою до 30 мкВ.
‐ Фотостимуляція проводилась в діапазоні частот 6‐24 Гц."""


def test_eeg_rhythm_frequencies_and_amplitudes():
    rows = rows_of("consultation", [page(EEG)])
    assert ("EEG alpha rhythm frequency", None, 10.0, None) in rows
    assert ("EEG alpha rhythm amplitude", "≤", 120.0, None) in rows
    assert ("EEG beta rhythm frequency", None, 18.5, None) in rows
    assert ("EEG theta rhythm amplitude", "≤", 30.0, None) in rows
    assert len([row for row in rows if row[0].startswith("EEG")]) == 6
    assert canonical_unit("Гц") == canonical_unit("Hz") and canonical_unit("мкВ") == canonical_unit("µV")
    set_locale("uk")
    try:
        assert (display_unit("Hz"), display_unit("µV")) == ("Гц", "мкВ")
    finally:
        set_locale("en")


def _word(x, top, text, width=8.0):
    return (x, x + width, top, text)


def test_breath_test_chart_labels_from_word_positions():
    text = "Дихальний тест на визначення надмірного бактерійного росту у кишківнику.\nРеагент: глюкоза.\n30\n27\n20\n18\n10\n0\n0 хв 15 хв 30 хв"
    words = [
        _word(40, 30, "097"), _word(160, 30, "33"),          # letterhead phone digits above a column
        _word(92, 100, "30"), _word(92, 140, "20"), _word(92, 180, "10"), _word(92, 220, "0"),  # y axis
        _word(158, 150, "18"), _word(238, 120, "27"), _word(318, 185, "9"),                  # data labels
        _word(155, 240, "0"), _word(165, 240, "хв"), _word(235, 240, "15"), _word(248, 240, "хв"),
        _word(315, 240, "30"), _word(328, 240, "хв"),
    ]
    rows = rows_of("clinical_report", [page(text, words=words)])
    assert by_name(rows, "Breath hydrogen") == [
        ("Breath hydrogen", None, 18.0, "глюкоза, 0 хв"), ("Breath hydrogen", None, 27.0, "глюкоза, 15 хв"),
        ("Breath hydrogen", None, 9.0, "глюкоза, 30 хв"),
    ]
    # Without positions the labels cannot be told from the axis: nothing.
    assert by_name(rows_of("clinical_report", [page(text)]), "Breath hydrogen") == []


def test_gastrolife_table_and_the_h_pylori_breath_test():
    table = "Синдром надмірного бактерійного росту\nЧас забору зразка (PPM)\n1. базальний 6\n2. 20 хвилина 5\n5. 80хвилина\n"
    assert by_name(rows_of("diagnostic_image", [page("", ocr=table)]), "Breath hydrogen") == [
        ("Breath hydrogen", None, 6.0, "0 хв"), ("Breath hydrogen", None, 5.0, "20 хв"),
    ]
    pylori = "Консультативний висновок за результатами дихального тесту\nРезультати тесту:\nHelicobacter pylori не виявлено."
    assert rows_of("diagnostic_image", [page("", ocr=pylori)]) == [("H. pylori urea breath test", None, "не виявлено", None)]


@pytest.mark.parametrize(("text", "vendor"), [
    ("Україні є ТОВ «НЕОМЕД 2007» mdclinics.com.ua лабораторного експерта", "MD Clinics"),
    ("медичний центр ІнМед м. Львів вул Мазепи, 25 Д", "InMed"),
    ("м.львів вул мазепи, 25д", "InMed"),
    ("www.ultramed.lviv колоноптозу", "UltraMed"),
    ("медичний центр тов \"клініка лоно\"", "LONO Clinic"),
    ("healthcare services medicover", "Medicover"),
    ("parens-ukraine", "PARENS"),
    ("тзов \"львів медікал центр хірургія\"", "Lviv Medical Center"),
    ("львівський обласний клінічний перинатальний центр", "Lviv Regional Clinical Perinatal Center"),
    ("gastrolife.ua", "GastroLife"),
    ("тзов «лікарня експерт»", "Expert Hospital"),
])
def test_vendor_rules_from_printed_headers(text, vendor):
    assert _vendor("file.pdf", text.casefold(), "")[0] == vendor


def test_studies_and_conclusion_labels():
    assert _study_for("УЗД органів малого тазу у жінок", "ultrasound")[2] == ("reproductive",)
    assert _study_for("Огляд грудних залоз", "diagnostic_image")[0] == "breast_us"
    assert _study_for("Протокол кольпоскопії", "diagnostic_image")[0] == "colposcopy"
    assert _study_for("Езофагогастродуоденоскопія", "clinical_report")[0] == "egd"
    assert _study_for("Дихальний тест на визначення надмірного бактерійного росту", "clinical_report")[0] == "breath_test"
    # A visit note that quotes a gastroscopy is a consultation, not the procedure.
    assert (_study_for("Консультація терапевта. ФГДС від 2020 року", "consultation") or ("",))[0] != "egd"
    assert _study_for("Консультація гінеколога", "consultation")[0] == "consult_gynecology"
    assert _conclusion_span("Шлунок: без змін.\nЗаключення лікаря: Гастропатія.") is not None
    assert _conclusion_span("Опис\nДіагноз кольпоскопічний: Нормальна кольпоскопічна картина.") is not None


NEW_CONCEPTS = [
    "Peak systolic velocity, anterior cerebral artery", "Peak systolic velocity, middle cerebral artery",
    "Peak systolic velocity, intracranial vertebral artery (V4)", "Peak systolic velocity, basilar artery",
    "Vertebral artery resistive index", "Internal jugular vein diameter",
    "Uterine body length", "Uterine body anteroposterior diameter", "Uterine body width", "Endometrial thickness",
    "Cervical length", "Cervical thickness", "Ovary length", "Ovarian volume", "Antral follicle count",
    "Largest ovarian follicle diameter", "Corpus luteum diameter", "Ovarian cyst largest diameter",
    "Ovarian cyst smaller diameter", "Ovarian O-RADS category", "Uterine lesion largest diameter",
    "Uterine lesion smaller diameter", "Breast BI-RADS category", "Breast lesion largest diameter",
    "Breast lesion smaller diameter", "Largest breast cyst diameter", "Breast skin thickness",
    "Breast subcutaneous fat thickness", "Breast glandular tissue thickness", "Gallbladder ejection fraction",
    "Gallbladder volume", "EEG alpha rhythm frequency", "EEG alpha rhythm amplitude", "EEG beta rhythm frequency",
    "EEG beta rhythm amplitude", "EEG theta rhythm frequency", "EEG theta rhythm amplitude", "Breath hydrogen",
    "H. pylori urea breath test",
]
ANALYTES = {entry["concept_id"]: entry for entry in json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))["analytes"]}


@pytest.mark.parametrize("name", NEW_CONCEPTS)
def test_every_new_concept_maps_names_itself_in_ukrainian_and_has_sourced_guidance(name):
    definition = concept_for_alias(name)
    assert definition is not None and definition["name"] == name
    assert CONCEPT_NAMES_UK.get(name)
    entry = ANALYTES[stable_concept_id(name)]
    assert entry["source_ids"] and entry["regions_covered"]
    assert entry["kind"] != "no_universal_target" or entry.get("no_target_reason")
    assert entry["uk"]["name"] and entry["uk"]["short_description"]
