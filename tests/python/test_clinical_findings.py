"""Narrative findings: the labelled conclusion only, filed by study, judged by
its own vocabulary, explained with cited sources, one finding per study.

Every report below is synthetic, shaped like the real ones that went wrong
(letterhead stored as the conclusion, a neurology consult filed under the
intestines, a serrated adenoma shown as "Information", a re-issued biopsy
shown twice)."""
import json

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect, migrate, utc_now
from anamna.health import (
    FINDING_EXPLANATION_SOURCES,
    _extract_date,
    _library_sources,
    finding_attention,
    metric_area_ids,
    present_finding,
    sync_clinical_findings,
)
from anamna.i18n import activate_locale
from anamna.ingest.pipeline import ensure_vendor
from anamna.locales.messages import MESSAGES
from anamna.security import create_session, create_user
from anamna.web.app import _area_table, create_app
from test_web_security import PASSWORD, settings_for

LETTERHEAD = """ТзОВ «ТЕСТ МЕДІКАЛ»
www.test-clinic.example.ua
м. Львів, вул. Тестова 1
+38 097 00 00 000,
Прізвище, ім'я, по-батькові пацієнта: Тестенко Тарас Іванович
Дата народження: 01.03.1990 р.
"""
FOOTER = """До відома пацієнта: надане заключення не є остаточним діагнозом і потребує консультації спеціаліста.
Підпис пацієнта ___________
Дата дослідження: Лікаренко Олена
Лікар:
01.02.2025 __________
Директор «Лікарня ТЕСТ»
"""


@pytest.fixture
def ledger(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "findings@example.test", "Findings", PASSWORD)
    patient = f"patient-{owner}"
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)"
            " VALUES (?, ?, 'Тарас Тестенко', '1990-03-01', 'male', ?)",
            (patient, owner, utc_now()),
        )
        ensure_vendor(connection, "Test Clinic", None)
    return settings, owner, patient


