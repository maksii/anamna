"""Visit notes, consultations and narrative metadata (review round 2).

Synthetic text in the shape of the pages that went wrong: Expert Hospital's
form 028/о (heading below the letterhead, diagnosis label read into its value,
a software placeholder for a missing diagnosis, vitals with a spaced dash), a
gynaecologist's «Консультаційне заключення», Veselka's consent line cut
mid-sentence, an X-ray dated «від …» with its reading under «Результат:», and
phone photos whose OCR carries the messenger's own interface.  Every name and
number is invented.
"""
import pytest

from anamna.health import _extract_clinical_assessment, _report_body_end, _conclusion_span
from anamna.ingest.classifier import classify_document, strip_screen_chrome
from anamna.ingest.parsers import parse_visit_measurements
from test_clinical_findings import add_report, findings, ledger  # noqa: F401


def page(native: str = "", ocr: str = "", number: int = 1) -> dict[str, object]:
    return {"page_number": number, "native_text": native, "ocr_text": ocr,
            "native_char_count": len(native), "image_count": 1 if ocr else 0}


def classify(native: str = "", filename: str = "Консультація терапевта28.pdf", mime: str = "application/pdf", ocr: str = ""):
    return classify_document(filename, mime, [page(native, ocr)])


FORM_HEAD = (
    "МЕДИЧНА ДОКУМЕНТАЦІЯ ТзОВ «Лікарня ТЕСТ»\nФорма № 028/о test-hospital.example.ua\n"
    "Затверджена наказом МОЗ України № 369 м. Львів, вул. Тестова, 1\nвід 29.12.2000 р.\n+38 097 00 00 000,\n"
)
PATIENT = (
    "Пацієнт: Тестенко Олена Іванівна Дата консультації: 14.11.2024\n"
    "Дата народження: 01.03.1990 р.н. Вік пацієнта: 34 р.\n"
    "Амбулаторна карта пацієнта № 11111 Наступна консультація: 22.11.2024\nКонсультації Поліклініка\n"
)
FOOT = (
    "Дата наступної консультації 22.11.2024\n"
    "З показанням, протипоказанням та можливою побічною дією ознайомлений.\n"
    "Лікар пояснив сутність мого захворювання. Своїм власним підписом я підтверджую, що мені була надана інформація.\n"
    "Лікар алерголог Лікаренко Ольга Петрівна\nДиректор «Лікарня ТЕСТ»\n"
)


def form(heading: str, body: str) -> str:
    return FORM_HEAD + heading + "\n" + PATIENT + body + FOOT


ALLERGIST = form(
    "КОНСУЛЬТАЦІЯ АЛЕРГОЛОГА\n+38 073 00 00 000.",
    "Скарги висип на тілі з помірним зудом.\n"
    "Анамнез хвороби Печінкова панель в нормі. Туберкульоз, вірусний гепатит заперечує.\n"
    "Об’єктивний статус поодинокі папульозні висипання на сідницях,\n"
    "основний: K52.9 Неінфекційний гастроентерит та коліт, неуточнений\n"
    "Діагноз синдром надмірного бактерійного росту.\n"
    "супутній: L20-L30 Дерматит та екзема\n"
    "супутній: L20-L30 Дерматит та екзема\n"
    "Дані лабораторних та\nінструментальних обстежень\n"
    "Рекомендації і лікування 1. здати харчову панель.\n2. Ерус по 1 таб протягом 14 днів.\n"
    "Рекомендовані послуги: 1) Консультація дерматолога (первинна),\n2) Харчова панель №1 (20 алергенів, Polycheck) (H0009),\n",
)
NO_DIAGNOSIS = form(
    "КОНСУЛЬТАЦІЯ ТЕРАПЕВТА +38 073 00 00 000,",
    "Скарги періодичний біль голови, тиск у скронях з обох боків.\n"
    "Анамнез хвороби вважає себе хворою декілька місяців\n"
    "Об’єктивний статус слизові зіву блідо-рожеві, ЧД - 16/хв, SpO2 - 98%, тони серця звучні,\n"
    "ритмічні, ЧСС - 78/хв., АТ - 95/60 мм.рт.ст.\n"
    "основний:\nДіагноз\nВкажіть основний діагноз у програмі !\nДані лабораторних та\nінструментальних обстежень\n"
    "Рекомендації і лікування 1). ЗАК з формулою.\n2). Консультація невропатолога.\n",
)
ENDOCRINE = form(
    "КОНСУЛЬТАЦІЯ ЕНДОКРИНОЛОГА +38 073 00 00 000,",
    "Скарги на загальну слабкість\nАнамнез хвороби скерована гастроентерологом\n"
    "УЗД ЩЗ: об'єм 10,9 см3, без патологічних змін\nГлюкоза 5,24, глікований гемоглобін 5,58%\n"
    "Діагноз\nосновний:\nРеактивна гіпоглікемія\nДані лабораторних та\nінструментальних обстежень\n"
    "Рекомендації і лікування 1. Обмежити прості вуглеводи\n2. Безперервний моніторинг глюкози\n",
)


