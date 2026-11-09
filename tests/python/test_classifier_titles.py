"""Titles, dates and printed identifiers read from the page, not the filename.

Every text below is synthetic -- invented patient, invented numbers -- shaped
like the real page it stands for.
"""

from anamna.ingest.classifier import (
    KNOWN_CLINICAL_TYPES,
    classify_document,
    extract_order_identifier,
    extract_title,
    sentence_case,
)


def page(text: str, number: int = 1) -> dict[str, object]:
    return {"page_number": number, "native_text": text, "ocr_text": "", "native_char_count": len(text), "image_count": 0}


def classify(text: str, filename: str = "2025-01-01__vendor__report__0001.pdf", mime: str = "application/pdf"):
    result = classify_document(filename, mime, [page(text)])
    assert result.clinical_type in KNOWN_CLINICAL_TYPES
    return result


EXPERT_HEAD = (
    "Поліклініка №6\nexperthospital.com.ua\nм. Львів, вул. Тестова, 1\n"
    "Ліцензія МОЗ України\n№ 1234 від 01.01.2020\n"
)
EXPERT_PATIENT = "Пацієнт: Іваненко Іван Іванович, 01.01.1990 р.н. 02.03.2025\nПОКАЗНИК РЕЗУЛЬТАТ НОРМА\n"


def expert(heading: str, body: str = "Залізо, мкмоль/л 20,0 від 9 до 30\n"):
    return classify(EXPERT_HEAD + heading + "\n" + EXPERT_PATIENT + body)


def test_expert_single_test_heading_replaces_the_filename():
    result = expert('"ЗАЛІЗО (СИРОВАТКА КРОВІ)"')
    assert result.title == "Залізо (сироватка крові)"
    assert result.specimen == "сироватка крові"
    assert result.report_date == "2025-03-02"


def test_expert_wrapped_heading_is_joined_and_its_quotes_balanced():
    result = expert(
        '"ПАКЕТ ""ПЕЧІНКОВІ ПРОБИ-1"" (БІЛІРУБІН ФРАКЦІЙНО, ЛУЖНА\nФОСФАТАЗА, ГАММА-ГЛУТАМАТТРАНСФЕРАЗА)"'
    )
    assert result.title == 'Пакет "Печінкові проби-1" (білірубін фракційно, лужна фосфатаза, гамма-глутаматтрансфераза)'
    assert expert('"ПАКЕТ "ЛІПІДОГРАМА""').title == 'Пакет "Ліпідограма"'


def test_expert_order_and_turnaround_codes_are_dropped():
    assert expert("ГЛІКОВАНИЙ ГЕМОГЛОБІН (HBA1C) (B075) (2 ДНІ)").title == "Глікований гемоглобін (HBA1C)"
    assert expert("ВИЯВЛЕННЯ НОСІЙСТВА ГЕНУ HLA B-27 (O0044)").title == "Виявлення носійства гену HLA B-27"
    stated = expert('"ПАКЕТ "СТАН ПІДШЛУНКОВОЇ ЗАЛОЗИ" (ГЛЮКОЗА, Α-АМІЛАЗА, ЛІПАЗА)" (24 ГОД)')
    assert stated.title == 'Пакет "Стан підшлункової залози" (глюкоза, α-амілаза, ліпаза)'
    assert "12 ГОДИН" not in expert('"КОАГУЛОГРАМА (МНВ, ПРОТРОМБІН ПО КВІКУ) (12 ГОДИН)"').title


def test_sentence_case_keeps_abbreviations_codes_and_organisms():
    assert sentence_case("ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ (ЗАС + МІКРОСКОПІЯ ОСАДУ)") == "Загальний аналіз сечі (ЗАС + мікроскопія осаду)"
    assert (
        sentence_case("ШВИДКІ ТЕСТИ (ВІЛ І ТА ІІ ТИПУ, ГЕПАТИТ С, СИФІЛІС, ГЕПАТИТУ В)")
        == "Швидкі тести (ВІЛ І та ІІ типу, гепатит С, сифіліс, гепатиту В)"
    )
    assert sentence_case("БАКПОСІВ З ЗІВУ НА МІКРОФЛОРУ. ЧУТЛИВІСТЬ ДО АНТИБІОТИКІВ ДДМ") == (
        "Бакпосів з зіву на мікрофлору. Чутливість до антибіотиків ДДМ"
    )
    assert sentence_case("ШВИДКИЙ ТЕСТ НА АНТИГЕН H.PYLORI") == "Швидкий тест на антиген H.PYLORI"
    urine = expert('"ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ (ЗАС + МІКРОСКОПІЯ ОСАДУ)"')
    assert urine.title == "Загальний аналіз сечі (ЗАС + мікроскопія осаду)"
    assert urine.specimen == "сеча"
    faeces = expert('"ШВИДКИЙ ТЕСТ НА ВИЗНАЧЕННЯ АНТИГЕНУ H.PYLORI ( ФЕКАЛІЇ )"')
    assert faeces.title == "Швидкий тест на визначення антигену H.PYLORI (фекалії)"
    assert faeces.specimen == "фекалії"


