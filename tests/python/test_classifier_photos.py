"""Phone photos and scans read by OCR: dates, titles, kinds and clinics.

Every line here is synthetic, shaped like what OCR made of a ~590x1280
messenger photo (debris, split words, Latin look-alikes); names and numbers
are invented.
"""
import sqlite3

import pytest

from anamna.ingest.classifier import classify_document, extract_date, misread_order
from anamna.ingest.pipeline import checked_order


def photo(text: str, name: str = "photo.jpg"):
    return classify_document(
        name, "image/jpeg",
        [{"page_number": 1, "native_text": "", "ocr_text": text, "native_char_count": 0, "image_count": 1}],
    )


INMED = (
    "МЕДИЧНИЙ ЦЕНТР\n"
    "їн Мед Ліцензія Мо1111 від 01.02.2019\n"
    "тел.: 068 688 06 69, 063 000 00 00\n"
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The table rule read as a pipe, no colon.
        ("ОБСТЕЖЕННЯ ОРГАНІВ МАЛОГО ТАЗУ\nДата обстеження | 09.05.2024\n", "2024-05-09"),
        # The value OCR read above its label.
        ("ПІБ пацієнта, рік народження Петренко Ольга\nп 19.03.2025\nДата обстеження\n", "2025-03-19"),
        # The label lost, the value alone under the patient row; «О.М.» is labelled.
        ("ПІБ пацієнта, рік народження\nДата обстеження Петренко Ольга 1990\n09.05.2024 , р,\nО.М. 01.05.2024\n",
         "2024-05-09"),
        ("ПІБ пацієнта, рік народження Петренко Ольга, 1990 р.\nО.М. 12.03.2025\nГрудні залози симетричні;\n", None),
        # UltraMed: the name, the birth year, then the examination day.
        ("Протокол ульт\n08-2026\nПетренко Ольга\nназ\n1990\n14.08.2026\nПЕЧІНКА.\n", "2026-08-14"),
        ("Дате: 16.04.2025\nЛікар\n", "2025-04-16"),
        ("Діагноз клінічний\nпідпис\nдата 18:08.2023\n", "2023-08-18"),
        ("Рекомендації: ...\nДата: 03 08.2025\n", "2025-08-03"),
        ("Pea: 000 0000 000\nДата обстеження 12,10.2023\nДихальний тест\n", "2023-10-12"),
        # «Дата» and «консультації: …» on separate lines.
        ("І-й КОНСУЛЬТАЦІЯ ГАСТРОЕНТЕРОЛОГА\nЛІКАРНЯ\nконсультації: 19.09.2024\nПацієнт: Петренко Ольга\n",
         "2024-09-19"),
        # The next visit is never the visit.
        ("Дата наступної\nконсультації: 26.09.2024\nЛікар гастроентеролог\n", None),
        ("Наступна консультація: 23.05.2026\n", None),
    ],
)
def test_photo_dates_in_every_shape_ocr_reads_them(text, expected):
    assert extract_date(text, "photo.jpg") == expected


def test_the_messenger_screenshot_date_is_never_the_report_date():
    assert photo("Ви\n16.07.26\nОПИТУВАЛЬНИК СИМПТОМІВ\n").report_date is None


@pytest.mark.parametrize(
    ("heading", "title"),
    [
        ("ОБСТЕЖЕННЯ ОРГАНІВ МАЛОГО ТАЗУ рон", "Обстеження органів малого тазу"),
        ("Огляд щитоподібної залози", "Огляд щитоподібної залози"),
        ("Огляд грудних залоз чо Gere -", "Огляд грудних залоз"),
    ],
)
def test_inmed_protocol_is_an_ultrasound_named_by_its_heading(heading, title):
    result = photo(INMED + heading + "\nПІБ пацієнта, рік народження Петренко Ольга, 1990 р.\n"
                   "Дата обстеження 13.08.2026\nМатка розташована в anteflexio versio\n")
    assert (result.clinical_type, result.title, result.vendor, result.report_date) == (
        "ultrasound", title, "InMed", "2026-08-13"
    )


def test_inmed_photo_that_kept_only_the_description_is_still_an_ultrasound():
    result = photo("пн Мед Ліцензія No\nОБСТЕЖЕННЯ ОРІ!\nМатка розташована в anteflexio versio\n")
    assert (result.clinical_type, result.vendor) == ("ultrasound", "InMed")


def test_ultramed_subject_line_names_the_study_and_a_lab_section_does_not():
    gut = photo(
        "Ультра/мед (068) 000-00-00\nwww.ultramed\nПротокол ультразвукового обстежен ня\n"
        "Обстеження шлунково кишкового тракту (ШКТ У\nСтравохід 10 мм\n"
    )
    assert (gut.clinical_type, gut.title, gut.vendor) == ("ultrasound", "УЗД шлунково-кишкового тракту", "UltraMed")
    joint = photo(
        "Протокол ультразвукового обстеження\nДата обстеження 14.08.2026\n"
        "Ультрасонографічне обстеження скронево-нижньощелепних суглобів\nта жувальних м'язів i\nЛівий СНЩС\n"
    )
    assert joint.title == "УЗД скронево-нижньощелепних суглобів та жувальних м'язів"
    sections = photo("Протокол ульт\nПЕЧІНКА.\nНе збільшена\nНИРКИ.\nРозміщені типово\n")
    assert sections.clinical_type == "ultrasound"
    lab = classify_document("lab.pdf", "application/pdf", [{
        "page_number": 1, "native_text": "Печінка\nАЛТ 20 Од/л\nНирки\nКреатинін 70 мкмоль/л\n", "ocr_text": "",
        "native_char_count": 60, "image_count": 0,
    }])
    assert lab.clinical_type != "ultrasound"