def add_report(settings, owner, patient, doc_id, clinical_type, title, pages, report_date="2025-02-01", imported="2026-01-01"):
    source = settings.source_dir / f"{doc_id}.pdf"
    source.write_text(doc_id, encoding="utf-8")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status)
               VALUES (?, ?, ?, (SELECT id FROM vendors LIMIT 1), ?, ?, 'application/pdf', 1, ?, ?, ?, ?, 'native_text', 1, ?, ?, 'final')""",
            (doc_id, owner, patient, f"{doc_id}.pdf", str(source), f"sha-{doc_id}", len(pages), title,
             clinical_type, report_date, imported),
        )
        for number, text in enumerate(pages, 1):
            native, ocr = (text if isinstance(text, tuple) else (text, None))
            connection.execute(
                "INSERT INTO document_pages(document_id, page_number, native_text, ocr_text, extraction_method, review_status)"
                " VALUES (?, ?, ?, ?, 'native', 'not_reviewed')",
                (doc_id, number, native, ocr),
            )
    return doc_id


def findings(settings):
    with connect(settings) as connection:
        sync_clinical_findings(connection)
        return [dict(row) for row in connection.execute(
            "SELECT * FROM clinical_findings ORDER BY document_id, health_area"
        )]


ABDOMINAL = [
    LETTERHEAD + "ПРОТОКОЛ\nУЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ органів черевної порожнини\nПечінка збільшена в розмірах:\n"
    "Права частка: 164.7 мм.\nСечовий міхур: Стінка потовщена – 4.5 мм.\n",
    "Селезінка не збільшена.\nВИСНОВОК:\nНа момент огляду УЗ ознаки Дифузних змін печінки по типу гепатозу. "
    "Гепатомегалії. Холестазу в помірній\nкількості.\nРЕКОМЕНДОВАНО: консультація гастроентеролога\n" + FOOTER,
]


def test_summary_is_the_labelled_conclusion_and_no_identity_is_stored(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "abd", "ultrasound", "УЗД черевної порожнини", ABDOMINAL)
    rows = findings(settings)
    assert {row["health_area"] for row in rows} == {"liver", "kidneys"}
    row = next(row for row in rows if row["health_area"] == "liver")
    assert row["summary_uk"].startswith("На момент огляду УЗ ознаки Дифузних змін печінки")
    assert row["summary_uk"].endswith("Холестазу в помірній кількості.")
    # Ukrainian wording never sits in the English column.
    assert row["summary_en"] == ""
    assert row["page_number"] == 2
    assert row["finding_date"] == "2025-02-01"
    assert row["status"] == "attention"
    assert row["attention_reasons"] == "fatty_liver,cholestasis"
    assert row["recommendations"] == "консультація гастроентеролога"
    assert row["title"] == "Abdominal ultrasound"
    for leaked in ("www.", "+38", "Тестенко", "01.03.1990", "вул.", "ТзОВ", "Директор", "Підпис", "не є остаточним"):
        assert leaked not in row["original_text"], leaked
        assert leaked not in row["summary_uk"], leaked
    assert "Стінка потовщена – 4.5 мм." in row["original_text"]


@pytest.mark.parametrize(
    ("clinical_type", "title", "text", "areas", "status"),
    [
        # «Сакроілеїт» once filed this under the intestines (it contains «ілеїт»).
        ("consultation", "Консультація невролога",
         "Консультативний висновок лікаря невролога\nПопередній діагноз:\nЗагострення вертеброгенної торакалгії. Сакроілеїт?\nРекомендовано:\nМРТ",
         {"spine"}, "attention"),
        # «шийного» in a cervical-spine MRI once filed it under ENT.
        ("radiology_mri", "МРТ шийного відділу хребта",
         "МРТ шийного відділу хребта\nОпис: ...\nВИСНОВОК: МР-ознаки початкового остеохондрозу.\nРЕКОМЕНДОВАНО:\nневролог",
         {"spine"}, "information"),
        ("ultrasound", "УЗД судин шиї",
         "ПРОТОКОЛ ДУПЛЕКСНОГО ДОСЛІДЖЕННЯ СОННИХ ТА ВЕРТЕБРАЛЬНИХ АРТЕРІЙ\nХребцева артерія 39\n"
         "ЗАКЛЮЧЕННЯ: на момент огляду ознак гемодинамічних розладів по сонних артеріях не виявлено.\nДо відома пацієнта",
         {"heart"}, "information"),
        ("ultrasound", "УЗД серця",
         "ПРОТОКОЛ УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ СЕРЦЯ\nЛегенева гіпертензія відсутня.\n"
         "Висновок: Лівий шлуночок не розширений. Ознак легеневої гіпертензії немає.\nРезультати ультразвукового дослідження не є діагнозом",
         {"heart"}, "information"),
        ("electrocardiogram", "Kardia 6-lead ECG",
         "EKG Recording\nKardia Advanced Determination:\nNormal Sinus Rhythm\n* Kardia Advanced Determination is done on Lead I.",
         {"heart"}, "information"),
        ("radiology_xray", "Рентгенографія ОГК",
         "Ділянка тіла: Рентгенографія ОГК\nВисновок:\nЛегеневий рисунок дещо збагачений.\nВисновок: видимої вогнищево-інфільтративної\nпатології не виявлено.\nЕД - 0.02 мЗв",
         {"lungs"}, "information"),
        ("ultrasound", "УЗД м'яких тканин спини",
         "УЛЬТРАЗВУКОВЕ ДОСЛІДЖЕННЯ М’ЯКИХ ТКАНИН\nЗАКЛЮЧЕННЯ: Ліпоми спини\nРекомендовано : спостереження в динаміці",
         {"joints"}, "attention"),
        ("ultrasound", "УЗД слинних залоз",
         "Область дослідження: л/вузли, слинні залози.\nВИСНОВОК:\nЗапальних змін привушної слинної залози справа.\n"
         "Вираженої правобічної шийної лімфаденопатії.\nРекомендовано:\nКонсультація інфекціоніста",
         {"ent"}, "attention"),
        ("radiology_mri", "МРТ грудного відділу хребта",
         "МРТ грудного відділу хребта\nВИСНОВОК: МР-ознаки помірного остеохондрозу. Екструзія м/х диска Th11-Th12.\nРЕКОМЕНДОВАНО:",
         {"spine"}, "attention"),
        # A protrusion alone is an age-related change, not a reason to act.
        ("radiology_mri", "МРТ поперекового відділу хребта",
         "МРТ поперекового відділу хребта\nВИСНОВОК: МР-ознаки помірного остеохондрозу. Протрузія м/х диска L5-L6.\nРЕКОМЕНДОВАНО:",
         {"spine"}, "information"),
    ],
)
def test_area_comes_from_the_study_and_status_from_the_conclusion(ledger, clinical_type, title, text, areas, status):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "doc", clinical_type, title, [text])
    rows = findings(settings)
    assert {row["health_area"] for row in rows} == areas
    assert {row["status"] for row in rows} == {status}


def test_serrated_adenoma_is_attention_with_a_sourced_explanation_and_reissue_is_one_finding(ledger):
    settings, owner, patient = ledger
    clean = ("Патологогістологічне дослідження № 1/25\nДата дослідження: 12.11.2025\nГістологічний висновок:\n"
             "1. Зміни відповідають хронічному неактивному ілеїту. Необхідна кореляція з клінічними даними.\n"
             "2. Морфологія процесу відповідає фрагментам зубчастої аденоми. Необхідна кореляція з клінічними даними.\n"
             "coe ЄЖЕНОЮ\nRy\nЛікар-патологоанатом Тест")
    garbled = clean.replace("висновок", "BUCHOBOK").replace("хронічному неактивному", "хронІчному неактИвному").replace(
        "клінічними", "КЛІНІЧНИМИ ДанимМИи")
    add_report(settings, owner, patient, "biopsy-a", "pathology", "БІОПСІЯ СЛИЗОВОЇ ОБОЛОНКИ КИШКІВНИКА",
               [("", garbled), ("Сайт лікарні", None)], report_date="2025-11-12", imported="2026-01-01")
    add_report(settings, owner, patient, "biopsy-b", "pathology", "БІОПСІЯ СЛИЗОВОЇ ОБОЛОНКИ КИШКІВНИКА",
               [("", clean), ("Сайт лікарні", None)], report_date="2025-11-22", imported="2026-01-02")
    rows = findings(settings)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["document_id"] == "biopsy-b"  # the legible copy wins
    assert row["health_area"] == "digestive"
    assert row["status"] == "attention"
    assert row["finding_date"] == "2025-11-12"  # the study date, not the re-issue date
    assert "зубчастої аденоми" in row["summary_uk"]
    assert "ЄЖЕНОЮ" not in row["summary_uk"] and "Ry" not in row["summary_uk"].split()
    for locale in ("en", "uk"):
        activate_locale(locale)
        shown = present_finding(row)
        assert shown["summary_text"] == row["summary_uk"]
        assert shown["summary_original_language"] == ("uk" if locale == "en" else None)
        [explanation] = shown["explanations"]
        assert explanation["key"] == "colorectal_polyp"
        assert explanation["text"] == MESSAGES["finding.explain.colorectal_polyp"][locale]
        assert {source["region"] for source in explanation["sources"]} == {"US", "EU", "UA"}
        assert all(source["url"].startswith("https://") for source in explanation["sources"])
    activate_locale("en")


def test_left_and_right_studies_on_one_day_stay_two_findings(ledger):
    settings, owner, patient = ledger
    text = "МРТ ліктьового суглоба\nВисновок: МР-ознаки тендинопатії тріцепса.\nРЕКОМЕНДОВАНО:\nтравматолог"
    add_report(settings, owner, patient, "left", "radiology_mri", "МРТ лівого ліктьового суглоба", [text])
    add_report(settings, owner, patient, "right", "radiology_mri", "МРТ правого ліктьового суглоба", [text])
    assert sorted(row["title"] for row in findings(settings)) == ["Left elbow MRI", "Right elbow MRI"]


def test_a_reupload_of_the_same_study_with_a_different_layout_is_one_finding(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "first", "ultrasound", "abdominal-ultrasound", ABDOMINAL, imported="2026-01-01")
    relaid = ["\n".join(line for chunk in ABDOMINAL for line in chunk.replace("Гепатомегалії. ", "Гепатомегалії.\n").splitlines())]
    add_report(settings, owner, patient, "again", "ultrasound", "УЗД черевноі порожнини", relaid, report_date=None, imported="2026-11-05")
    rows = findings(settings)
    assert {row["document_id"] for row in rows} == {"first"}


def test_an_image_set_without_a_conclusion_is_filed_but_says_so(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "ct", "diagnostic_image", "ENT CT screening image set",
               ["Дата обстеження: 11.09.2025\nПІБ: Тестенко Т.І.\n[Embedded image region 1]\nSagittal 64mm"])
    [row] = findings(settings)
    assert (row["health_area"], row["summary_uk"], row["summary_en"], row["original_text"]) == ("ent", "", "", "")
    assert row["finding_date"] == "2025-09-11"


def test_printed_study_date_wins_and_a_birth_date_never_does():
    assert _extract_date("Дата народження: 14.03.1990\nДата дослідження: Лікаренко Олена\nЛікар:\n01.02.2025", None) == "2025-02-01"
    assert _extract_date("Дата візиту: 23/02/2025", "2026-08-07") == "2025-02-23"
    assert _extract_date("Дата народження: 14.03.1990", "2025-01-01") == "2025-01-01"
    assert _extract_date("Дата надходження 10.11.2025 Дата дослідження 12.11.2025", None) == "2025-11-12"


def test_negated_and_plain_vocabulary():
    assert finding_attention("Ознак кісти Бейкера не виявлено.") == []
    assert finding_attention("Без ознак гепатомегалії.") == []
    assert finding_attention("Колоїдні вузли правої частки ЩЗ") == ["thyroid_nodule"]
    assert finding_attention("Хрящові вузли Шморля.") == []
    assert finding_attention("Сонографічно ознаки стеатозу, ліпоматозу підшлункової залози.") == ["fatty_liver"]
    assert finding_attention("Спондилоартрит?") == ["spine_disc"]
    assert finding_attention("Плантарний фасциїт. Артрит.") == ["joint_tendon"]


def test_rerunning_the_sync_changes_nothing(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "abd", "ultrasound", "УЗД черевної порожнини", ABDOMINAL)
    first = findings(settings)
    assert findings(settings) == first


def test_every_explanation_is_bilingual_and_cites_existing_sources_in_two_regions():
    sources = _library_sources()
    for family, ids in FINDING_EXPLANATION_SOURCES.items():
        entry = MESSAGES[f"finding.explain.{family}"]
        assert entry["en"] and entry["uk"] and entry["en"] != entry["uk"]
        assert all(key in sources for key in ids), family
        assert len({sources[key]["region"] for key in ids}) >= 2, family


def test_spine_lists_only_results_read_with_the_spine():
    # CLIN-34: the whole autoimmune and minerals panels used to reach the spine.
    assert "spine" not in metric_area_ids("Sodium", "electrolytes")
    assert "spine" not in metric_area_ids("Potassium", "electrolytes")
    assert "spine" not in metric_area_ids("LKM1 antibodies", "autoimmune")
    assert "liver" in metric_area_ids("LKM1 antibodies", "autoimmune")
    assert "joints" in metric_area_ids("Antinuclear antibodies", "autoimmune")
    assert metric_area_ids("HLA-B27", "immunogenetics") == ["immunity", "joints", "spine"]
    assert "spine" in metric_area_ids("Calcium, total", "electrolytes")


def _card(index, interpretation="negative", value=0.05, text="<0.1"):
    return {
        "id": f"c{index}", "name": f"Allergen {index} Cyn d {index % 9 + 1}", "url": f"/metrics/c{index}",
        "value_numeric": value, "value_text": text, "unit": "kUA/L", "date_text": "31 Aug 2025",
        "verdict": {"interpretation": interpretation, "label": interpretation},
    }


def test_a_large_area_becomes_a_table_with_attention_first(ledger):
    settings, _, _ = ledger
    cards = [_card(index) for index in range(40)] + [_card(98, "negative", 0.11, "0.11"), _card(99, "positive", 0.5, "0.5")]
    with connect(settings) as connection:
        assert _area_table(connection, "allergy", cards[:30]) is None
        table = _area_table(connection, "allergy", cards)
    assert len(table["rows"]) == 42
    # Flagged first, then a value measured above the detection limit.
    assert [row["card"]["id"] for row in table["attention"]] == ["c99", "c98"]
    assert table["rows"][0]["card"]["id"] == "c99"
    assert table["rows"][0]["code"] == "Cyn d 1"


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_area_page_leads_with_the_conclusion_and_hides_the_letterhead(ledger, locale):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "abd", "ultrasound", "УЗД черевної порожнини", ABDOMINAL)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, owner)
    client.cookies.set("anamna_session", token)
    page = client.get(f"/areas/liver?lang={locale}")
    assert page.status_code == 200
    text = page.text
    assert "Дифузних змін печінки по типу гепатозу" in text
    assert MESSAGES["finding.explain.fatty_liver"][locale] in text
    assert MESSAGES["area.finding_recommended"][locale] in text
    assert "https://pmc.ncbi.nlm.nih.gov/articles/PMC10735173/" in text
    for leaked in ("www.test-clinic", "+38 097", "Тестенко", "01.03.1990"):
        assert leaked not in text
    # The conclusion comes before the panel grid and the full text is collapsed.
    assert text.index('id="area-findings"') < text.index('id="area-measurements"')
    assert "<details>\n          <summary>" + MESSAGES["area.finding_full_text"][locale] in text
    if locale == "en":
        assert MESSAGES["area.finding_original_uk"]["en"] in text
    assert "Date unknown" not in text and "Дата невідома" not in text


def test_library_json_stays_canonically_formatted():
    from anamna.reference import LIBRARY_PATH

    raw = LIBRARY_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    ids = [source["id"] for source in data["sources"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))


def test_an_english_source_is_translated_only_through_the_phrase_catalogue():
    row = {"summary_en": "Normal Sinus Rhythm", "summary_uk": "", "attention_reasons": ""}
    activate_locale("uk")
    shown = present_finding(row)
    assert (shown["summary_text"], shown["summary_original_language"]) == ("Нормальний синусовий ритм", None)
    shown = present_finding({**row, "summary_en": "An uncatalogued English conclusion"})
    assert shown["summary_original_language"] == "en"
    activate_locale("en")
    assert present_finding(row) == {"summary_text": "Normal Sinus Rhythm", "summary_original_language": None, "explanations": []}


def test_each_organ_of_an_abdominal_scan_is_judged_on_its_own_sentences(ledger):
    """A fatty liver does not put the kidneys of the same scan under attention;
    the kidneys' own sentence is what the kidney area shows."""
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "abd", "ultrasound", "УЗД черевної порожнини", ABDOMINAL)
    salts = [ABDOMINAL[0], ABDOMINAL[1].replace(
        "Холестазу в помірній\nкількості.", "Холестазу в помірній\nкількості. Сольові нашарування в нирках без порушення уродинаміки.")]
    add_report(settings, owner, patient, "abd2", "ultrasound", "УЗД черевної порожнини", salts, report_date="2025-08-21")
    rows = {(row["document_id"], row["health_area"]): row for row in findings(settings)}
    assert rows[("abd", "liver")]["status"] == "attention"
    assert rows[("abd", "kidneys")]["status"] == "information"
    assert rows[("abd", "kidneys")]["attention_reasons"] == ""
    assert rows[("abd2", "kidneys")]["summary_uk"] == "Сольові нашарування в нирках без порушення уродинаміки."
    assert "нирках" not in rows[("abd2", "liver")]["summary_uk"]


VISIT_NOTE_CONSULT = [
    LETTERHEAD + "Консультація лікаря-дерматолога\nДата візиту: 27.07.2025\nКлінічний діагноз:\n"
    "L82 \u2010 Себорейний кератоз \ufd3eкератома\ufd3f\nB07 \u2010 Вірусні бородавки\n"
    "ПРИЗНАЧЕНЕ ЛІКУВАННЯ ТА РЕКОМЕНДАЦІЇ:\nСпосіб Тривалість Потреба в к\u2010сті\nНазва препарату\n"
    "Обробка бетадином 2 р/д\nТел. 0931234567\nПовторний візит:\n"
    "Своїм підписом підтверджую:\n",
]


def test_a_visit_note_keeps_its_diagnoses_apart_and_its_plan(ledger):
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "derm", "consultation", "Консультація дерматолога", VISIT_NOTE_CONSULT)
    row = next(row for row in findings(settings) if row["document_id"] == "derm")
    assert row["summary_uk"] == "L82 - Себорейний кератоз (кератома); B07 - Вірусні бородавки"
    assert row["recommendations"] == "Обробка бетадином 2 р/д"
