"""Round-3 review: findings, ultrasound readers, consultation vitals, page seams.

Every line below is synthetic, shaped like the photographed pages that went
wrong (OCR of a phone photo: lost colons, Latin lookalikes, wrapped words,
margin debris).  Names, dates and numbers are invented."""
from __future__ import annotations

from pathlib import Path

from anamna.health import _clean_block, _strip_letterhead, finding_attention
from anamna.ingest.parsers import parse_ultrasound, parse_visit_measurements

from test_clinical_findings import add_report, findings, ledger  # noqa: F401
from test_document_copies import _batch, add_document, no_worker, relate  # noqa: F401
from test_rescan import build


def rows(text: str, name: str | None = None):
    found = parse_ultrasound(text, 1)
    return [row for row in found if name is None or row.raw_name == name]


def values(text: str, name: str) -> list[tuple[float, str | None]]:
    return [(row.value_numeric, row.specimen) for row in rows(text, name)]


# --- 1, 9: a polyp or adenoma outside the bowel is not colorectal -------------

def test_fibroadenoma_and_an_endometrial_polyp_are_not_colorectal_polyps():
    assert finding_attention("ультразвукові ознаки фіброаденоми правої грудної залози") == []
    assert finding_attention("Fibroadenoma of the right breast") == []
    assert finding_attention("УЗ - ознаки поліпу ендометрію?") == []
    # Filed only under the reproductive area, a bare «поліп?» is not the bowel's.
    assert finding_attention("Поліп?", ("reproductive",)) == []
    assert finding_attention("Тубулярна аденома сигмовидної кишки") == ["colorectal_polyp"]
    assert finding_attention("Поліп?", ("digestive",)) == ["colorectal_polyp"]


def test_a_pelvic_scan_with_an_endometrial_polyp_is_not_under_bowel_attention(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "pelvic", "ultrasound", "УЗД органів малого тазу",
               ["Матка розміром 50 х 40 мм.\nВисновок: УЗ - ознаки кісти лівого яєчника. УЗ - ознаки поліпу ендометрію?\n"])
    [row] = findings(settings)
    assert row["health_area"] == "reproductive"
    assert row["attention_reasons"] == "" and row["status"] == "information"


# --- 2: sizes as OCR spells them; the largest cyst or nothing -----------------

BREAST = """Огляд грудних залоз
Права грудна залоза
Шкіра не змінена; товщиною 1,5 мм;
Виявлено на 10 год, 8 мм від ареоли
візуалізується гіпоехогенне утворення, з чітким рівним контуром, розміром 6X3 мм,
аваскулярне; 7 параареолярно кистозне включення діаметром 3 мм, поруч діаметром 4 м.м
на годину,
Ліва грудна залоза
Шкіра не змінена; товщиною 1,4 мм;
Виявлено : на 1 годину кілька кист, макс. діаметром 5 MM;
на 2 годину киста діаметром 8 мм;
на 4 годину кистозне включення, з кальцинатом в структурі, розміром 6,1Х2,2 MM
BI-RADS 2 - контрольне обстеження кожних 6-12 місяців
Заключення: ультразвукові ознаки фіброаденоми правої грудної залози.
"""


def test_breast_sizes_with_capital_x_and_dotted_millimetres_and_the_largest_cyst():
    assert values(BREAST, "Breast lesion largest diameter") == [(6.0, "права")]
    assert values(BREAST, "Breast lesion smaller diameter") == [(3.0, "права")]
    # «поруч діаметром 4 м.м» is the larger right cyst; «макс. діаметром 5 MM»
    # stays one clause; the left side's largest is the 8 mm cyst.
    assert values(BREAST, "Largest breast cyst diameter") == [(4.0, "права"), (8.0, "ліва")]


def test_a_cyst_whose_size_ocr_lost_stores_no_largest_cyst():
    lost = """Права грудна залоза
Виявлено на 12 год проста киста діаметром 3 мм;
на 4 год проста киста діаметром з кистозними включеннями
Ліва грудна залоза
Виявлено :
-на 1 2 ГОД. кистозне включення
-на3 ГОД. кистозне включення, розміром 4,5x2,0 мм.
Ліва грудна залоза без кист.
Заключення: прості кисти.
"""
    assert values(lost, "Largest breast cyst diameter") == []


