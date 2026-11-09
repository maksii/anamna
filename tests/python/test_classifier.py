from anamna.ingest.classifier import classify_document, extract_date
from anamna.ingest.pipeline import page_classifications


def pdf_page(native_text: str, ocr_text: str = ""):
    return {
        "page_number": 1,
        "native_text": native_text,
        "ocr_text": ocr_text,
        "native_char_count": len(native_text),
        "image_count": 1,
    }


def test_st_paraskeva_radiology_is_classified_from_native_text():
    text = (
        'ТОВ "Медцентр Св. Параскеви"\n'
        "Рентгенологічне дослідження\n"
        "Дата: 15.03.2022\n"
        "Ділянка обстеження: поперековий відділ хребта\n"
    )

    result = classify_document(
        "bundle.pdf", "application/pdf", [pdf_page(text, "")]
    )

    assert result.vendor == "St. Paraskeva Medical Center"
    assert result.clinical_type == "radiology_xray"
    assert result.report_date == "2022-03-15"


def test_hybrid_result_table_is_final_and_uses_embedded_ocr_strategy():
    page = pdf_page(
        "ЕКСПЕРТ Результати дослідження №1000176",
        "Назва дослідження Результат Одиниці Референтні значення\nКалій 5.9 ммоль/л 3.8-5.0",
    )
    result = classify_document("result.pdf", "application/pdf", [page])

    assert result.clinical_type == "laboratory"
    assert result.status == "final"
    assert result.extraction_strategy == "native_text_plus_embedded_image_ocr"


def test_cover_export_that_points_to_attachment_has_no_result_value():
    page = pdf_page(
        """Сінево
        Показник Результат Од. Референтний інтервал
        ALEX2-тест
        Ваш результат готовий і знаходиться в додатковому pdf файлі.
        """
    )
    result = classify_document("cover.pdf", "application/pdf", [page])

    assert result.clinical_type == "allergy"
    assert result.status == "result_not_present"


def test_single_report_date_propagates_across_same_type_pages():
    pages = [
        pdf_page("Сінево ALEX2 алерген"),
        {**pdf_page("Сінево ALEX2 алерген дата інтерпретації 31.08.2025"), "page_number": 2},
    ]
    results = page_classifications("alex.pdf", "application/pdf", pages, {})

    assert [item.report_date for item in results] == ["2025-08-31", "2025-08-31"]
    assert extract_date("дата інтерпретації 31.08.2025", "alex.pdf") == "2025-08-31"


def test_kardia_report_is_classified_with_english_recorded_date():
    text = """KARDIA EKG Recording
    6L Recording
    Recorded on:
    Monday, Aug 03, 2026, 1:44 PM
    Kardia Advanced Determination:
    Normal Sinus Rhythm
    2026 AliveCor, Inc."""
    result = classify_document(
        "2026_08_03_ecg-20260803-134448.pdf",
        "application/pdf",
        [pdf_page(text)],
    )

    assert result.vendor == "Kardia"
    assert result.clinical_type == "electrocardiogram"
    assert result.title == "Kardia 6-lead ECG recording"
    assert result.report_date == "2026-08-03"


def image_page(ocr_text: str):
    """A photograph: no text layer, one picture, everything read by OCR."""
    return {
        "page_number": 1,
        "native_text": "",
        "ocr_text": ocr_text,
        "native_char_count": 0,
        "image_count": 1,
        "extraction_method": "tesseract_ukr_eng",
    }


def test_a_photographed_note_is_classified_by_what_it_says():
    """`image/*` used to outrank every fact about the contents.

    A screenshot headed «Консультація сімейного лікаря» became a
    `diagnostic_image` — a kind that means "pictures with no written
    interpretation", promising a radiology reading that was never in it.
    """
    result = classify_document(
        "photo_2026-08-07_20-31-12.jpg",
        "image/jpeg",
        [image_page(
            "« Консультація сімейного лікаря Е...\n\nЛікар: Фока Ірина Ярославівна\n\n"
            "Дата візиту: 23/02/2025\n\nСкарги\n\nA44 вакцинація Бустрікс."
        )],
    )
    assert result.clinical_type == "consultation"

    radiograph = classify_document(
        "photo.jpg",
        "image/jpeg",
        [image_page(
            "Комп'ютерна рентгенографія\n\nДілянка тіла: Рентгенографія ОГК\n\n"
            "Висновок: видимої вогнищево- інфільтративної патології не виявлено."
        )],
    )
    assert radiograph.clinical_type == "radiology_xray"

    # An image whose text says nothing recognisable is still what the kind is
    # actually for.
    picture = classify_document("scan.jpg", "image/jpeg", [image_page("IM-0001-0001")])
    assert picture.clinical_type == "diagnostic_image"