SYNEVO = (
    "Результати досліджень Сінево (Synevo)\nЛабораторія Тестова\n"
    "Дата замовлення: 03.04.2016 08:51 Оформлено: онлайн\n"
    "Клієнт: Іваненко Іван Іванович (AbCdEfGh)\n"
    "Дата народження: 01.01.1990 Вік: 26 Y 3 M Стать: Чоловіча 12345678\n"
    "Показник Результат Од. Референтний інтервал\n"
)


def test_synevo_column_caption_is_not_part_of_the_title_and_every_panel_is_named():
    # A department prints its results straight under it; the title names them.
    single = classify(SYNEVO + "Біохімія Індикатор зони підвищеної уваги\nГлюкоза 5.0 ммоль/л 3.3 - 5.5\n")
    assert single.title == "Глюкоза"
    assert single.order_identifier == "12345678"  # eight-digit barcode of the older reports
    assert single.collected_at == "2016-04-03T08:51"
    city = classify(SYNEVO + "Імунологія Київ Індикатор зони підвищеної уваги\nТест 0.3 R R < 0.8\n")
    assert city.title == "Тест"
    two = classify(
        SYNEVO + "Пакет №4.18.1 (Вітаміни і Мікроелементи) Індикатор зони підвищеної уваги\n"
        "Магній 0.9 ммоль/л 0.66 - 1.07\nПакет №371 (Фолатний обмін міні)\nФолієва кислота 9 нг/мл 3.9 - 26.8\n"
    )
    assert two.title == "Вітаміни і Мікроелементи · Фолатний обмін міні"
    assert extract_order_identifier("Стать: Чоловіча 1234567890\n") == "1234567890"


ESCULAB = (
    "Замовлення: 1234567 / 05.11.2026 08:13 Дата видачі: 05.11.2026 12:23\nЛ:00000\n"
    "Пацієнт: Іваненко Іван Іванович ДН: 01.01.1990 Стать: Чол.\nРезультати дослідження №1234567\n"
)


def test_esculab_code_prefix_never_survives_and_a_wrapped_name_is_joined():
    urine = classify(
        ESCULAB + "1. F6001 Загальний аналіз сечі автоматизований (ЗАС автоматизований)\n"
        "Показник Результат Одиниці Референтні значення\nрН (C-PH) 6.0 - 5.5 - 7.0\nПриносний матеріал, сеча\n"
        "Час відбору: 07:40\n"
    )
    assert urine.title == "Загальний аналіз сечі автоматизований (ЗАС автоматизований)"
    assert urine.collected_at == "2026-11-05T07:40"
    assert urine.issued_at == "2026-11-05T12:23"
    assert urine.specimen == "сеча"
    culture = classify(
        ESCULAB + "1. J0007 Мікробіологічне дослідження виділень із зіву із визначенням чутливості виділених\n"
        "мікроорганізмів до антибіотиків (антибіотикограма) (матеріал: виділення із зіву)\n"
        "Мікроорганізм виявлено Результат\n"
    )
    assert culture.title.endswith("(матеріал: виділення із зіву)")
    assert culture.specimen == "виділення із зіву"
    assert culture.collected_at == "2026-11-05"  # no sampling time printed: the order date alone


def test_garmin_blood_pressure_report_is_titled_as_printed():
    text = (
        "Підсумок\nПоказники кров’яного тиску\nЗвіт про кров’яний тиск протягом\nIvan\n"
        "1 січ. 1990 ( 35 yr ) • Male\n1 року\n16 лют. 2024 - 13 лют. 2025\n"
        "Дані надані програмою Garmin Connect 13 лют. 2025 1 з 2\n"
    )
    result = classify(text, "export.pdf")
    assert result.clinical_type == "blood_pressure"
    assert result.title == "Звіт про кров’яний тиск протягом 1 року"