def test_bi_rads_split_over_two_lines_by_ocr():
    split = BREAST.replace("BI-RADS 2 - контрольне обстеження кожних 6-12 місяців",
                           "2 обстеження кожних 6-12 місяців\nBI-RADS - контрольне")
    assert values(split, "Breast BI-RADS category") == [(2.0, None)]
    assert values(BREAST.replace("BI-RADS 2", "BI- RADS 3"), "Breast BI-RADS category") == [(3.0, None)]


# --- 3: capitalised abdominal headings, «Жовчний» -----------------------------

def test_capitalised_abdominal_headings_keep_each_organs_sizes_apart():
    text = """ПЕЧІНКА.
Ліва частка: 61 мм.
ЖОВЧНИЙ МІХУР.
Розташований типово, розміри: 66 х 24 мм.
СЕЛЕЗІНКА.
Розмірами: 101 * 38 мм.
"""
    assert values(text, "Liver left lobe size") == [(61.0, "ліва частка")]
    assert values(text, "Gallbladder length") == [(66.0, None)]
    assert values(text, "Spleen length") == [(101.0, None)]
    # The spleen's pair is never read as the gallbladder's.
    assert values(text, "Gallbladder width") == [(24.0, None)]


# --- 10: a size triple read down to one figure keeps all three ----------------

def test_an_ovary_and_a_thyroid_lobe_keep_their_printed_triple():
    pelvic = """Тіло матки: довжина 50,0 мм; передньо-задній розмір 40,0 мм; поперечний розмір 48,0 мм.
Праві додатки: Розміри: 30,0 х 28,0 х 33,0 мм.
Ліві додатки: Розміри: 35,0 х 29,0 х 31,0 мм.
Висновок: без патології.
"""
    ovaries = {row.specimen: row for row in rows(pelvic, "Ovary length")}
    assert ovaries["права"].value_numeric == 33.0
    assert ovaries["права"].note == "Розміри: 30,0 х 28,0 х 33,0 мм"
    assert ovaries["ліва"].note == "Розміри: 35,0 х 29,0 х 31,0 мм"
    thyroid = "Розміри правої частки: 15,5 х 14,0 х 45,0 Об'єм 5,20 см. куб.\nTI-RADS 1"
    [lobe] = rows(thyroid, "Thyroid lobe length")
    assert lobe.value_numeric == 45.0 and lobe.note == "Розміри правої частки: 15,5 х 14,0 х 45,0"


# --- 4, 6: conclusion anchors, debris, wrapped words --------------------------

def summary_of(ledger, doc_id, clinical_type, title, text, report_date="2025-02-01"):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, doc_id, clinical_type, title, [text], report_date=report_date)
    return [row for row in findings(settings) if row["document_id"] == doc_id]


def test_expert_form_with_latin_mkx_and_no_recommendation_label(ledger):
    text = """Пацієнт: Тестенко Тарас
Шкіра перианальної ділянки незмінена.
по MKX-10 (Основний): -. Опис: Гостра анальна тріщина. Внутрішній геморой | ст.
Вживання 2 л води за добу
Свічки Тестозол 1 раз на день 10 днів
Огляд за потреби
і
"""
    [row] = summary_of(ledger, "fissure", "consultation", "Консультативний висновок", text)
    assert row["summary_uk"] == "Гостра анальна тріщина. Внутрішній геморой І ст."
    assert row["health_area"] == "digestive"
    assert row["recommendations"].startswith("Вживання 2 л води за добу; Свічки Тестозол")
    assert row["recommendations"].endswith("Огляд за потреби")


def test_a_preliminary_diagnosis_of_abbreviations_files_a_digestive_finding(ledger):
    text = """Консультативне заключення
Скарги: здуття.
Попередній діагноз: СПК? СНБР?
Супутній: -
Рекомендації:
Копрограма.
"""
    [row] = summary_of(ledger, "ibs", "consultation", "Консультативне заключення", text)
    assert row["summary_uk"] == "СПК? СНБР?"
    assert row["health_area"] == "digestive"