# --- classifier: type, title and date of a consultation ---------------------

def test_form_028_heading_makes_a_consultation_titled_and_dated_by_the_page():
    result = classify(NO_DIAGNOSIS)
    assert (result.clinical_type, result.title, result.report_date) == (
        "consultation", "Консультація терапевта", "2024-11-14")


@pytest.mark.parametrize(("text", "title"), [
    # «Polycheck» among the recommended services is not an allergy panel.
    (ALLERGIST, "Консультація алерголога"),
    # «УЗД ЩЗ: …» quoted in the history is not an ultrasound.
    (ENDOCRINE, "Консультація ендокринолога"),
    (form("ПОВТОРНА КОНСУЛЬТАЦІЯ АЛЕРГОЛОГА\n+38 073 00 00 000.", "Скарги здуття.\n"), "Повторна консультація алерголога"),
])
def test_a_quoted_study_or_a_recommended_panel_never_retypes_a_consultation(text, title):
    result = classify(text, filename="Консультація43.pdf")
    assert (result.clinical_type, result.title) == ("consultation", title)


def test_a_gynaecologists_consultative_conclusion_is_a_consultation():
    text = ("Медичний центр Тест\nПродовження форми №025/о\nVIII. Щоденник\nКонсультаційне заключення\n"
            "Пацієнт: Тестенко Олена Іванівна\nКлінічні дані: Звернулась на кольпоскопію.\n"
            "Заключення: Ендометріоїдна кіста лівого яєчника.\nРекомендовано: 1.Препарат по 1 таб.\nДата: 28.11.2025\n")
    result = classify(ocr=text, filename="file.pdf")
    assert (result.clinical_type, result.title, result.report_date) == (
        "consultation", "Консультаційне заключення", "2025-11-28")


def test_visit_sections_outweigh_a_culture_ordered_in_the_plan_or_a_scan_in_the_history():
    text = ("Скарги на відчуття здуття.\nАнамнез хвороби УЗД ОЧП від 01.05.24р: без змін.\n"
            "Об'єктивний статус Живіт м'який.\nРекомендації: Бакпосів калу на дисбактеріоз.\n")
    assert classify(ocr=text, filename="photo.jpg", mime="image/jpeg").clinical_type == "consultation"


def test_a_scan_report_with_a_history_line_and_advice_stays_a_scan():
    text = ("ПРОТОКОЛ УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ щитоподібної залози\nАнамнез: без особливостей.\n"
            "Висновок: без патології.\nРекомендовано: контроль через рік.\n")
    assert classify(text, filename="scan.pdf").clinical_type == "ultrasound"


def test_an_ultrasound_disclaimer_about_biopsy_is_not_pathology():
    text = ("Протокол ультразвукового обстеження шлунково-кишкового тракту\nСтравохід не розширений.\n"
            "Висновок: УЗ ознаки гастроптозу.\nУЗД не замінить ендоскопічне обстеження, тим більше ендоскопію з біопсією.\n")
    assert classify(text, filename="scan.pdf").clinical_type == "ultrasound"


