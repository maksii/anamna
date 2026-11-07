"""Round-3 value-by-value review (2026-11-08): lab sync, copies, vendor split,
specimens per section, concept keys and the SILAB PAP reader.

Every line is synthetic, shaped like the evidence the reviewers quoted:
invented names, orders and numbers.  Nothing here identifies anyone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def filed(connection, raw_name, *, vendor="EskuLab", value_type="numeric", clinical_type="laboratory", **row):
    concept_id, _unit = ensure_concept(
        connection, raw_name, ensure_vendor(connection, vendor, None), value_type=value_type,
        clinical_type=clinical_type, **row,
    )
    return concept_id


def category(connection, concept_id):
    return connection.execute("SELECT category FROM concepts WHERE id=?", (concept_id,)).fetchone()[0]


# --- 2: an auto concept reused through its learned alias takes the current category --


def test_a_learned_alias_does_not_keep_a_category_the_inference_no_longer_gives(connection):
    # As an older reader filed it: a urine word in the title made it urinalysis.
    first = filed(connection, "Таурин", unit_raw="мкмоль/л", context="Аналіз сечі загальний")
    assert category(connection, first) == "urinalysis"
    # The re-read files the row before its specimen is known: the learned
    # alias is the path, and it must not keep the old category.
    again = filed(connection, "Таурин", unit_raw="мкмоль/л", context="Амінокислоти (скринінг в сироватці) · Сечовина")
    assert again == first and category(connection, first) != "urinalysis"
    # A defined concept keeps the catalogue's category whatever the title says.
    urea = filed(connection, "Сечовина", unit_raw="ммоль/л", context="Аналіз сечі загальний")
    assert category(connection, urea) == "renal"


# --- 3: a re-read that only renamed a row reports nothing vanished ------------------

from anamna.ingest import pipeline  # noqa: E402

from test_rescan import build, observation, rescanner  # noqa: E402,F401  (fixture)


def test_a_row_whose_printed_name_alone_changed_has_not_vanished(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    rescanner([observation("Феритин", 42.0), observation("LDL cholesterol", 4.42)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    # The same page, concept and value under another printed label.
    rescanner([observation("Ferritin", 42.0), observation("LDL cholesterol", 4.42)])
    result = pipeline.reingest_document(settings, user_id, "doc-1")
    assert (result["appeared"], result["vanished"]) == (0, 0)
    # A changed value still counts both ways.
    rescanner([observation("Феритин", 43.0), observation("LDL cholesterol", 4.42)])
    result = pipeline.reingest_document(settings, user_id, "doc-1")
    assert (result["appeared"], result["vanished"]) == (1, 1)


# --- 4: after the specimen split, an auto concept's unit follows its remaining rows --

from anamna.ingest.pipeline import repair_observation_semantics  # noqa: E402

from test_concepts_repair import _insert  # noqa: E402
from test_web_panels import build as build_record  # noqa: E402


def test_an_auto_concept_left_with_urine_rows_takes_their_unit(tmp_path: Path):
    settings, user_id, _ = build_record(tmp_path)
    with connect(settings) as connection:
        vendor_id = connection.execute("SELECT vendor_id FROM documents WHERE id='doc-1'").fetchone()[0]
        # The stool reading created the concept, then moved to «(кал)».
        concept_id, unit = ensure_concept(connection, "Lactobacillus spp.", vendor_id, unit_raw="КУО/г")
        assert unit == "КУО/г"
        _insert(connection, user_id, "urine-lacto", "Lactobacillus spp.", concept_id, value=1000.0,
                unit="КУО/мл", canonical="КУО/мл")
        connection.execute("UPDATE observations SET specimen='сеча' WHERE id='urine-lacto'")
        repair_observation_semantics(connection)
        row = connection.execute(
            "SELECT o.unit_canonical, c.preferred_unit FROM observations o JOIN concepts c ON c.id=o.concept_id "
            "WHERE o.id='urine-lacto'").fetchone()
        assert tuple(row) == ("КУО/мл", "КУО/мл")
        repair_observation_semantics(connection)  # idempotent
        assert connection.execute("SELECT preferred_unit FROM concepts WHERE id=?",
                                  (concept_id,)).fetchone()[0] == "КУО/мл"


# --- 5: apostrophe look-alikes and Cyrillic Roman numerals are one key -------------

from anamna.ingest.text import normalized_key  # noqa: E402
from anamna.labsync.common import name_key  # noqa: E402


def test_apostrophes_and_cyrillic_roman_numerals_fold_to_one_key():
    spellings = ["Зміни, не пов'язані з процесом", 'Зміни, не пов"язані з процесом',
                 "Зміни, не пов’язані з процесом", "Зміни, не повʼязані з процесом"]
    assert len({normalized_key(text) for text in spellings}) == 1
    assert len({name_key(text) for text in spellings}) == 1
    assert normalized_key("NILM, (тип II, запальний)") == normalized_key("NILM, (тип ІІ, запальний)")
    assert normalized_key("ступінь ІV") == normalized_key("ступінь IV")
    assert normalized_key("кров і сеча") == "кров і сеча"  # the conjunction is a word, not a numeral


def test_one_label_spelled_two_ways_by_two_vendors_is_one_concept(connection):
    first = filed(connection, 'Зміни, не пов"язані з процесом', vendor="Synevo", value_type="text",
                  clinical_type="microbiology")
    # As round 3 found it: the other spelling already had a concept of its own.
    connection.execute(
        "INSERT INTO concepts(id, canonical_name, category, value_type, created_at) "
        "VALUES ('split-twin', ?, 'microbiology', 'text', '2999-01-01T00:00:00Z')",
        ("Зміни, не пов'язані з процесом",))
    connection.execute(
        "INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias) VALUES ('split-twin', ?, ?, ?)",
        (ensure_vendor(connection, "MD Clinics", None), "Зміни, не пов'язані з процесом",
         normalized_key("Зміни, не пов'язані з процесом")))
    again = filed(connection, "Зміни, не пов'язані з процесом", vendor="MD Clinics", value_type="text",
                  clinical_type="microbiology")
    assert again == first


# --- 6: one print of one order that lost rows to OCR is a duplicate ---------------

from test_document_duplicates import add_copy  # noqa: E402


def _relations(settings, user_id, doc_id):
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, doc_id)
        connection.commit()
        return {(row[0], row[1], row[2]) for row in connection.execute(
            "SELECT source_document_id, target_document_id, relationship FROM document_relations "
            "WHERE notes LIKE 'auto:shared_results:%'")}


def test_a_copy_with_the_same_order_and_result_times_and_equal_values_is_a_duplicate(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_copy(settings, "half-scan")
    with connect(settings) as connection:
        kept = connection.execute("SELECT COUNT(*) FROM observations WHERE document_id='doc-1'").fetchone()[0]
        assert kept >= 2
        # The half-size scan lost one row to OCR and its order number.
        connection.execute("DELETE FROM observations WHERE id=(SELECT id FROM observations "
                           "WHERE document_id='half-scan' ORDER BY rowid LIMIT 1)")
        connection.execute("UPDATE documents SET collected_at='2026-03-02T09:15', issued_at='2026-03-04T14:36'")
        connection.execute("UPDATE documents SET order_identifier='7700001234' WHERE id='doc-1'")
        connection.commit()
    assert _relations(settings, user_id, "half-scan") == {("half-scan", "doc-1", "duplicate")}
    # Another result time is another print of the order: a part of it.
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET issued_at='2026-03-05T10:00' WHERE id='half-scan'")
        connection.commit()
    assert _relations(settings, user_id, "half-scan") == {("doc-1", "half-scan", "contains")}
    # So is another order number.
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET issued_at='2026-03-04T14:36', order_identifier='7700009999' "
                           "WHERE id='half-scan'")
        connection.commit()
    assert _relations(settings, user_id, "half-scan") == {("doc-1", "half-scan", "contains")}


# --- 7: re-reading a stored lab record moves the concept and restores a reference ---

import re  # noqa: E402

from anamna import labsync  # noqa: E402


def test_a_refreshed_lab_record_row_takes_its_concept_and_reference_at_once(tmp_path: Path, monkeypatch):
    from test_labsync_nofile import NOFILE, connected, stub_intake, sync

    analysis = {**NOFILE, "name": "ПЛР. ВПЛ ВКР (генотипування 16, 18, кількісне визначення)"}
    indicators = [
        {"id": 1, "name": "16 генотип", "value": "не виявлено", "unit": None,
         "reference_text": "<3 LgВПЛ/10^5 клітин: клінічно малозначуще", "is_abnormal": False},
        {"id": 2, "name": "Відсоток рангу препарату", "value": "61", "unit": "%",
         "reference_text": "(система визначає ранг препарату у відсотках до набору слайдів)", "is_abnormal": False},
    ]
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    # What the reader filed before: the bare genotype name, every reference line taken for a method note.
    monkeypatch.setattr(labsync, "_BARE_NAME_RE", re.compile(r"(?!x)x"))
    monkeypatch.setattr(labsync, "_method_note", lambda line: True)
    sync(settings, user_id, monkeypatch, analysis, indicators)
    monkeypatch.undo()
    with connect(settings) as connection:
        before = {row["raw_name"]: dict(row) for row in connection.execute("SELECT * FROM observations")}
    assert "16 генотип" in before and before["Відсоток рангу препарату"]["vendor_reference_text"] is None
    labsync.recheck(settings)
    with connect(settings) as connection:
        after = {row["raw_name"]: dict(row) for row in connection.execute("SELECT * FROM observations")}
        genotype = after["ПЛР. ВПЛ ВКР, 16 генотип"]
        name = connection.execute("SELECT canonical_name FROM concepts WHERE id=?",
                                  (genotype["concept_id"],)).fetchone()[0]
    assert genotype["concept_id"] != before["16 генотип"]["concept_id"] and name == "ПЛР. ВПЛ ВКР, 16 генотип"
    assert after["Відсоток рангу препарату"]["vendor_reference_text"] == indicators[1]["reference_text"]
    assert labsync.recheck(settings)["record_values"] == 0  # idempotent


# --- 8: a clinic's logo on some pages of a laboratory print splits nothing ---------

from anamna.ingest.classifier import classify_document  # noqa: E402
from anamna.ingest.pipeline import classify_pages  # noqa: E402

LOGO = "Медичний центр КИЇВ / ЖИТОМИР\nТОВ «НЕОМЕД 2007» Мати та дитина\ne-mail: info@mdclinics.com.ua\n"
HEADER = "Результати досліджень\nДата замовлення: 03.02.2025 10:30\nДата результату: 04.02.2025 18:05\n"
REFERENCE = "<3 LgВПЛ/10^5 клітин: клінічно малозначуще"


def text_page(number, native, ocr=""):
    return {"page_number": number, "native_text": native, "ocr_text": ocr, "extraction_method": "native_pdf_text",
            "native_char_count": len(native), "image_count": 1 if ocr else 0}


def test_pages_of_one_order_under_a_clinic_logo_stay_one_laboratory_report():
    first = text_page(1, HEADER + "Показник Результат Од. Референтний інтервал\nПЛР Київ Індикатор зони підвищеної уваги\n"
                      "ПЛР. ВПЛ ВКР (генотипування 16, 18, 45, 51)\n16 генотип не виявлено " + REFERENCE + "\n"
                      "18 генотип не виявлено " + REFERENCE + "\n", LOGO)
    rest = [text_page(number, HEADER + f"{genotype} генотип не виявлено {REFERENCE}\nСтор. {number} з 3\n", LOGO)
            for number, genotype in ((2, 45), (3, 51))]
    pages = [first, *rest]
    # Page by page, the logo names the clinic: the split the fix must not make.
    assert classify_document("print.pdf", "application/pdf", [rest[0]], {}).vendor == "MD Clinics"
    document, per_page = classify_pages("print.pdf", "application/pdf", pages, {})
    assert document.clinical_type == "laboratory" and document.vendor == "Synevo"
    assert document.report_date == "2025-02-03"
    assert {(page.vendor, page.report_date, page.issued_at) for page in per_page} == {
        ("Synevo", "2025-02-03", "2025-02-04T18:05")}


def test_a_page_that_prints_no_order_or_date_is_not_another_report():
    order = "№ замовл.: 7700001111\n"
    footer = "Обробка матеріалу та видача результатів аналізів виконується за допомогою лабораторної інформаційної системи SILAB.\n"
    pages = [
        text_page(1, "", LOGO + "Результати досліджень\nДата замовлення 11/08/2021 14:18 " + order
                  + "Аналіз сечі загальний\nКолір жовтий від світло-жовтого до жовтого\n"),
        text_page(2, "", LOGO + order + "Слиз не виявлений не виявлений\n" + footer),
        text_page(3, "", LOGO + "Дата замовлення 11/08/2021 14:18 " + order
                  + "Кристали білірубіну не виявлені не виявлені\n" + footer),
    ]
    document, per_page = classify_pages("file.pdf", "application/pdf", pages, {})
    assert document.clinical_type != "compound_bundle" and document.vendor != "Multiple vendors"
    assert len({page.vendor for page in per_page}) == 1
    assert {page.report_date for page in per_page} == {"2021-08-11"}  # page 2 is dated with the others


def test_two_orders_in_one_file_are_still_two_reports():
    pages = [text_page(1, HEADER.replace("03.02.2025", "01.02.2025") + "Показник Результат Од. Референтний інтервал\n"
                       "Індикатор зони підвищеної уваги\nГлюкоза 5.1 ммоль/л 3.9 - 5.8\n"),
             text_page(2, "", LOGO + HEADER + "Показник Результат Од. Референтний інтервал\nГлюкоза 5.4 ммоль/л 3.9 - 5.8\n")]
    document, _per_page = classify_pages("file.pdf", "application/pdf", pages, {})
    assert document.clinical_type == "compound_bundle"


def test_an_undated_consultation_behind_a_lab_order_is_not_folded_into_it():
    pages = [text_page(1, HEADER + "Показник Результат Од. Референтний інтервал\nІндикатор зони підвищеної уваги\n"
                       "Глюкоза 5.1 ммоль/л 3.9 - 5.8\n"),
             text_page(2, "", LOGO + "Консультація лікаря-гінеколога\nСкарги: немає\nРекомендовано: контроль\n")]
    document, per_page = classify_pages("file.pdf", "application/pdf", pages, {})
    assert [page.vendor for page in per_page] == ["Synevo", "MD Clinics"]
    assert document.clinical_type == "compound_bundle"


# --- 9: a page with a blood count and a urinalysis: specimen per section heading ----

from anamna.ingest.classifier import extract_specimen  # noqa: E402
from anamna.ingest.pipeline import observation_specimen, parse_pages  # noqa: E402

BLOOD_AND_URINE = """Результати досліджень Сінево (Synevo)
Дата замовлення: 14.03.2019 08:40
Показник Результат Од. Референтний інтервал
Аналіз крові розгорнутий (ЗАК)
Середній об'єм тромбоцитів (MPV) 10.4 фл 6.0 - 13.0
Тромбокрит (РСТ) 0.21 % 0.1 - 0.5
Аналіз крові: Лейкоцитарна формула
(ручний підрахунок)
Паличкоядерні нейтрофіли 3 %
Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)
Аналіз сечі загальний
Доставлена кількість, мл 30 мл
Відносна щільність 1.015 1.010 - 1.020
Стор. 2 з 3
"""


def test_a_title_naming_two_specimens_gives_the_page_none():
    assert extract_specimen("Аналіз крові розгорнутий (ЗАК) · Аналіз сечі загальний (ЗАС)") is None
    assert extract_specimen("Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)") == "сеча"


def test_rows_take_the_specimen_of_the_section_they_are_printed_under():
    pages = [text_page(1, BLOOD_AND_URINE)]
    document, per_page = classify_pages("x.pdf", "application/pdf", pages, {})
    assert " · " in per_page[0].title and per_page[0].specimen is None
    found = {parsed.raw_name: observation_specimen(parsed, page.specimen)
             for parsed, page in parse_pages(document, per_page, pages)}
    assert found["Середній об'єм тромбоцитів (MPV)"] is None and found["Паличкоядерні нейтрофіли"] is None
    assert found["Відносна щільність"] == "сеча" and found["Доставлена кількість, мл"] == "сеча"


# --- 10: the SILAB PAP section's percentile and Bethesda conclusion ---------------

from anamna.ingest.parsers import parse_silab_page  # noqa: E402

PAP_PAGE = """ПАП-тест методом рідинної цитології
Квінтильний ранг препарату за 3 Автоматизована система BD FocalPoint GS
технологією ВО FocalPoint використовує алгоритми відповідного
Відсоток квінтильного рангу за 52 % Автоматизована система BD FocalPoint GS
технологією BD FocalPoint використовує алгоритми для визначення
співвідношенні до квінтильного рангового
Лабораторний висновок ПАП-тесту за NILM (тип II, запальний тип мазка) /Negative for intraepithelial Lesion or Malignancy
класифікацією ВЕТНЕЗОА 2014 (негативні відносно iHmpaenimenianbHux уражень і злоякісності)
"""


def test_the_pap_percentile_and_the_bethesda_conclusion_are_read():
    rows = {row.raw_name: row for row in parse_silab_page(PAP_PAGE, 1)}
    percent = rows["Відсоток квінтильного рангу за технологією BD FocalPoint"]
    assert (percent.value_numeric, percent.unit_raw) == (52.0, "%")
    bethesda = rows["Лабораторний висновок ПАП-тесту за класифікацією BETHESDA 2014"]
    assert bethesda.value_text == ("NILM (тип II, запальний тип мазка) /Negative for Intraepithelial Lesion or "
                                   "Malignancy (негативні відносно інтраепітеліальних уражень і злоякісності)")


def test_a_percentile_outside_its_rank_or_a_spoiled_result_is_left_out():
    spoiled = PAP_PAGE.replace("за 52 %", "за 5 %").replace("NILM (тип II", "МИМ (тип Il")
    names = {row.raw_name for row in parse_silab_page(spoiled, 1)}
    assert "Відсоток квінтильного рангу за технологією BD FocalPoint" not in names
    assert "Лабораторний висновок ПАП-тесту за класифікацією BETHESDA 2014" not in names
    assert "Квінтильний ранг препарату за технологією BD FocalPoint" in names


# --- 11: the cytology passport is titled, typed and carries its barcode -----------

PASSPORT = (LOGO + "ui итологічний паспо ee\nТестова Пацієнтка Іванівна WK 7700002222\n"
            "Дата народження: 01.01.1990 Дата замовлення: 02.03.2026\n"
            "Аналіз проводиться із застосуванням системи візуалізації BD FocalPoint GS Imaging System.\n"
            "Автоматизовані індивідуальні цифрові зображення створені та оброблені системою BD FocalPoint.\n")


def test_the_cytology_passport_is_named_typed_and_numbered():
    found = classify_document("file.pdf", "application/pdf", [text_page(1, "", PASSPORT)], {})
    assert (found.title, found.clinical_type, found.order_identifier) == ("Цитологічний паспорт", "pathology", "7700002222")
    # The results print names the passport in its panel title and stays a laboratory report.
    results = text_page(1, HEADER + "ПАП-тест методом рідинної цитології (технологія BD SurePath). ЦИТОЛОГІЧНИЙ "
                        "ПАСПОРТ (технологія BD FocalPoint)\nПоказник Результат Од. Референтний інтервал\n"
                        "Обробка матеріалу та видача результатів аналізів виконується за допомогою лабораторної "
                        "інформаційної системи SILAB.\n", LOGO)
    assert classify_document("file.pdf", "application/pdf", [results], {}).clinical_type == "laboratory"