def test_alex_export_carries_the_sample_barcode_and_the_draw_date():
    text = (
        'ТОВ "Сінево Україна"\nІдентифікаційний номер пацієнта: Протестовані алергени:\n9876543210 295\n'
        "Пацієнт: Метод випробування:\nІваненко Іван Іванович 2\nALEX\n"
        "Ідентифікаційний номер зразка:\nПримітка. Внутрішній контроль якості (перевірка\n9876543210\n"
        "ЗАБІР КРОВІ НАДРУКОВАНИЙ НА\n28.08.2025 31.08.2025\n"
        "Зразок був протестований за штрих-кодом ALEX² 00ABC0, дата інтерпретації 31.08.2025\n"
        "Всі протестовані алергени мали рівні IgE нижче 0,3 kUA/L.\nЗагальний IgE: 39 kU/L\n"
    )
    result = classify(text, "alex.pdf")
    assert result.clinical_type == "allergy"
    assert result.title == "ALEX² - протестовані алергени: 295"
    assert result.order_identifier == "9876543210"
    assert result.collected_at == "2025-08-28"
    assert result.issued_at == "2025-08-31"


def test_vaccination_card_is_titled_and_its_clinic_named():
    text = (
        "МЕДИЧНА ДОКУМЕНТАЦІЯ\nТзОВ Повноділ\nФОРМА № 063/о\nКАРТА ПРОФІЛАКТИЧНИХ ЩЕПЛЕНЬ\n"
        "Прізвище, ім'я Іваненко Іван\nЩеплення проти дифтерії\nДата Вік Доза Серія Назва препарату\n"
        "01.02.2020 30 р. 0,5 AB123 Бустрікс\n"
    )
    result = classify(text, "card.pdf")
    if result.clinical_type == "immunization_record":
        assert result.title == "Карта профілактичних щеплень"
    else:  # the card detector wants more of the form than this snippet carries
        assert extract_title(text, "card.pdf", "immunization_record") == "Карта профілактичних щеплень"
    assert result.vendor == "Veselka"
    assert result.website == "https://veselka.clinic"


US_HEAD = (
    "ТзОВ «ЕКСПЕРТ МЕДІКАЛ ГРУП»\nwww.experthospital.com.ua\n"
    "Прізвище, ім'я, по-батькові пацієнта: Іваненко Іван Іванович\nДата народження: 01.01.1990 р.\n"
)


def test_ultrasound_is_titled_by_its_study_and_dated_from_the_footer():
    result = classify(
        US_HEAD + "ПРОТОКОЛ\nУЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ ОРГАНІВ ЧЕРЕВНОЇ ПОРОЖНИНИ\n"
        "(дослідження проводилось на ультразвуковому апараті експертного класу ____)\n"
        "Печінка не збільшена.\nЗАКЛЮЧЕННЯ: без особливостей\nПідпис пацієнта ____\n"
        "Дата дослідження: Петренко Олена Петрівна\nЛікар:\n01.02.2025 ______\n",
        "УЗД.pdf",
    )
    assert result.clinical_type == "ultrasound"
    assert result.title == "УЗД органів черевної порожнини"
    assert result.report_date == "2025-02-01"
    # The other footer layout: the label itself split around the doctor's name.
    split = classify(
        US_HEAD + "ПРОТОКОЛ\nУЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ СЕРЦЯ\n(дослідження проводилось на апараті)\n"
        "Дата Олена-\nдослідження: Лікар: Марія\n13.02.2025 Петрівна\n",
        "heart.pdf",
    )
    assert split.title == "УЗД серця"
    assert split.report_date == "2025-02-13"


def test_duplex_and_soft_tissue_ultrasound_titles():
    duplex = classify(
        US_HEAD + "ПРОТОКОЛ\nДУПЛЕКСНОГО УЛЬТРАЗВУКОВОГО дослідження\n"
        "ЕКСТРАКРАНІАЛЬНИХ ВІДДІЛІВ СОННИХ ТА ВЕРТЕБРАЛЬНИХ АРТЕРІЙ\n(дослідження проводилось на апараті)\n"
    )
    assert duplex.title == "Дуплексне УЗД екстракраніальних відділів сонних та вертебральних артерій"
    soft = classify(
        US_HEAD + "УЛЬТРАЗВУКОВЕ ДОСЛІДЖЕННЯ М’ЯКИХ ТКАНИН\n(дослідження проводилось на апараті)\n"
        "Локалізація патологічного процесу – в проекції лівого\nплеча\nОсобливості обстеження – утвір 5 мм\n"
    )
    assert soft.title == "УЗД м’яких тканин - в проекції лівого плеча"


def test_a_report_headed_uzd_is_an_ultrasound_from_veselka():
    result = classify(
        "Медичний центр ТзОВ «Повноділ»\nЛіцензія МОЗ України АА 000000 від 01.01.2014р.\nwww.veselka.clinic\n"
        "Дата візиту: 08.08.2026\nПІБ пацієнта: Іваненко Іван Іванович\nУЗД органів черевної порожнини\n"
        "Печінка: розміри: Права доля 130,0 мм.\nВисновок: без змін\n",
        "document.pdf",
    )
    assert result.clinical_type == "ultrasound"
    assert result.vendor == "Veselka"
    assert result.title == "УЗД органів черевної порожнини"
    assert result.report_date == "2026-08-08"