def test_breath_tests_are_named_by_their_test_and_clinic():
    pylori = photo(
        "Gastray/; ve\nKNIHIKA FACTPOEHTEPONAM)\n"
        "Консультативний висновок за результатами дихального тесту Ha\nвизначення бактерії Helicobacter pylori.\n"
        "| Пацієнт: Петренко Ольга\n| Дата тестування: | 15.08.2026\nДихальний тест дозволяє виявити інфекцію\n"
    )
    assert (pylori.clinical_type, pylori.vendor, pylori.report_date) == ("clinical_report", "GastroLife", "2026-08-15")
    assert pylori.title == (
        "Консультативний висновок за результатами дихального тесту на визначення бактерії Helicobacter pylori"
    )
    sibo = photo(
        "Синдро дром надмірного\n;\nGastr бактерійного росту в\nКЛІНІКА ГАСТРОЕНТЕРОЛО mW\nтонкому кишківнику\n"
        "Дата проведення тесту\nПетренко Ольга Стать Жіноча 05.11.2026\n"
    )
    assert (sibo.title, sibo.vendor) == (
        "Дихальний тест на визначення надмірного бактерійного росту у кишківнику", "GastroLife"
    )


def test_endoscopy_service_report_is_titled_by_its_service_and_hospital():
    result = photo(
        'КОМУНАЛЬНЕ НЕКОМЕРЦІЙНЕ ПІДПРИЄМСТВО " ЛЬВІВСЬКЕ ТЕРИТОРІАЛЬНЕ МЕДИЧНЕ\nОБ\'ЄДНАННЯ "\n'
        "ДІАГНОСТИЧНИЙ ЗВІТ за послугою\nПанендоскопія до дванадцятипалої кишки\nПацієнт: Петренко Ольга\n"
        "Дата та час формування діагностичного звіту: 09.05.2024 12:06\n"
    )
    assert result.title == "Діагностичний звіт: Панендоскопія до дванадцятипалої кишки"
    assert result.vendor == "Lviv Territorial Medical Association"


@pytest.mark.parametrize(
    "area",
    ["Область Рентгенографія граф ОГК (дві (дві проекції)", "сен Область Pentre: нографія ОГК (дві проекції)"],
)
def test_xray_area_survives_ocr_echo_and_a_garbled_first_word(area):
    result = photo(
        "ЕКСПЕРТ\nКомп'ютерна рентгенографія досліджень Ne 1234\nвід 30.09.2026\nЧастина тіла Грудна клітина\n"
        f"{area}\nдослідження\nРезультат:\n"
    )
    assert (result.clinical_type, result.title) == ("radiology_xray", "Рентгенографія ОГК (дві проекції)")


@pytest.mark.parametrize(
    ("heading", "title"),
    [
        ("Консу: втаційне заключення", "Консультаційне заключення"),
        ("Консультативне заклю слючення", "Консультативне заключення"),
        ("КОНСУЛЬТАТИВНИЙ BUCHOBOK ме мі000097 22 33 911,", "Консультативний висновок"),
    ],
)
def test_consultation_form_name_is_spelt_out_from_what_ocr_kept(heading, title):
    result = photo(f"{heading}\nПацієнт: Петренко Ольга\nСкарги на біль\nАнамнез: 2 тижні\n")
    assert (result.clinical_type, result.title) == ("consultation", title)


def test_consultation_heading_without_its_patient_label_and_with_letterhead_debris():
    seen = photo("ТЗОВ \"Львів Медікал Центр Хірургія\"\nemail: office@ivivmedicaicenter.com\nОГЛЯД ГІНЕКОЛОГА\n"
                 "ацієнта: Петренко Ольга\nСкарги на момент огляду\nГінекологічний анамнез\n")
    assert (seen.title, seen.vendor) == ("Огляд гінеколога", "Lviv Medical Center")
    phone = photo("Форма Мо 028/0\n72233911\nКОНСУЛЬТАЦІЯ з 73 22 33 911 Медікал\nСкарги\nАнамнез хвороби\n")
    assert (phone.title, phone.vendor) == ("Консультація", "Expert Hospital")


def test_a_recommended_service_is_never_a_consultation_title():
    result = photo(
        "овані послуги: 1) - Повторна консультація після дообстеження.\nСкарги на біль\nАнамнез: 2 дні\n"
        "Лікар гастроентеролог\n"
    )
    assert result.clinical_type == "consultation"
    assert result.title == "photo"