def test_the_clinical_diagnosis_box_wins_over_complaints(ledger):
    text = """Консультація гінеколога
Скарги на момент огляду:
- біль низом живота.
ДІАГНОЗ КЛІНІЧНИЙ:
Фолікулярні кисти обох яєчників.
| Вузлова міома матки.
РЕКОМЕНДОВАНО:
1. УЗД через 3 місяці
"""
    [row] = summary_of(ledger, "lono", "consultation", "Консультація гінеколога", text)
    assert row["summary_uk"] == "Фолікулярні кисти обох яєчників. Вузлова міома матки."


def test_form_110_specialist_conclusion_and_main_diagnosis(ledger):
    text = """Консультаційний висновок лікаря акушера-гінеколога
Висновок спеціаліста:
e Основний діагноз:
Аденоміоз. Вузлова лейоміома матки.
|
Супутній діагноз:
Рекомендації:
1.Фізичний | статевий спокій 7 днів.
14 квітня 2026 р. Тестенко О.О.
Лікар
"""
    [row] = summary_of(ledger, "f110", "consultation", "Консультаційний висновок", text)
    assert row["summary_uk"] == "Аденоміоз. Вузлова лейоміома матки."
    assert row["recommendations"] == "1.Фізичний і статевий спокій 7 днів."


def test_colposcopy_and_ultrasound_conclusions_as_ocr_spells_them(ledger):
    colposcopy = "Діагноз кол ьпоскопічний:\nНормальна кольпоскопічна картина\nІнші ознаки\nДіагноз клінічний\n"
    [row] = summary_of(ledger, "colpo", "diagnostic_image", "Diagnostic image", colposcopy)
    assert row["summary_uk"] == "Нормальна кольпоскопічна картина"
    no_colon = "Лівий яйник розміром 40 х 30 мм.\nЗаключення Кисти лівого яйника: ендометріоїдна та серозна?\nРекомендовано консультація гінеколога.\nДате: 03.04.2025\n"
    [row] = summary_of(ledger, "nocolon", "ultrasound", "УЗД органів малого тазу", no_colon)
    assert row["summary_uk"] == "Кисти лівого яйника: ендометріоїдна та серозна?"
    assert row["recommendations"] == "консультація гінеколога."
    lost_letter = "Печінка не збільшена.\nаключення: Структурних змін з боку органів черевної порожнини не виявлено.\nЛікар: Тестенко\n"
    [*rows_] = summary_of(ledger, "lost", "ultrasound", "УЗД органів черевної порожнини", lost_letter)
    assert rows_[0]["summary_uk"] == "Структурних змін з боку органів черевної порожнини не виявлено."


def test_icd_code_with_a_cyrillic_letter_is_stored_latin_and_margin_debris_is_dropped(ledger):
    text = """Консультація гастроентеролога
основний: К21.0 Гастроезофагеальний рефлюкс з езофагітом
Ai Гастропатія. Бульбопатія.
Дані лабораторних та
"""
    [row] = summary_of(ledger, "gerd", "consultation", "Консультація гастроентеролога", text)
    assert row["summary_uk"].startswith("K21.0 Гастроезофагеальний рефлюкс")
    assert "К21" not in row["summary_uk"] and "Ai" not in row["summary_uk"]
    xray = """Результат:
a
з На рентгенограмі ОГК легеневий рисунок
ої збагачений за рахунок судинного компоненту. Корені
С структурні. Синуси вільні.
Рекомендовано: Консультація терапевта. Загальний аналіз крові з лейкоцитарною
формулою
| ЕД = 0.05 мЗв
"""
    [row] = summary_of(ledger, "xray", "radiology_xray", "Рентгенографія ОГК", xray)
    assert row["summary_uk"] == ("На рентгенограмі ОГК легеневий рисунок збагачений за рахунок судинного компоненту. "
                                 "Корені структурні. Синуси вільні.")
    # The wrapped last word of the advice is kept.
    assert row["recommendations"].endswith("з лейкоцитарною формулою")


def test_debris_rules_never_drop_a_negation():
    assert "Не виявлено" in _clean_block("Патологічних змін\nНе\nвиявлено.")
    assert _clean_block("He збільшена.") == "He збільшена."
    assert _clean_block("ознаки фіброаденоми правої грудної залози. ae") == "ознаки фіброаденоми правої грудної залози."
    assert _clean_block("Т 36,6.") == "Т 36,6."


