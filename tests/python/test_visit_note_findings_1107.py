"""eHealth visit notes and an EEG report, as findings.

Synthetic text in the shape of the primary-care vaccination notes and the EEG
conclusion that went wrong: advice printed above «Призначення» lost from the
recommendations, «Грипу» / «ВПЛ» glued into one diagnosis, a last «Опис: ВПЛ»
dropped as stamp debris, an EEG filed nowhere, and the dose quantity and site
cut from the stored text along with the vaccinating doctor's name.
"""
import html

import pytest
from fastapi.testclient import TestClient

from anamna.health import _clean_block, _extract_recommendations
from anamna.security import create_session
from anamna.web.app import create_app
from test_clinical_findings import add_report, findings, ledger  # noqa: F401

H = "‐"  # the eHealth generator's hyphen

PAGE_1 = (
    "Підрозділ:\nСпеціальність Педіатрія\nПаспортна частина\n"
    "ПІБ пацієнта: Тестенко Тарас Іванович Стать: Чоловіча\n"
    "Дата народження: 01.03.1990 Вік: 35 років\n"
    f"Скарги. Причина звернення: A98 {H} Підтримання здоров'я / профілактика\n"
    "Об’єктивний стан:\nЗагальний стан: задовільний. Температура: 36,6 ° C\n"
    "Діагноз:\nПідтримання здоров'я / профілактика*\nКод ICPC2\n"
    f"МКХ{H}10 Z27.9 {H} Необхідність імунізації\nпроти неуточнених комбінацій інфекційних\nхвороб\n"
    "Опис: Гепатиту А+В\nГрипу\nВПЛ\nПневмококової інфекції\n"
    "Вакцинації\n"
    f"Назва вакцини HPV {H} Вакцина для профілактики Виробник Тест Фарма\n"
    "інфекції, викликаної вірусом папіломи людини Серія вакцин TEST0001\n"
    "Дата та час вакцинації в системі 08.01.2026 9:54 Термін придатності 31.05.2027\n"
    "Лікар, який виконав вакцинацію Лікаренко Кількість введеної вакцини 0,5\n"
    f"Олена Петрівна ﴾Лікар{H}педіатр﴿ Одиниці вимірювання ML {H} мл\n"
    "Проведено Місце введення дельтоподібний м'яз ﴾ліва рука﴿\n"
)
PAGE_2 = (
    "Причина проведення вакцинації Щеплення за Шлях введення внутрішньом'язово\n"
    "станом здоров’я ﴾планово﴿\nПояснення проведення вакцинації\n"
    "№ дози Опис протоколу Автор протоколу Етап Кількість Хвороба\nдоз\n"
    f"2 Gardasil{H}9 Міністерство Охорони 2 3 ВПЛ\nЗдоров'я України\n"
    # The second dose prints its right column one line lower: the site sits
    # beside the doctor's name.
    f"Назва вакцини Pneumo_conj {H} Пневмококова Виробник Тест Фарма\n"
    "кон'югована вакцина Серія вакцин TEST0002\n"
    "Дата та час вакцинації в системі 08.01.2026 9:54 Кількість введеної вакцини 0,5\n"
    f"Лікар, який виконав вакцинацію Лікаренко Одиниці вимірювання ML {H} мл\n"
    f"Олена Петрівна ﴾Лікар{H}педіатр﴿ Місце введення дельтоподібний м'яз ﴾права рука﴿\n"
    "Проведено Шлях введення внутрішньом'язово\n"
    "№ дози Опис протоколу Автор протоколу Етап Кількість Хвороба\nдоз\n"
    "1 Vaxneuvance Міністерство Охорони 1 1 Пневмококова інфекція\nЗдоров'я України\n"
    "Після вакинації перебувати 30 хв в умовах медичного центру\n"
    f"При підвищенні температури тіла понад 38,5 приймати жарознижуючі Нурофен 400 мг {H} 1\n"
    "таб кожних 8 год\nабо\n"
    f"Парацетамол 500 мг {H} 1 таб кожних 6 год\n"
    f"Рекомендована вакцинація: Через 1 місяць {H} 2 Твінрикс\n"
    f"Через 6 місяців {H} 3 Гардасил 9\n"
    f"Кожні 10 років {H} Бустрикс ﴾дифтерія правець, кашлюк﴿\n"
    "Призначення\nПовторна консультація 14.02.2026\n"
    "Своїм підписом підтверджую:\n• згоду пацієнта на обстеження та лікування у медичному закладі;\n"
    "Лікар: ПІБ Олена Лікаренко\nПідпис _________ ﴾ПІБ﴿ ______\n"
)

