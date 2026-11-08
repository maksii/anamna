"""Round-4 review (2026-11-08): the effective dose on an X-ray report, the
SILAB print's HPV rows under the lab record's name, and the pages of one
order read as one report.

Every line is synthetic, shaped like the evidence the reviewers quoted:
invented names, orders and numbers.  Nothing here identifies anyone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale
from anamna.health import display_unit
from anamna.ingest import pipeline
from anamna.ingest.concepts import concept_for_alias, stable_concept_id
from anamna.ingest.parsers import ParsedObservation, parse_document, parse_effective_dose, parse_silab_page
from anamna.ingest.pipeline import classify_pages, ensure_concept, ensure_vendor, parse_pages
from anamna.labsync import _record_name
from anamna.reference import canonical_unit

from test_rescan import build, rescanner  # noqa: F401  (fixture)


def text_page(number, native, ocr=""):
    return {"page_number": number, "native_text": native, "ocr_text": ocr, "extraction_method": "native_pdf_text",
            "native_char_count": len(native), "image_count": 0}


# --- 1: the effective dose under an X-ray conclusion -------------------------------

XRAY = """ТзОВ «Лікарня Приклад»
РЕЗУЛЬТАТИ
Комп'ютерна рентгенографія досліджень № 101
від 02.03.2024
Частина тіла Грудна клітина
Область Рентгенографія ОГК (одна проекція)
Результат:
На рентгенограмі ОГК в прямій проекції легеневі поля прозорі. Синуси вільні.
Рекомендовано: консультація терапевта.
{dose}
П.І.Б лікаря діагноста Іваненко Олена Петрівна
Рентгенологічний висновок не є остаточним (клінічним) діагнозом
"""


@pytest.mark.parametrize(("line", "value"), [
    ("ЕД = 0.02 мЗв", 0.02),
    ("ЕД - 0.02 мЗв", 0.02),
    ("ЕД- 0.06 мЗв", 0.06),
    ("ЕЕД = 0,05 мЗв", 0.05),
    ("Ефективна доза: 0.1 мЗв", 0.1),
    ("| ЕД=1,2мЗв", 1.2),
])
def test_an_xray_report_gives_its_effective_dose(line, value):
    rows = parse_document("Expert Hospital", "radiology_xray", [text_page(1, XRAY.format(dose=line))])
    assert [(row.raw_name, row.value_numeric, row.unit_raw) for row in rows] == [
        ("Effective radiation dose", value, "мЗв")]
    assert rows[0].evidence_text == line.strip("| ")


def test_the_dose_files_under_one_defined_concept_in_its_own_unit():
    definition = concept_for_alias("Effective radiation dose", "numeric")
    assert definition and definition["category"] == "radiation_exposure"
    assert canonical_unit("мЗв") == canonical_unit(str(definition["unit"])) == canonical_unit("mSv")
    for locale, unit, shown in (("uk", "mSv", "мЗв"), ("en", "мЗв", "mSv")):
        token = activate_locale(locale)
        try:
            assert display_unit(unit) == shown
        finally:
            reset_locale(token)


def test_ocr_that_lost_the_decimal_point_is_reported_not_stored():
    issues = []
    pages = [text_page(1, "", XRAY.format(dose="| ЕД-006мЗв"))]
    assert parse_document("Expert Hospital", "radiology_xray", pages, issues=issues) == []
    assert [(issue.kind, issue.raw_name, issue.evidence_text) for issue in issues] == [
        ("unparsed_known_analyte", "ЕД", "ЕД-006мЗв")]


def test_a_dose_is_read_once_per_page_and_not_inside_another_word():
    page = text_page(1, XRAY.format(dose="ЕД = 0.02 мЗв"), XRAY.format(dose="ЕД = 0.02 мЗв"))
    assert len(parse_effective_dose([page])) == 1
    assert parse_effective_dose([text_page(1, "ПЕД 5 мЗв\nМЕДИЧНИЙ ЦЕНТР 3 мЗв\nЕДТА 2 мЗв\n")]) == []


def test_the_dose_is_not_read_from_a_laboratory_report():
    page = text_page(1, "Показник Результат Од. Референтний інтервал\nЕД = 0.02 мЗв\n")
    assert all(row.raw_name != "Effective radiation dose" for row in parse_document("Synevo", "laboratory", [page]))


def test_the_dose_has_reference_information_from_every_region_and_no_invented_target():
    library = json.loads((Path(__file__).parents[2] / "data" / "reference_library.json").read_text(encoding="utf-8"))
    entry = next(item for item in library["analytes"] if item["concept_id"] == stable_concept_id("Effective radiation dose"))
    sources = {source["id"]: source for source in library["sources"]}
    assert entry["kind"] == "no_universal_target" and entry["bands"] == []
    assert {sources[source_id]["region"] for source_id in entry["source_ids"]} == {"US", "EU", "INT", "UA"}
    assert all(sources[source_id]["url"].startswith("https://") for source_id in entry["source_ids"])
    for text in (entry["short_description"], entry["uk"]["short_description"], entry["no_target_reason"],
                 entry["uk"]["no_target_reason"]):
        assert text and "—" not in text and "→" not in text


# --- 2: SILAB's HPV rows carry the lab record's name -------------------------------

HPV_PAGE = """ПЛР. ВПЛ ВКР (генотипування, якісне
визначення)
16 генотип не виявлено не виявлено
18 генотип не виявлено не виявлено
"""


def test_a_silab_genotype_row_is_named_as_the_lab_record_names_it():
    rows = parse_silab_page(HPV_PAGE, 1)
    record = _record_name({"test": "16 генотип", "packet": "ПЛР. ВПЛ ВКР (генотипування 16, 18, 31, якісне визначення)"})
    assert [row.raw_name for row in rows] == [record, "ПЛР. ВПЛ ВКР, 18 генотип"]


@pytest.fixture
def connection(tmp_path: Path):
    from anamna.config import Settings
    from anamna.db import migrate

    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        pipeline.seed_concepts(conn)
        yield conn


def test_the_print_and_the_lab_record_are_one_series(connection):
    vendor = ensure_vendor(connection, "Synevo", None)
    printed = parse_silab_page(HPV_PAGE, 1)[0]
    record = _record_name({"test": "16 генотип", "packet": "ПЛР. ВПЛ ВКР (генотипування 16, 18, якісне визначення)"})
    on_print, _ = ensure_concept(connection, printed.raw_name, vendor, value_type="text", clinical_type="laboratory")
    on_record, _ = ensure_concept(connection, record, vendor, value_type="text", clinical_type="laboratory")
    assert on_print == on_record


def test_a_verified_bare_genotype_row_moves_to_the_named_concept_on_reread(tmp_path: Path, rescanner):  # noqa: F811
    settings, user_id, _ = build(tmp_path)
    renamed = "ПЛР. ВПЛ ВКР, 16 генотип"
    with connect(settings) as connection:
        vendor = connection.execute("SELECT vendor_id FROM documents WHERE id='doc-1'").fetchone()[0]
        # As an older reader filed it, with a category an inference gave the bare name.
        bare, _ = ensure_concept(connection, "16 генотип", vendor, value_type="text", clinical_type="laboratory")
        connection.execute("UPDATE concepts SET category='infection' WHERE id=?", (bare,))
        row = connection.execute("SELECT id, page_number FROM observations WHERE document_id='doc-1' LIMIT 1").fetchone()
        connection.execute(
            """UPDATE observations SET raw_name='16 генотип', value_numeric=NULL, value_text='не виявлено',
                   unit_raw=NULL, unit_canonical=NULL, comparator=NULL, concept_id=?, verification_status='verified',
                   evidence_text='16 генотип не виявлено не виявлено' WHERE id=?""", (bare, row["id"]))
        connection.execute("DELETE FROM observations WHERE document_id='doc-1' AND id<>?", (row["id"],))
        connection.commit()
    rescanner([ParsedObservation(
        raw_name=renamed, value_numeric=None, value_text="не виявлено", comparator=None, unit_raw=None,
        reference_text="не виявлено", reference_low=None, reference_high=None, page_number=row["page_number"],
        evidence_text="16 генотип не виявлено не виявлено", confidence=0.9,
    )])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        stored = connection.execute("SELECT raw_name, concept_id, verification_status FROM observations WHERE id=?",
                                    (row["id"],)).fetchone()
        named, _ = ensure_concept(connection, renamed, vendor, value_type="text", clinical_type="laboratory")
    assert (stored["raw_name"], stored["verification_status"]) == (renamed, "verified")
    assert stored["concept_id"] == named != bare


# --- 3: the pages of one order are parsed as one report -----------------------------

LOGO = "ТОВ «НЕОМЕД 2007» Мати та дитина\n"
FOOTER = "Обробка матеріалу та видача результатів аналізів виконується за допомогою лабораторної інформаційної системи SILAB.\n"
ORDER = "Дата замовлення 05/04/2023 09:12 № замовл.: 7700002222\n"


def test_a_silab_results_page_that_reads_as_a_clinical_report_is_parsed_with_its_order():
    # Page 1 holds the results but lost its table header and footer to OCR;
    # page 3 prints no order number.  One order, so one report.
    pages = [
        text_page(1, "", LOGO + "Результати досліджень\n" + ORDER + HPV_PAGE),
        text_page(2, "", LOGO + ORDER + "Показник Результат Од. Референтний інтервал\n" + FOOTER),
        text_page(3, "", LOGO + "Дата замовлення 05/04/2023 09:12\nПоказник Результат Од. Референтний інтервал\n" + FOOTER),
    ]
    document, per_page = classify_pages("print.pdf", "application/pdf", pages, {})
    assert pipeline._one_report(per_page) and len(pipeline._report_runs(per_page)) > 1
    rows = parse_pages(document, per_page, pages)
    assert [row.raw_name for row, _ in rows] == ["ПЛР. ВПЛ ВКР, 16 генотип", "ПЛР. ВПЛ ВКР, 18 генотип"]
    assert {page_class.clinical_type for _, page_class in rows} == {document.clinical_type}


def test_two_orders_in_one_file_are_still_parsed_apart():
    header = "Результати досліджень\nДата замовлення: {day}.02.2025 10:30\nПоказник Результат Од. Референтний інтервал\n"
    pages = [text_page(1, header.format(day="01") + "Індикатор зони підвищеної уваги\nГлюкоза 5.1 ммоль/л 3.9 - 5.8\n"),
             text_page(2, "", LOGO + header.format(day="03") + "Глюкоза 5.4 ммоль/л 3.9 - 5.8\n")]
    document, per_page = classify_pages("file.pdf", "application/pdf", pages, {})
    assert not pipeline._one_report(per_page)
    rows = parse_pages(document, per_page, pages)
    assert {(row.page_number, page_class.report_date) for row, page_class in rows} <= {
        (1, "2025-02-01"), (2, "2025-02-03")}
