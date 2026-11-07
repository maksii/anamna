"""Document metadata the 2026-11-07 value-by-value review found wrong.

Titles that were a file name, a lab department or one panel of several; dates
and order numbers left empty; one laboratory order filed as a bundle of
unrelated reports; a POLYCHECK allergen chip with no vendor.  Every text below
is synthetic -- invented patient, invented numbers -- in the line shapes of the
real pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from anamna.ingest.classifier import classify_document, extract_title
from anamna.ingest.pipeline import classify_pages


def page(text: str, number: int = 1, ocr: str = "") -> dict[str, object]:
    return {"page_number": number, "native_text": text, "ocr_text": ocr, "native_char_count": len(text),
            "image_count": 0}


ESKULAB_HEAD = (
    "Замовлення: 10000001 / 12.04.2025 11:24 Дата видачі: 12.04.2025 15:53\n"
    "Здоров’я планується вчасно\n"
    "Пацієнт: Тестова Ольга Іванівна ДН: 01.01.1990 Стать: Жін.\n"
    "Результати дослідження №10000001\n"
    "Показник Результат Одиниці Референтні значення\n"
)


# -- titles -----------------------------------------------------------------


def test_an_order_of_uncoded_tests_is_titled_by_its_tests_not_its_file_name():
    text = ESKULAB_HEAD + (
        "1. Онкомаркер яєчників 31.4 Од/мл Референтне значення < 35\n"
        "(СА-125)\n"
        "сироватка крові\n"
        "2. Ранній онкомаркер раку яєчників 48.4 пмоль/л\n"
        "до 40 р.: <60,5 60-69 р.: <82,9\n"
        "3. Антимюллерів гормон Advanced 2.68 нг/мл\n"
        "Діти (ж) ≤ 60 д.: 0.01 - Діти (ч) ≤ 60 д.: 15.11 -\n"
        "(АМГ, AMH Advanced) сироватка крові 3.39 266.59\n"
    )
    title = extract_title(text, "eskulab-10000001.pdf", "laboratory")
    assert title == "Онкомаркер яєчників (СА-125) · Ранній онкомаркер раку яєчників · Антимюллерів гормон Advanced"


def test_a_test_name_ends_where_its_result_starts_and_keeps_its_bracket():
    text = ESKULAB_HEAD + (
        "1. Хелікобактер пілорі, кал не виявлено - не виявлено\n"
        "Приносний\n"
        "2. Скринінг на сифіліс (реакція від`ємна - від`ємна\n"
        "мікропреципітації)\n"
        "3. 25-Гідроксивітамін D (Вітамін D 35.3 нг/мл\n"
        "Ризик дефіциту: < 10.0 Дорослі: 30.0-50.0\n"
        "4. Антитіла IgG до тканинної 0.8 Од/мл негативний: <7.0\n"
        "трансглютамінази (t-TG), ELiA сумнівний: 7.0-10.0\n"
        "5. Глюкоза (плазма крові) 5.95 ммоль/л\n"
        "плазма крові новонароджені (1 день): Маніфестний цукровий\n"
        "6. Кальпротектин <24.0 мг/кг негативний: < 50\n"
    )
    assert extract_title(text, "eskulab-10000001.pdf", "laboratory").split(" · ") == [
        "Хелікобактер пілорі, кал",
        "Скринінг на сифіліс (реакція мікропреципітації)",
        "25-Гідроксивітамін D",
        "Антитіла IgG до тканинної трансглютамінази (t-TG)",
        "Глюкоза (плазма крові)",
        "Кальпротектин",
    ]


def test_every_panel_is_named_and_no_title_ends_in_a_dangling_separator():
    text = ESKULAB_HEAD + (
        "1. С-пептид 1.47 нг/мл 0,9-7,1\n"
        "3. L0610 Пакет №375. D3+B9+B12\n"
        "1. F4001 Загальний аналіз крові (ЗАК автоматизований + ручна лейкоформула)\n"
        "2. F4003 Загальний аналіз крові з ручним підрахунком лейкоцитарної формули та\n"
        "ретикулоцитів\n"
    )
    title = extract_title(text, "eskulab-10000001.pdf", "laboratory")
    assert title == (
        "D3+B9+B12 · Загальний аналіз крові (ЗАК автоматизований + ручна лейкоформула) · "
        "Загальний аналіз крові з ручним підрахунком лейкоцитарної формули та ретикулоцитів · С-пептид"
    )


def test_a_title_cut_for_length_says_so_instead_of_ending_in_a_bullet():
    names = "Альфа Бета Гамма Дельта Епсилон Дзета Ета Тета Йота Каппа Лямбда Мю".split()
    tests = "".join(f"{n}. Тестовий показник {name} довгої назви {n}.5 ммоль/л\n" for n, name in enumerate(names, 1))
    title = extract_title(ESKULAB_HEAD + tests, "eskulab-10000001.pdf", "laboratory")
    assert title.endswith(" · ...") and len(title) <= 240
    assert not title.endswith(" ·")


def test_a_packet_whose_result_is_not_on_the_paper_does_not_name_the_document():
    text = ESKULAB_HEAD + (
        "1. K0000 ВІЛ експрес-тест (якісне визначення) з підтвердженням\n"
        "Дослідження: ВІЛ-тест (якісне визначення)\n"
        "Даний результат можна отримати лише на пункті забору за адресою: м. Тестове, вул. Тестова, 1\n"
        "1. F4001 Загальний аналіз крові (ЗАК автоматизований + ручна лейкоформула)\n"
        "1. Феритин 64.9 нг/мл\n"
    )
    assert extract_title(text, "eskulab-10000001.pdf", "laboratory") == (
        "Загальний аналіз крові (ЗАК автоматизований + ручна лейкоформула) · Феритин"
    )


def test_the_older_eskulab_form_names_its_test():
    text = "Показники Результат Од. виміру Реф. значення\n30511 Копрограма\nФорма оформлений\n"
    assert extract_title(text, "eskulab-10000001.pdf", "laboratory") == "Копрограма"


SYNEVO_HEAD = (
    "Результати досліджень Сінево (Synevo)\nЛабораторія Тестове\n"
    "Дата замовлення: 04.08.2023 08:20 Оформлено: у відділенні\n"
    "Клієнт: Тестова Ольга Іванівна (AbCdEf)\n"
    "Дата народження: 01.01.1990 Вік: 33 Y 7 M Стать: Жіноча 3600000001\n"
    "Показник Результат Од. Референтний інтервал\n"
)


def test_a_synevo_department_gives_way_to_the_tests_printed_under_it():
    text = SYNEVO_HEAD + (
        "Загальна клініка Індикатор зони підвищеної уваги\n"
        "Аналіз калу на кишкові паразити (метод\n"
        "концентрування Parasep)\n"
        "Яйця гельмінтів не виявлені не виявлені\n"
        "\f\n" + SYNEVO_HEAD.split("Показник")[0] + "Показник Результат Од. Референтний інтервал\n"
        "Копрограма\n"
        "Кристали не виявлені не виявлені\n"
    )
    assert extract_title(text, "synevo-3600000001.pdf", "laboratory") == (
        "Аналіз калу на кишкові паразити (метод концентрування Parasep) · Копрограма"
    )
    # A section that names its tests stays, and later pages add nothing to it.
    biochemistry = SYNEVO_HEAD + "Біохімія Індикатор зони підвищеної уваги\nХолестерин 6.27 ммоль/л <5.2\n"
    assert extract_title(biochemistry, "synevo-3600000001.pdf", "laboratory") == "Біохімія"
    urine = SYNEVO_HEAD + (
        "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду) Індикатор зони підвищеної уваги\n"
        "Колір жовтий жовтий\n" + SYNEVO_HEAD.split("Дата замовлення")[0] + "Показник Результат Од. Референтний інтервал\n"
        "Ручна мікроскопія осаду сечі\n"
    )
    assert extract_title(urine, "synevo-3600000001.pdf", "laboratory") == (
        "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"
    )


def test_a_synevo_packet_heading_cut_by_a_line_wrap_is_joined():
    text = SYNEVO_HEAD + (
        "Пакет №183 (CHECK-UP. Все під контролем для жінок + звіт з описом Індикатор зони підвищеної уваги\n"
        "лабораторних показників)\n"
        "Аналіз крові: Швидкість осідання 4 мм/год. Нормативні значення\n"
    )
    assert extract_title(text, "synevo-3600000001.pdf", "laboratory") == (
        "Пакет №183 (CHECK-UP. Все під контролем для жінок + звіт з описом лабораторних показників)"
    )


COMPANION_COVER = "Пакет № 183\nCHECK-UP: Все під\nконтролем для жінок\nТестова Ольга\n12.05.2023\n"
COMPANION_FOOTER = "Ольга Іванівна Тестова / Пакет № 183 (Все під контролем для жінок) / 13.05.2023 / cтор. 2\n"
COMPANION_DETAILS = (
    "Штрих-код 3600000002-1641\nДата народження 01.01.1990\n"
    "Дата замовлення 12.05.2023\nДата видруку 13.05.2023 cкринінговий\n"
)


def test_the_synevo_companion_report_keeps_its_packet_name_dates_and_barcode():
    pages = [page(COMPANION_COVER, 1), page("Гемоглобін\n" + COMPANION_FOOTER, 2),
             page(COMPANION_DETAILS + COMPANION_FOOTER, 3)]
    result = classify_document("synevo-3600000002-1.pdf", "application/pdf", pages)
    assert result.title == "Пакет № 183 (Все під контролем для жінок)"
    assert (result.report_date, result.collected_at, result.issued_at) == ("2023-05-12", "2023-05-12", "2023-05-13")
    assert result.order_identifier == "3600000002"


def test_a_clinic_study_titled_as_a_visit_takes_the_heading_it_prints():
    text = "Консультація лікаря\nВисновок ЕЕГ\nДата візиту: 17.11.2025\nПацієнт: Тестова Ольга\n"
    assert extract_title(text, "veselka-1000001 2025-11-17 Огляд лікаря.pdf", "consultation") == "Висновок ЕЕГ"
    visit = "Медичний центр\nДата візиту: 17.11.2025\nВисновок: здорова\n"
    assert extract_title(visit, "veselka-1000002 2025-11-17 Огляд лікаря.pdf", "consultation") == "Огляд лікаря"


# -- dates and order numbers --------------------------------------------------


def test_expert_hospital_dates_a_report_by_the_second_date_on_the_patient_line():
    text = (
        "ТзОВ «Лікарня ЕКСПЕРТ»\nexperthospital.com.ua\nЛіцензія МОЗ України\n№ 1234 від 01.01.2020\n"
        "\"Загальний аналіз крові (аналізатор) + ШОЕ\"\n"
        "Пацієнт: Тестова Ольга Іванівна, 01.01.1990 01.01.2024\n"
        "ПОКАЗНИК РЕЗУЛЬТАТ РЕФЕРЕНТНІ ЗНАЧЕННЯ\nЛейкоцити (WBC), х 10*9/л 6,05 від 4 до 9\n"
    )
    result = classify_document("ekspert-100001.pdf", "application/pdf", [page(text)])
    assert result.report_date == "2024-01-01"
    # Not printed: lab sync named the file by the lab's own order number.
    assert result.order_identifier == "100001"
    assert classify_document("upload.pdf", "application/pdf", [page(text)]).order_identifier is None


def test_one_eskulab_order_of_a_culture_and_a_urinalysis_is_one_laboratory_report():
    head = "Замовлення: 10000003 / 18.05.2026 11:42 Дата виконання: 21.05.2026 12:00\nРезультати дослідження №10000003\n"
    culture = head + (
        "1. J0008 Мікробіологічне дослідження сечі із визначенням чутливості виділених\n"
        "мікроорганізмів до антибіотиків (антибіотикограма)\n"
        "Мікроорганізм Результат Референтні значення\nЧас відбору: 10:15\n"
    )
    urine = head + "1. F6001 Загальний аналіз сечі автоматизований (ЗАС автоматизований)\nПоказник Результат Одиниці\n"
    classification, per_page = classify_pages(
        "eskulab-10000003.pdf", "application/pdf", [page(culture, 1), page(urine, 2)], {})
    assert [item.clinical_type for item in per_page] == ["microbiology", "laboratory"]
    assert classification.clinical_type == "laboratory"
    assert (classification.report_date, classification.order_identifier) == ("2026-05-18", "10000003")
    assert (classification.collected_at, classification.issued_at) == ("2026-05-18T10:15", "2026-05-21T12:00")
    assert classification.title == (
        "Мікробіологічне дослідження сечі із визначенням чутливості виділених мікроорганізмів до антибіотиків "
        "(антибіотикограма) · Загальний аналіз сечі автоматизований (ЗАС автоматизований)"
    )
    # Two orders in one file are still a bundle.
    other = urine.replace("10000003", "10000004")
    bundle, _ = classify_pages("scan.pdf", "application/pdf", [page(culture, 1), page(other, 2)], {})
    assert bundle.clinical_type == "compound_bundle"


# -- vendor and type ----------------------------------------------------------


POLYCHECK_TEXT = (
    "Тестова Харчовa 20-I\nОльга Іванівна /\n01.01.1990 18.11.2024\n18.11.2024 (V. 6.01.21 )\n"
    "Скануй 18.11.2024, cass. # 9 (V6.01.21) C:\\ProgramData\\Biocheck\\tmp\\Chip09.bmp\n"
    "f13 Арахіс 0 0 .26\nf02 Молоко 0 <0.15\n"
    "0 <0.35 Антитіла відсутні 4 17.5 - <50 Висока концентрація антитіл\n"
)


def test_a_polycheck_chip_from_eskulab_is_a_dated_allergy_report():
    pages = [page(POLYCHECK_TEXT, ocr="[Embedded image region 1]\nPOLYCHECK®\nwww.polycheck.de\n")]
    result = classify_document("eskulab-10000005.pdf", "application/pdf", pages)
    assert (result.vendor, result.clinical_type, result.status) == ("EskuLab", "allergy", "final")
    assert (result.report_date, result.order_identifier) == ("2024-11-18", "10000005")
    # The panel as printed, its Latin «a» read as the Cyrillic letter it stands for.
    assert result.title == "POLYCHECK - Харчова 20-I"


# -- lab records (no PDF) -------------------------------------------------------


def test_a_lab_record_is_titled_by_every_packet_it_holds():
    from anamna.labsync import _record_title

    row = {"test": "Колір", "result": "жовтий", "resulttype": "text", "units": "", "norm": [], "state": "normal"}
    rows = [
        {**row, "packet": "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"},
        {**row, "packet": "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"},
        {**row, "test": "Гемоглобін (HGB)", "result": "134", "packet": '"Загальний аналіз крові"'},
    ]
    assert _record_title(rows) == "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду) · Загальний аналіз крові"
    assert _record_title([{**row, "packet": ""}]) == "Колір"


def test_recheck_gives_a_stored_lab_record_the_title_read_today(tmp_path: Path, monkeypatch):
    from anamna import labsync
    from anamna.db import connect

    from test_labsync_nofile import NOFILE, connected, state, stub_intake, sync

    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    sync(settings, user_id, monkeypatch, NOFILE)
    [record] = state(settings)["documents"]
    with connect(settings) as connection:
        expected = connection.execute("SELECT title FROM documents WHERE id=?", (record["id"],)).fetchone()[0]
        connection.execute("UPDATE documents SET title='old' WHERE id=?", (record["id"],))
        connection.execute("UPDATE reports SET title='old' WHERE document_id=?", (record["id"],))
        connection.commit()
    assert json.loads(Path(record["source_path"]).read_text(encoding="utf-8"))["rows"]
    assert labsync.recheck(settings)["titles"] == 1
    assert labsync.recheck(settings)["titles"] == 0
    with connect(settings) as connection:
        titles = {row[0] for row in connection.execute(
            "SELECT title FROM documents WHERE id=? UNION SELECT title FROM reports WHERE document_id=?",
            (record["id"], record["id"]))}
    assert titles == {expected}