def test_an_endoscopy_report_and_a_breath_test_are_reports_not_laboratory_or_pictures():
    egd = ("ДІАГНОСТИЧНИЙ ЗВІТ за послугою\nПанендоскопія до дванадцятипалої кишки\nПацієнт: Тестенко Олена\n"
           "Результати дослідження: Протокол Езофагогастродуоденоскопія\nЗаключення лікаря: Гастропатія.\n"
           "Дата та час формування діагностичного звіту: 09.05.2024 12:06\n")
    result = classify(ocr=egd, filename="photo.jpg", mime="image/jpeg")
    assert (result.clinical_type, result.report_date, result.status) == ("clinical_report", "2024-05-09", "final")
    breath = "Синдром надмірного бактерійного росту\nДата проведення тесту\nТестенко Олена Стать Жіноча 05.11.2026\n"
    result = classify(ocr=breath, filename="photo.jpg", mime="image/jpeg")
    assert (result.clinical_type, result.report_date) == ("clinical_report", "2026-11-05")


def test_a_consultation_carries_no_missing_results_status():
    assert classify(ALLERGIST).status == "final"


# --- classifier: dates and titles of narrative documents and clinic prints ---

@pytest.mark.parametrize(("text", "expected"), [
    ("Дата замовлення: | 28.11.2025 15:30\nПоказник\n", ("2025-11-28", None)),
    ("Результати\n11/08/2021 14:18 Nesamosn.: 6000000000\n01/03/1990 Контракт\n", ("2021-08-11", None)),
    ("Аналіз сечі загальний\nДата забору матеріалу: 16.03.2021\nПацієнт: Тестенко\n", ("2021-03-16", "2021-03-16")),
    ("Комп'ютерна рентгенографія досліджень № 209\nвід 31.01.2022\nП.І.Б. пацієнта: Тестенко\n", ("2022-01-31", None)),
    ("Комп'ютерна рентгенографія досліджень Ne 8792 ie\n| від 12.10.2026\n", ("2026-10-12", None)),
    ("Заключення: без змін.\nЛікар: Лікаренко О.П. Дата: 13.05.2023\n", ("2023-05-13", None)),
    ("TEST HOSPITAL TESTENKO OLENA\n2022-01-31 1990-03-01 F 31Y\n17:22:33\n", ("2022-01-31", None)),
    ("6. Попередній діагноз: F90.2\n17 липня 2026 року - підпис\n", ("2026-07-17", None)),
    ("Консультативне заключення\nДата візиту: 02.08.23\n", ("2023-08-02", None)),
    ("Діагноз кольпоскопічний:\nНормальна картина\nпідпис\nдата 18.08.2023\n", ("2023-08-18", None)),
])
def test_report_dates_as_printed(text, expected):
    # A partner clinic's order moment is the report's day, not the draw
    # (one smear was taken the day before it was ordered).
    result = classify(ocr=text, filename="file.pdf")
    assert (result.report_date, result.collected_at) == expected


def test_a_birth_date_or_the_forms_approval_date_is_never_the_report_date():
    assert classify("Дата народження: 01.03.1990\nвід 29.12.2000 р.\n", filename="file.pdf").report_date is None


def test_a_file_name_never_puts_the_patients_name_into_the_title():
    # Saved on a Mac: «ї» as «і» plus a combining diaeresis.
    stem = "Тестенко_Олена_Андрі\u0456\u0308вна_Панель_досліджень"
    result = classify(ocr="Результати досліджень\nКлієнт: Тестенко Олена Андріївна 3600000000\n", filename=f"{stem}.pdf")
    assert result.title == "Панель досліджень"