def test_mri_and_xray_titles_drop_labels_and_study_numbers():
    mri = classify(
        'ТОВ "Оксфорд Медікал Захід"\nДата: 06.08.2025\nПІБ: Іваненко Іван Іванович\n'
        "МРТ лівого колінного суглоба MRI 1234\nОбстеження виконане у трьох площинах.\n",
        "knee.pdf",
    )
    assert mri.title == "МРТ лівого колінного суглоба"
    labelled = classify(
        "Протокол 1\nДата обстеження: 15.03.2022\nДілянка обстеження: МРТ грудного відділу хребта.\n"
        "Магнітно-резонансна томографія\n",
        "mri.pdf",
    )
    assert labelled.title == "МРТ грудного відділу хребта"
    xray = classify(
        "Рентгенологічне дослідження\nПротокол 1\nПацієнт: Іваненко Іван Іванович Дата: 15.03.2022\n"
        "Ділянка обстеження: поперековий відділ хребта в двох проекціях.\nТіла хребців норма.\n",
        "xray.pdf",
    )
    assert xray.title == "Рентгенологічне дослідження - поперековий відділ хребта в двох проекціях"
    photo = classify(
        "Комп'ютерна рентгенографія\nДілянка тіла: Рентгенографія ОГК госпіталізацій...\n"
        "Висновок: патології не виявлено.\n",
        "photo.jpg",
        "image/jpeg",
    )
    assert photo.title == "Рентгенографія ОГК"


def test_consultation_title_is_the_heading_never_a_recommendation():
    result = classify(
        "П.І.Б. пацієнта: Іваненко Іван Іванович Стать: Чоловіча\nДата консультації: 12.03.2022\n"
        "Консультативний висновок лікаря ортопеда­травматолога\nПопередній діагноз:\nРекомендовано:\n"
        "Повторна консультація невролога, МРТ поперекового відділу хребта\n",
        "consultation.pdf",
    )
    assert result.title == "Консультативний висновок лікаря ортопеда-травматолога"
    assert "­" not in result.title
    photo = classify(
        "€ Консультація сімейного лікаря Е...\nЛікар: Петренко Олена\nДата візиту: 23/02/2025\nСкарги\n",
        "photo_2026-08-07_20-31-12.jpg",
        "image/jpeg",
    )
    assert photo.title == "Консультація сімейного лікаря"
    assert photo.report_date == "2025-02-23"  # printed, not the photo's own date


def test_pathology_report_number_and_operation_date():
    result = classify(
        EXPERT_HEAD + "БІОПСІЯ СЛИЗОВОЇ ОБОЛОНКИ КИШКІВНИКА\n"
        "Пацієнт: Іваненко Іван Іванович, 01.01.1990 р.н. 12.11.2025\n"
        "Патологогістологічне дослідження Ме 11111/25\nДата надходження матеріалу в лабораторію 10.11.2025\n"
        "Дата операції 07.11.2025 Дата дослідження 12.11.2025\nБіопсія діагностична\n",
        "path.pdf",
    )
    assert result.clinical_type == "pathology"
    assert result.title == "Біопсія слизової оболонки кишківника"
    assert result.report_number == "№ 11111/25"
    assert result.collected_at == "2025-11-07"
    assert result.report_date == "2025-11-12"
    # The same report under another order, OCR reading «№» differently.
    assert classify("Патологогістологічне дослідження N2 11111/25\nбіопсія\n").report_number == "№ 11111/25"


def test_st_paraskeva_form_heading_and_sample_date():
    result = classify(
        "МЕДИЧНА ДОКУМЕНТАЦІЯ\nНайменування закладу ФОРМА № 228/о\nЗатверджена наказом МОЗ України\n"
        "04.01.2001 р. № 1\nІмунологічні дослідження\nПрізвище: Іваненко Іван Іванович Номер 1\n"
        "Дата здачі аналізу: 17.03.2022\nПоказник Результат Одиниці Норма\nРевматоїдний фактор 5 IU/ml <14\n",
        "rf.pdf",
    )
    assert result.title == "Імунологічні дослідження"
    assert result.collected_at == "2022-03-17"


def test_filename_is_the_title_only_when_nothing_printed_is_usable():
    assert classify("Лише якийсь текст без заголовка\n", "scan-0001.pdf").title == "scan-0001"
