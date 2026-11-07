"""Browser prints of the partner clinic's SILAB results, read from their scans.

Each page of such a print is one screenshot placed small on the sheet, so the
page render read it at fewer pixels than the picture has; and the text that
comes back is OCR, in which a grade «III» arrives as «І» and a genotype 33 as
38.  The reader keeps only rows it recognises whole.  Every line below is
synthetic, shaped like the scans and carrying invented names and numbers.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from anamna.ingest import extract
from anamna.ingest.classifier import classify_document
from anamna.ingest.concepts import concept_for_alias, specimen_family
from anamna.ingest.parsers import parse_document, parse_silab_page

HEADER = """Медичний центр київ / ЖИТОМИР / ЛЬВІВ
ТОВ «НЕОМЕД 2007» Мати та дитина +38 (044) 000-0-000
e-mail: info@mdclinics.com.ua
Результати досліджень
Дата замовлення: 02/03/2020 10:05 Мезамовл.: 6001234567
Пацієнт: Тестова Ольга Іванівна
Стать: Жіноча Лікар:
Показник Результат Од. Референтний інтервал
"""
FOOTER = """Результати пабораторних досліджень не є достатньою підставою для постановки діагнозу.
Обробка матеріалу та видача результатів аналізів виконується за допомогою пабораторної інформаційної системи SILAB.
Стор. 1з1 Дата друку: 04.03.2020
"""


def page(text: str, number: int = 1) -> dict[str, object]:
    return {"page_number": number, "native_text": "02.03.26, 10:26\nСторінка 1 із 1", "ocr_text": text,
            "native_char_count": 31, "image_count": 2, "extraction_method": "page_image_ocr"}


def rows(*texts: str, vendor: str = "Unknown vendor") -> dict[tuple, tuple]:
    pages = [page(text, number) for number, text in enumerate(texts, start=1)]
    return {
        (item.page_number, item.raw_name, item.specimen): (
            item.value_numeric if item.value_numeric is not None else item.value_text, item.unit_raw,
            item.reference_text,
        )
        for item in parse_document(vendor, "laboratory", pages)
    }


# --- the scan's own pixels ---------------------------------------------------

def scan_pdf(tmp_path: Path, box: tuple[float, float]) -> Path:
    from reportlab.pdfgen.canvas import Canvas

    scan, logo, target = tmp_path / "scan.png", tmp_path / "logo.png", tmp_path / "print.pdf"
    Image.new("RGB", (1170, 1653), "white").save(scan)
    Image.new("RGB", (19, 19), "red").save(logo)
    canvas = Canvas(str(target), pagesize=(595, 842))
    canvas.drawImage(str(logo), 36, 780, 15, 15)
    canvas.drawImage(str(scan), 43, 353, *box)
    canvas.save()
    return target


def test_a_screenshot_placed_small_is_read_from_its_own_pixels(tmp_path, monkeypatch):
    source = scan_pdf(tmp_path, (312, 441))
    with pdfium.PdfDocument(source) as document:
        # At the page render's 3.5x the box is 1092 px wide: fewer than 1170.
        assert extract._embedded_scan(document[0], 3.5).size == (1170, 1653)
        assert extract._embedded_scan(document[0], 4.0) is None
    seen: list[tuple[int, int]] = []

    def read(path):
        with Image.open(path) as image:
            seen.append(image.size)
        return "Колір бурштиновий" if image.size == (1170, 1653) else "Колір"

    monkeypatch.setattr(extract, "_read_scan", read)
    assert extract.ocr_pdf_page(source, 0) == "Колір бурштиновий"
    assert (1170, 1653) in seen


def test_the_render_wins_when_the_pixels_read_less(tmp_path, monkeypatch):
    """A scan placed some way the matrix check misses reads as less: the render is kept."""
    source = scan_pdf(tmp_path, (312, 441))
    monkeypatch.setattr(
        extract, "_read_scan", lambda path: "x" if Image.open(path).size == (1170, 1653) else "the page as shown"
    )
    assert extract.ocr_pdf_page(source, 0) == "the page as shown"


def test_a_screenshot_rendered_larger_keeps_the_page_render(tmp_path):
    source = scan_pdf(tmp_path, (516, 730))
    with pdfium.PdfDocument(source) as document:
        assert extract._embedded_scan(document[0], 3.5) is None


def test_a_small_picture_is_enlarged_by_a_whole_factor():
    assert extract._enlarged(Image.new("L", (1000, 1200))).size == (2000, 2400)
    assert extract._enlarged(Image.new("L", (1170, 1653))).size == (1170, 1653)


# --- classification and metadata --------------------------------------------

def test_a_silab_print_is_a_laboratory_report_with_its_order_and_tests():
    text = HEADER + "Загальна клініка\nАналіз yir мазка на мікрофлору (на склі)\nТОЧКА2 VAGINA\n" + FOOTER
    result = classify_document("file.pdf", "application/pdf", [page(text)])
    assert result.clinical_type == "laboratory"
    assert result.status == "final"
    assert result.report_date == "2020-03-02"
    assert result.order_identifier == "6001234567"
    assert result.title == "Аналіз у/г мазка на мікрофлору (на склі)"
    # The form prints when it was ordered, not when the smear was taken.
    assert result.collected_at is None


def test_the_synevo_copy_names_its_sampling_day_and_one_urinalysis():
    text = (
        "Сінево (Synevo)\nАналіз сечі загальний (ЗАС + ручна мікроскопія осаду) (Аналіз сечі загальний;Ручна\n"
        "Дата забору матеріалу: 01.03.2020\nАналіз сечі загальний (ЗАС + мікроскопія -\nосаду)\n" + FOOTER
    )
    result = classify_document("file.pdf", "application/pdf", [page(text)])
    assert result.clinical_type == "laboratory"
    assert result.report_date == "2020-03-01"
    assert result.collected_at == "2020-03-01"
    assert result.title == "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"


def test_the_2026_print_gives_its_barcode_beside_the_client_and_its_result_time():
    text = (
        "info@mdclinics.com.ua\nРезультати досліджень\nДата замовлення: 01.02.2026 15:15\n"
        "Дата результату: | 03.02.2026 14:36\nКлієнт: Тестова Ольга Іванівна 3600000001\n"
        "ПАП-тест методом рідинної цитології\nОбробка матеріалу та видача результатів аналізів виконується\n"
    )
    result = classify_document("file.pdf", "application/pdf", [page(text)])
    assert result.clinical_type == "laboratory"
    assert result.order_identifier == "3600000001"
    assert result.issued_at == "2026-02-03T14:36"


# --- the reader -------------------------------------------------------------

URINE = HEADER + """Аналіз сечі загальний (ЗАС + мікроскопія осаду)
Аналіз сечі загальний
колір бурштиновий від світло-жовтого до жовтого кольору
Прозорість каламутна прозора
Відносна щільність 1.031 г/мл 1.002 1.030
pH 5 5.0-9.0
Нітрити He виявлені не виявлені
Білок не виявлений г/л He виявлений
0.25=+
0.75 = ++
1.5 = +++
5.0 = ++++
Глюкоза не виявлена ммоль/л не виявлена
заз
6=++
Лейкоцити 25 Leu/µL не виявлені
25=+
100 = ++
500 = +++
Лейкоцити визначаються за активністю
лейкоцитестерази.
Кетонові тіла 7 ммоль/л не виявлені
0.5=+
1.5 = ++
5.0 = +++
15 = ++++
Аналіз сечі: Мікроскопія осаду сечі
Клітини плоского епітелію не виявлені т не виявлені, 1-15
Кристали оксалату кальцію не виявлені не виявлені
Bockonogi6vi циліндри не виявлені не виявлені
Аморфні урати Не виявлені
""" + FOOTER


def test_urine_rows_are_kept_only_when_every_printed_cell_reads():
    found = rows(URINE)
    assert found[(1, "Колір", "сеча")] == ("бурштиновий", None, "від світло-жовтого до жовтого кольору")
    assert found[(1, "Прозорість", "сеча")] == ("каламутна", None, "прозора")
    assert found[(1, "pH", "сеча")] == (5.0, None, "5.0 - 9.0")
    assert found[(1, "Нітрити", "сеча")] == ("не виявлені", None, "не виявлені")
    assert found[(1, "Білок", "сеча")] == ("не виявлений", "г/л", "не виявлений 0.25 = + 0.75 = ++ 1.5 = +++ 5.0 = ++++")
    assert found[(1, "Лейкоцити", "сеча")] == (25.0, "Leu/µL", "не виявлені 25 = + 100 = ++ 500 = +++")
    assert found[(1, "Кристали оксалату кальцію", "сеча")] == ("не виявлені", None, "не виявлені")
    names = {name for _, name, _ in found}
    # «1.002 1.030» lost its dash; the glucose scale lost two tiers; ketones
    # read 7, which is no tier of its scale; the epithelium unit read «т».
    assert {"Відносна щільність", "Глюкоза", "Кетонові тіла", "Клітини плоского епітелію"}.isdisjoint(names)
    # A flagged value lost to its box leaves only the reference: no row, not «не виявлені».
    assert "Аморфні урати" not in names
    # The row above a spoiled label keeps its own value.
    assert len(found) == 7


SMEAR = HEADER + """Загальна клініка
Аналіз у/г мазка на мікрофлору (на склі)
ТОЧКА 1 URETRA
Матеріал відсутній
TOUKA2 VAGINA
Лейкоцити 40-50 вп/з
Еритроцити He виявлені
Флора дрібні палички в помірній кількості
коки є помірній кількості
Дріжджоподібний грибок міцелій в невеликій кількості
ТОЧКАЗ CERVIX
Лейкоцити 20-306 0
Флора (дрібні палички у великій кількості
й
Trichomonas vaginalis невиявлена
Висновок Ступінь чистоти III
""" + FOOTER


def test_smear_rows_carry_their_site_and_drop_what_ocr_spoiled():
    found = rows(SMEAR)
    assert found[(1, "Мазок на мікрофлору", "URETRA")] == ("Матеріал відсутній", None, None)
    assert found[(1, "Лейкоцити", "VAGINA")] == ("40-50 в п/з", None, None)
    assert found[(1, "Еритроцити", "VAGINA")] == ("не виявлені", None, None)
    assert found[(1, "Дріжджоподібний грибок", "VAGINA")] == ("міцелій в невеликій кількості", None, None)
    assert found[(1, "Флора", "CERVIX")] == ("дрібні палички у великій кількості", None, None)
    assert found[(1, "Trichomonas vaginalis", "CERVIX")] == ("не виявлена", None, None)
    assert found[(1, "Ступінь чистоти", None)] == ("III", None, None)
    # Its second line («коки …») did not read, so the vaginal flora is not half of itself.
    assert (1, "Флора", "VAGINA") not in found
    assert (1, "Лейкоцити", "CERVIX") not in found


def test_only_an_untouched_latin_grade_is_a_grade():
    for spoiled in ("І", "Il", "tI", "ПІ", "tt"):
        assert not parse_silab_page(f"Аналіз у/г мазка на мікрофлору\nВисновок Ступінь чистоти {spoiled}\n", 1)


def test_synevos_copy_prints_smear_rows_out_of_order_so_none_carries_a_site():
    text = SMEAR.replace("Мезамовл.: 6001234567", "").replace("Дата замовлення", "Дата забору матеріалу")
    found = rows(text)
    assert {name for _, name, _ in found} == {"Ступінь чистоти"}


HPV = HEADER + """ПЛР Київ
ПЛР. ВПЛ ВКР (генотипування, якісне
визначення)
16 генотип не виявлено ‘He виявлено
Метод Real-Time PCR
Реагенти: Sacace Biotechnologies (Італія), які
(сертифіковані системою CE
38 генотип не виявлено не виявлено
56 генотип не виявлено не виявлено
58 генотип не виявлено не виявлено
"""


def test_a_genotype_outside_the_panel_or_read_twice_is_not_a_result():
    second = HEADER + "ПЛР. ВПЛ ВКР (генотипування, якісне.\n58 генотип не виявлено не виявлено\n"
    found = rows(HPV, second)
    assert found == {(1, "16 генотип", None): ("не виявлено", None, "не виявлено"),
                     (1, "56 генотип", None): ("не виявлено", None, "не виявлено")}


CYTOLOGY = HEADER + """Цитологічні дослідження Київ
Цитологія на атипові клітини (зішкріб,
мазок на склі)
Плоский епітелій (2) Клітини в помірній кількості, розташовані окремо, групами, невеликими
пластами.
Опис морфологічних змін плоскогого епітелік Ядра поодиноких клітин незначно збільшені. Реактивні зміни.
Залозистий епітелій (2) Клітини в невеликій кількості. розташовані окремо, невеликими.
групами.
Клітинні зміни, не пов'язані з неопластичним He виявлені зміни.
(2) й ти
інфекційні агенти He виявлені.
"""


def test_a_cytology_row_reads_whole_sentences_or_not_at_all():
    found = rows(CYTOLOGY)
    assert found == {
        (1, "Плоский епітелій (2)", None): (
            "Клітини в помірній кількості, розташовані окремо, групами, невеликими пластами.", None, None),
        (1, "Опис морфологічних змін плоского епітелію", None): (
            "Ядра поодиноких клітин незначно збільшені. Реактивні зміни.", None, None),
        (1, "Інфекційні агенти", None): ("Не виявлені.", None, None),
    }


def test_a_page_opening_with_the_previous_pages_rows_keeps_their_section():
    second = "кристали сечової кислоти не виявлені не виявлені\n" + FOOTER
    found = rows(URINE, second)
    assert found[(2, "Кристали сечової кислоти", "сеча")] == ("не виявлені", None, "не виявлені")


def test_the_flat_passes_never_read_the_ocr_of_a_silab_print():
    """«Глюкоза 5.2 ммоль/л» would be a row to the shared passes; outside a section it is noise."""
    noise = {"page_number": 1, "native_text": "", "ocr_text": "info@mdclinics.com.ua\nГлюкоза 5.2 ммоль/л 3.3 - 5.5"}
    assert parse_document("Unknown vendor", "laboratory", [noise]) == []
    plain = dict(noise, ocr_text="Глюкоза 5.2 ммоль/л 3.3 - 5.5")
    assert parse_document("Unknown vendor", "laboratory", [plain])


def test_a_smear_site_is_a_smear_specimen():
    assert specimen_family("VAGINA") == "smear"
    assert specimen_family("CERVIX") == "smear"
    assert concept_for_alias("Лейкоцити", "text", specimen="smear") is None