def test_the_whole_conclusion_and_a_scale_category_line_are_kept(ledger):
    pelvic = "Матка 50 х 40 мм.\nЗаключення:\nУЗ-ознаки аденоміозу тіла матки, кистозних змін обох\nяйників,\nРекомендовано: консультація гінеколога.\n"
    [row] = summary_of(ledger, "wrap", "ultrasound", "УЗД органів малого тазу", pelvic)
    assert row["summary_uk"] == "УЗ-ознаки аденоміозу тіла матки, кистозних змін обох яйників"
    thyroid = "Огляд щитоподібної залози\nПерешийок 2,0 мм.\nЗаключення: Структурних змін не виявлено.\nTI-RADS 1\nЛікар: Тестенко\n"
    [row] = summary_of(ledger, "tirads", "ultrasound", "УЗД щитоподібної залози", thyroid)
    assert row["summary_uk"] == "Структурних змін не виявлено. TI-RADS 1"


def test_three_undated_scans_of_one_study_stay_three_findings(ledger):
    settings, owner, patient = ledger
    text = "Огляд щитоподібної залози\nПерешийок 2,{n} мм.\nЗаключення: Структурних змін не виявлено.\n"
    for index in range(3):
        add_report(settings, owner, patient, f"thy-{index}", "ultrasound", "Огляд щитоподібної залози",
                   [text.format(n=index)], report_date=None)
    assert {row["document_id"] for row in findings(settings)} == {"thy-0", "thy-1", "thy-2"}


# --- 5: a line of figures alone is part of the body ---------------------------

def test_the_body_keeps_a_wrapped_line_that_holds_only_a_number():
    text = "Скарги на слабкість.\nФеритин 12 норма більше\n30.\nприймає препарати заліза.\n"
    assert _strip_letterhead(text) == "Скарги на слабкість.\nФеритин 12 норма більше\n30.\nприймає препарати заліза."


# --- 7: vitals a photo's OCR left readable ------------------------------------

def test_unitless_weight_metre_height_and_latin_at_pressure_are_read():
    text = "Клінічні дані: скарги на біль\nВага - 61\nЗріст 1.70\nCC 70/xp. AT 105/65 мм р =\n"
    found = {row.raw_name: row for row in parse_visit_measurements([{"page_number": 1, "ocr_text": text}])}
    assert (found["Вага"].value_numeric, found["Вага"].unit_raw) == (61.0, "кг")
    assert (found["Зріст"].value_numeric, found["Зріст"].unit_raw) == (170.0, "см")
    assert found["Систолічний артеріальний тиск"].value_numeric == 105.0
    assert found["Діастолічний артеріальний тиск"].unit_raw == "мм рт.ст."
    # A dose or a reference beside «Вага» is not a bare weight line.
    assert not parse_visit_measurements([{"page_number": 1, "ocr_text": "Вага - 61 при нормі 50"}])


# --- 8: a clinic's letterhead is no page seam ----------------------------------

LETTERHEAD = """МЕДИЧНИЙ ЦЕНТР ТОВ "Клініка Тест"
м. Львів, вул. Тестова, буд. 9-А
Тел.: +380770000000
Ел. пошта: test.clinic@example.test
Дата звернення: 03.03.2026
Дата народження: 01.01.1990
"""


def test_two_papers_of_one_visit_sharing_a_letterhead_are_not_parts(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_document(settings, "scan-sheet", ocr=LETTERHEAD + "Ультразвукове обстеження органів малого тазу\n",
                 mime="image/jpeg")
    add_document(settings, "consult", ocr=LETTERHEAD + "Консультація гінеколога\nСкарги на біль низом живота після встановлення спіралі\n"
                 "ДІАГНОЗ КЛІНІЧНИЙ:\nФолікулярні кисти обох яєчників та вузлова міома матки\n", mime="image/jpeg")
    from anamna.db import connect
    with connect(settings) as connection:
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
    _batch(settings, user_id, patient, "batch-1", "scan-sheet", "consult")
    assert not {row for row in relate(settings, user_id, "scan-sheet", "consult") if row[2] == "part_of"}