def test_xray_and_vessel_titles_come_from_the_page():
    xray = classify("РЕЗУЛЬТАТИ\nКомп'ютерна рентгенографія досліджень № 1\nвід 31.01.2022\n"
                    "П.І.Б. пацієнта: Тестенко\nЧастина тіла Грудна клітина\nОбласть Рентгенографія ОГК (одна проекція)\n"
                    "дослідження\nРезультат:\nЛегеневі поля прозорі.\n", filename="Інструментальне дослідження4.pdf")
    assert xray.title == "Рентгенографія ОГК (одна проекція)"
    vessels = classify("Протокол\nУльтразвукове обстеження гілок дуги\nвул. Тестова, 11\nвул. Друга, 64 А\nаорти\n"
                       "Тел: 097 00 00 000\nПІБ пацієнта: Тестенко\n", filename="vessels.pdf")
    assert vessels.title == "УЗД гілок дуги аорти"


def test_a_quoted_earlier_scan_is_not_an_ultrasound_title():
    text = "УЗД від 19.03.2025р.: лівий яєчник без змін\nОбстеження органів малого тазу\nВисновок: норма\n"
    assert not classify(text, filename="scan.pdf").title.startswith("УЗД від")


def test_screenshot_chrome_never_reaches_the_document():
    ocr = "22:39 2\n< Ви\n16.07.26\nКонсультація лікаря\nВисновок: норма\n3 із 8\n<4 Viber\n17:22:33\n"
    assert strip_screen_chrome(ocr).split() == ["Консультація", "лікаря", "Висновок:", "норма", "17:22:33"]


# --- vitals ------------------------------------------------------------------

def test_vitals_written_with_a_spaced_dash_are_read_and_a_bare_per_minute_after_hr_is_beats():
    read = {(item.raw_name, item.value_numeric, item.unit_raw) for item in parse_visit_measurements([page(NO_DIAGNOSIS)])}
    assert read == {
        ("ЧД", 16.0, "/хв"), ("SpO2", 98.0, "%"), ("ЧСС", 78.0, "уд/хв"),
        ("Систолічний артеріальний тиск", 95.0, "мм.рт.ст."), ("Діастолічний артеріальний тиск", 60.0, "мм.рт.ст."),
    }


def test_a_range_is_not_a_reading():
    assert parse_visit_measurements([page("ЧСС 60-90 уд/хв норма\n")]) == []


# --- findings ----------------------------------------------------------------

def _finding_rows(ledger, text, clinical_type="consultation", title="Консультація"):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "doc", clinical_type, title, [text], report_date="2024-11-14")
    return [row for row in findings(settings) if row["document_id"] == "doc"]


@pytest.mark.parametrize(("text", "summary"), [
    # Label after the value's first line, «Діагноз» read into the next one, a repeated line.
    (ALLERGIST, "основний: K52.9 Неінфекційний гастроентерит та коліт, неуточнений; "
                "синдром надмірного бактерійного росту. супутній: L20-L30 Дерматит та екзема"),
    ("Діагноз основний: G44.2 Головний біль, пов'язаний з перенапруженням\nДані лабораторних та\n",
     "G44.2 Головний біль, пов'язаний з перенапруженням"),
    (ENDOCRINE, "Реактивна гіпоглікемія"),
    ("Скарги відрижка\nпо МКХ-10 (Основний): -. Опис: Хронічний панкреатит.\nДані лабораторних та\n", "Хронічний панкреатит."),
])
def test_the_form_028_diagnosis_is_read_in_every_layout(text, summary):
    assert _extract_clinical_assessment(text, "consultation") == summary


def test_a_consultation_is_filed_by_its_diagnosis_never_by_its_history(ledger):  # noqa: F811
    rows = _finding_rows(ledger, ALLERGIST)
    assert {(row["health_area"], row["title"]) for row in rows} == {
        ("digestive", "Allergy consultation"), ("skin", "Allergy consultation")}
    row = rows[0]
    assert row["finding_date"] == "2024-11-14"
    assert row["recommendations"] == "1. здати харчову панель. 2. Ерус по 1 таб протягом 14 днів."
    assert "Лікаренко" not in row["original_text"] and "11111" not in row["original_text"]