ADVICE = (
    "Після вакинації перебувати 30 хв в умовах медичного центру; "
    "При підвищенні температури тіла понад 38,5 приймати жарознижуючі Нурофен 400 мг - 1 таб кожних 8 год "
    "або Парацетамол 500 мг - 1 таб кожних 6 год; "
    "Рекомендована вакцинація: Через 1 місяць - 2 Твінрикс; Через 6 місяців - 3 Гардасил 9; "
    "Кожні 10 років - Бустрикс (дифтерія правець, кашлюк)"
)


def _visit_note(ledger, pages=(PAGE_1, PAGE_2)):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "visit", "consultation", "Огляд лікаря первинка", list(pages), report_date="2026-01-08")
    return next(row for row in findings(settings) if row["document_id"] == "visit")


def test_advice_printed_above_the_plan_is_part_of_the_recommendations(ledger):  # noqa: F811
    row = _visit_note(ledger)
    assert row["recommendations"] == ADVICE + "; Повторна консультація 14.02.2026"


def test_a_plan_left_empty_still_keeps_the_recommended_schedule(ledger):  # noqa: F811
    page_2 = PAGE_2.replace("Призначення\nПовторна консультація 14.02.2026\n", "Призначення\n")
    assert _visit_note(ledger, (PAGE_1, page_2))["recommendations"] == ADVICE


def test_a_recommended_schedule_without_a_dose_given_is_kept_with_its_label():
    text = (
        "Діагноз:\nZ00.0 Загальний медичний огляд\n"
        f"Рекомендована вакцинація: Кожні 10 років {H} Бустрикс\nПризначення\nПовторна консультація 14.02.2026\n"
        "Своїм підписом підтверджую:\n"
    ).replace(H, "-")
    assert _extract_recommendations(text, text.index("Рекомендована")) == (
        "Рекомендована вакцинація: Кожні 10 років - Бустрикс; Повторна консультація 14.02.2026"
    )


def test_an_order_sheet_quantity_column_is_still_dropped():
    text = (
        "РЕКОМЕНДОВАНО:\nКонсультації спеціалістів та реабілітація\nНазва послуги К-сть Дата Ehealth\n"
        "Консультація кардіолога 1\nКонсультація гастроентеролога 1\nДо уваги пацієнта!\n"
    )
    assert _extract_recommendations(text) == "Консультація кардіолога; Консультація гастроентеролога"


def test_each_vaccine_target_is_its_own_diagnosis_item(ledger):  # noqa: F811
    row = _visit_note(ledger)
    assert row["summary_uk"] == (
        "Підтримання здоров'я / профілактика; Код ICPC2 МКХ-10 Z27.9 - Необхідність імунізації "
        "проти неуточнених комбінацій інфекційних хвороб; Опис: Гепатиту А+В; Грипу; ВПЛ; Пневмококової інфекції"
    )


def test_an_abbreviation_that_continues_a_line_is_not_a_new_item():
    assert _clean_block("Гіпертонічна хвороба Іст, КВР помірний\nСН 0\nE78.2 - Змішана гіперліпідемія") == (
        "Гіпертонічна хвороба Іст, КВР помірний СН 0; E78.2 - Змішана гіперліпідемія"
    )
    assert _clean_block("Опис: Гепатиту А+В\nВПЛ (6, 11, 16, 18)") == "Опис: Гепатиту А+В; ВПЛ (6, 11, 16, 18)"