def test_a_recommendation_to_see_a_specialist_is_not_a_consultation():
    """The guard that keeps the generalisation from eating the corpus.

    Every Expert Hospital laboratory report ends «потребують консультації
    лікаря», and every imaging report ends with a referral. Matching those
    refiled sixty documents as consultations.
    """
    laboratory = classify_document(
        "result.pdf",
        "application/pdf",
        [pdf_page(
            "Експерт\nПоказник Результат Од. Референтний інтервал\n"
            "Гемоглобін 148 г/л 130 - 160\n" + "\u00a0" * 200 +
            "\nРезультати досліджень не є клінічним діагнозом і потребують консультації лікаря."
        )],
    )
    assert laboratory.clinical_type == "laboratory"

    ultrasound = classify_document(
        "abdo.pdf",
        "application/pdf",
        [pdf_page(
            "Протокол ультразвукового дослідження органів черевної порожнини\n"
            + "Опис дослідження. " * 20
            + "\nрекомендовано: консультація гастроентеролога"
        )],
    )
    assert ultrasound.clinical_type == "ultrasound"


def test_order_number_is_never_the_day_of_the_order_date():
    """Synevo prints «Дата замовлення: 28.08.2025»; the unanchored pattern
    stored "28" as the order number of every Synevo report.  Its barcode,
    printed unlabelled after the patient's sex, is the real identifier."""
    from anamna.ingest.classifier import extract_order_identifier

    synevo = "Дата замовлення: 28.08.2025 08:39 Оформлено: онлайн\nСтать: Чоловіча 3600000777\nПоказник"
    assert extract_order_identifier(synevo) == "3600000777"
    assert extract_order_identifier("Дата замовлення: 15.07.2015") is None
    assert extract_order_identifier("Замовлення: 12345678 / 05.11.2026 08:13") == "12345678"


def test_an_esculab_order_is_titled_by_all_its_panels():
    """The first «Пакет» line named a whole multi-panel order after one panel."""
    from anamna.ingest.classifier import extract_title

    text = (
        "Результати дослідження №10000001\n"
        "1. Холестерин не-ЛПВЩ 3.29 ммоль/л\n"
        "2. F2005 Пакет №6. Ліпідограма\n"
        "3. F0501 Пакет №2. Печінкові проби\n"
        "1. F5000 Коагулограма\n"
    )
    # The uncoded test is part of the order too; it follows the panels.
    assert extract_title(text, "x.pdf", "laboratory") == (
        "Ліпідограма · Печінкові проби · Коагулограма · Холестерин не-ЛПВЩ"
    )
    single ="1. F6001 Загальний аналіз сечі автоматизований (ЗАС автоматизований)\n"
    assert "Загальний аналіз сечі" in extract_title(single, "x.pdf", "laboratory")


def test_a_clinic_document_takes_its_name_day_and_clinic_from_the_lab_sync_file_name():
    """Doctor Eleks documents arrive as «<clinic>-<id> <day> <the clinic's name>.pdf»:
    a cardiology note quoting an ultrasound is still the cardiology consultation,
    a note with no printed date or clinic name still gets both."""
    quoting = "Скарги відсутні\nУЗД ОЧП Сонографічно незначні дифузні зміни паренхіми печінки\nРекомендовано контроль"
    result = classify_document("veselka-2000161 2026-08-09 Консультація лікаря-кардіолога.pdf", "application/pdf",
                               [pdf_page(quoting)])
    assert (result.vendor, result.clinical_type, result.title, result.report_date) == (
        "Veselka", "consultation", "Консультація лікаря-кардіолога", "2026-08-09")
    bare = classify_document("paraskeva-4000786 2022-03-17 Загальний аналіз крові.pdf", "application/pdf",
                             [pdf_page("Гемоглобін 152 г/л 130-165\nПопередні аналізи Synevo в нормі")])
    assert (bare.vendor, bare.title) == ("St. Paraskeva Medical Center", "Загальний аналіз крові")
    # An ordinary upload is untouched by the pattern.
    upload = classify_document("Консультація 2026.pdf", "application/pdf", [pdf_page("Довільний текст")])
    assert upload.vendor == "Unknown vendor" and upload.title == "Консультація 2026"