def test_an_endocrine_note_quoting_a_thyroid_scan_is_filed_under_metabolism(ledger):  # noqa: F811
    rows = _finding_rows(ledger, ENDOCRINE)
    assert [(row["health_area"], row["title"], row["summary_uk"]) for row in rows] == [
        ("metabolism", "Endocrinology consultation", "Реактивна гіпоглікемія")]
    # The quoted study is held nowhere else: it stays in the stored text.
    assert "об'єм 10,9 см3" in rows[0]["original_text"]


def test_a_visit_with_no_diagnosis_entered_keeps_its_complaints_not_the_placeholder(ledger):  # noqa: F811
    [row] = _finding_rows(ledger, NO_DIAGNOSIS)
    assert (row["health_area"], row["title"]) == ("brain", "General practitioner consultation")
    assert row["summary_uk"] == "Скарги періодичний біль голови, тиск у скронях з обох боків."
    assert "Вкажіть" not in row["summary_uk"] + row["original_text"]
    assert row["recommendations"] == "1). ЗАК з формулою. 2). Консультація невропатолога."


def test_a_quoted_studys_conclusion_in_the_history_is_not_the_visits(ledger):  # noqa: F811
    text = ("КОНСУЛЬТАТИВНИЙ ВИСНОВОК\nПацієнт: Тестенко Олена\nСкарги утримуються.\n"
            "Анамнез хвороби Дихальний тест від 16.05.2026р: Висновок: Зафіксовано підвищення водню.\n"
            "Об'єктивний статус Живіт м'який.\nпо МКХ-10 (Основний): -. Опис: Дисбіоз кишківника.\n"
            "Дані лабораторних та\n")
    [row] = _finding_rows(ledger, text)
    assert row["summary_uk"] == "Дисбіоз кишківника."


def test_xray_reading_under_result_is_the_conclusion_and_the_dose_is_not_advice(ledger):  # noqa: F811
    text = ("Комп'ютерна рентгенографія досліджень № 1\nвід 31.01.2022\nП.І.Б. пацієнта: Тестенко\n"
            "Область Рентгенографія ОГК (одна проекція)\nдослідження\nРезультат:\n"
            "Легеневі поля прозорі. Синуси вільні.\nРекомендовано: консультація терапевта.\nЕД = 0.02 мЗв\n"
            "П.І.Б лікаря діагноста Лікаренко Ольга\nРентгенологічний висновок не є остаточним діагнозом\n")
    [row] = _finding_rows(ledger, text, "radiology_xray", "Рентгенографія ОГК")
    assert (row["health_area"], row["summary_uk"], row["recommendations"]) == (
        "lungs", "Легеневі поля прозорі. Синуси вільні.", "консультація терапевта.")


def test_a_report_with_nothing_read_files_no_empty_finding(ledger):  # noqa: F811
    urinalysis = "Аналіз сечі загальний\nКлітини ниркового епітелію не виявлені\nБілок не виявлений\n"
    assert _finding_rows(ledger, urinalysis, "clinical_report", "file") == []


def test_an_empty_template_heading_never_files_the_report(ledger):  # noqa: F811
    text = ("ПРОТОКОЛ УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ\nЩитовидна залоза:\nПечінка: не збільшена.\n"
            "Висновок: @test_medical_center Печінка без змін.\n")
    rows = _finding_rows(ledger, text, "ultrasound", "УЗД")
    assert "thyroid" not in {row["health_area"] for row in rows}
    assert all(row["summary_uk"] == "Печінка без змін." for row in rows)


def test_the_stored_text_ends_at_a_line_not_inside_the_consent_sentence():
    text = "Висновок: норма.\nРекомендовано: контроль\nПовторна консультація 14.02.2026\nСвоїм підписом підтверджую:\n"
    end = _report_body_end(text, _conclusion_span(text, "consultation"))
    assert text[:end].rstrip().endswith("Повторна консультація 14.02.2026")


def test_attention_words_are_not_read_inside_other_words():
    from anamna.health import finding_attention

    assert finding_attention("Аденоміоз тіла матки. Вузлова міома матки.") == []