def test_second_page_of_a_consultation_is_a_consultation():
    result = photo("діагноз попередній: Кіста правого яйника\nрекомендації:\n1. Повторити УЗД\nдата: 24.11.2025\n")
    assert (result.clinical_type, result.report_date) == ("consultation", "2025-11-24")
    colposcopy = photo("Діагноз кольпоскопічний:\nНормальна картина\nрекомендовано\nдата 18:08.2023\n")
    assert colposcopy.clinical_type == "clinical_report"


def test_questionnaires_have_their_own_kind_and_name():
    vanderbilt = photo("Ви\n16.07.26\nОПИТУВАЛЬНИК СИМПТОМІВ ПОВЕДІНКОВИХ РОЗЛАДІВ\n"
                       "У ДІТЕЙ ТА ПІДЛІТКІВ ,ХІСНО Vanderbilt” форма A\n")
    assert (vanderbilt.clinical_type, vanderbilt.title) == ("questionnaire", "Опитувальник NICHQ Vanderbilt (форма A)")
    asrs = photo("Нікозли|Ріджо|Їмоді| Часто\nЯк часто у вас виникають\nASRS\n")
    assert (asrs.clinical_type, asrs.title) == ("questionnaire", "Опитувальник ASRS")


def test_consent_forms_are_administrative_without_the_order_cover_note():
    result = photo("ЄДРПОУ 00000000\nеш ІНФОРМОВАНА ДОБРОВІЛЬНА ЗГОДА ПАЦІЄНТА\nна проведення втручання\n")
    assert (result.clinical_type, result.title, result.status, result.notes) == (
        "administrative", "Інформована добровільна згода пацієнта", "supporting_record", None
    )
    assert photo("Згода на обробку персональних даних\nДата: 24.03.2025\n").title == (
        "Згода на обробку персональних даних"
    )


def test_vaccination_booklet_and_rabies_card_are_vaccination_records():
    booklet = photo("Mpenapar Дата Серія Підпис і печатка\nПроти\nполіомієліту\n")
    assert booklet.clinical_type == "immunization_record"
    rabies = photo("но 045/0\nЗАТВЕРДЖЕНО\nми ї коли: КНП ІТМО ВП лікарня святого\nТирабічн: щеплення\n")
    assert (rabies.clinical_type, rabies.title, rabies.vendor) == (
        "immunization_record", "Карта звернення за антирабічною допомогою",
        "First Territorial Medical Association of Lviv, St. Luke's Hospital",
    )


def test_lviv_territorial_associations_and_a_private_practice_are_named():
    second = photo("ТОВАРИСТВО \"ДРУГЕ КЛІНІЧНЕ.\nКАРТА ПРОФІЛАКТИЧНИХ ЩЕПЛЕНЬ\n")
    assert second.vendor == "Second Clinical Territorial Medical Association of Lviv"
    first = photo("ЄДРПОУ: 44496574\nКонсультаційний висновок спеціаліста\n")
    assert first.vendor == "First Territorial Medical Association of Lviv, St. Luke's Hospital"
    practice = photo("ФОП Коваленко Петро Іванович\n02000, м.Київ\nКОНСУЛЬТАЦІЙНИЙ ВИСНОВОК СПЕЦІАЛІСТА\n")
    assert practice.vendor == "ФОП Коваленко П. І."


def test_another_clinics_sheet_at_the_top_edge_does_not_name_the_clinic():
    # The edge of a Lviv Medical Center form above an MD Clinics consultation.
    result = photo(
        "ТзОВ \"Львів Медікал Центр\nвул. Довга, 1\nАдреси медичних центрів\nМати та дитина\n"
        "ТОВ «НЕОМЕД 2007»\nКонсультаційне заключення\nПацієнт: Петренко Ольга\n"
    )
    assert result.vendor == "MD Clinics"


def test_a_results_photo_left_an_image_is_named_by_its_test():
    result = photo(
        "mdclinics.com.ua\nРезультати досліджень\nДата замовлення: 06.04.2026 15:15\n"
        "ПАПІ-тест методом рідинної цитології\n(технологія BD SurePath)\n"
    )
    assert (result.clinical_type, result.title) == ("diagnostic_image", "ПАП-тест методом рідинної цитології")


def test_an_order_number_one_digit_off_a_known_order_of_that_day_is_not_stored():
    assert misread_order("1000000691", {"1000000891"})
    assert not misread_order("1000000691", {"1000000691", "2000000000", "100000891"})
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE documents (id TEXT, patient_id TEXT, order_identifier TEXT, report_date TEXT, collected_at TEXT)"
    )
    connection.execute("INSERT INTO documents VALUES ('lab', 'p1', '1000000891', '2026-04-06', NULL)")
    assert checked_order(connection, "p1", "1000000691", "2026-04-06") is None
    assert checked_order(connection, "p1", "1000000691", "2026-04-07") == "1000000691"
    assert checked_order(connection, "p2", "1000000691", "2026-04-06") == "1000000691"
    assert checked_order(connection, "p1", "1000000891", "2026-04-06", "lab") == "1000000891"