def test_a_short_last_field_is_kept_and_stamp_debris_is_not():
    assert _clean_block("Z25.8 - Необхідність імунізації\nОпис: ВПЛ") == "Z25.8 - Необхідність імунізації; Опис: ВПЛ"
    assert _clean_block("Дифузні зміни паренхіми печінки.\ncoe ЄЖЕНОЮ\nRy") == "Дифузні зміни паренхіми печінки."


def test_the_stored_text_keeps_the_dose_column_beside_the_doctors_name(ledger):  # noqa: F811
    text = _visit_note(ledger)["original_text"]
    for kept in ("Кількість введеної вакцини 0,5", "Одиниці вимірювання ML - мл",
                 "Місце введення дельтоподібний м'яз (ліва рука)", "Місце введення дельтоподібний м'яз (права рука)"):
        assert kept in text
    for dropped in ("Лікаренко", "Олена Петрівна", "Лікар, який виконав", "Тестенко"):
        assert dropped not in text


EEG = (
    "Консультація лікаря\nВисновок ЕЕГ\nДата візиту: 17.11.2025\n"
    "Пацієнт: Тестенко Тарас Іванович Вік: 35 років Стать: Чоловіча\nДата народження: 01.03.1990\n"
    "Обстеження проводилось в стані пасивної бадьорості з закритими очима.\n"
    f"Домінує альфа{H}ритм із середньою частотою 10 Гц та амплітудою до 80 мкВ, симетрично.\n"
    f"Бета{H}ритм реєструється з середньою частотою 18 Гц та амплітудою до 15 мкВ.\n"
    "Висновок:\n"
    "Відмічаються незначно виражені дифузні зміни біоелектричної активності головного мозку.\n"
    "Потиличний домінантний ритм модульований, симетричний, реактивний.\n"
    "Висновок ЕЕГ не являється клінічним діагнозом і повинен бути інтерпретований лікуючим\n"
    "лікарем в контексті клінічних даних.\n"
    "Лікар: Олена Лікаренко\nМедична сестра-асистент: Тестова Н.Я.\n"
)


def test_an_eeg_report_is_filed_under_the_brain_with_its_own_conclusion(ledger):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "eeg", "consultation", "Огляд лікаря", [EEG], report_date="2025-11-17")
    [row] = [row for row in findings(settings) if row["document_id"] == "eeg"]
    assert (row["health_area"], row["title"], row["finding_date"]) == ("brain", "Electroencephalogram (EEG)", "2025-11-17")
    assert row["summary_uk"] == (
        "Відмічаються незначно виражені дифузні зміни біоелектричної активності головного мозку. "
        "Потиличний домінантний ритм модульований, симетричний, реактивний."
    )
    # The rhythm measurements stay in the report's own text; the doctor and
    # the patient do not.
    assert "10 Гц та амплітудою до 80 мкВ" in row["original_text"]
    assert "Лікаренко" not in row["original_text"] and "Тестенко" not in row["original_text"]


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_the_brain_area_page_shows_the_eeg_in_both_languages(ledger, locale):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "eeg", "consultation", "Огляд лікаря", [EEG], report_date="2025-11-17")
    findings(settings)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, owner)
    client.cookies.set("anamna_session", token)
    page = client.get(f"/areas/brain?lang={locale}")
    assert page.status_code == 200
    name = "Brain & nervous system" if locale == "en" else "Головний мозок і нервова система"
    title = "Electroencephalogram (EEG)" if locale == "en" else "Електроенцефалограма (ЕЕГ)"
    assert html.escape(name) in page.text and title in page.text
    assert "Відмічаються незначно виражені дифузні зміни" in page.text
