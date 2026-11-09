"""Form 027/о, the discharge summary Expert Hospital attaches to a stay as a
Word file: a report, titled as printed, dated the day the stay ended."""

from __future__ import annotations

from anamna.health import _diagnosis_areas
from anamna.ingest.classifier import classify_document

from test_classifier import pdf_page

FORM_027 = """Перетворено Anamna з файлу Word «Консультація 1748171.docx», виданого Лікарнею «Експерт». /
Converted by Anamna from the Word file «Консультація 1748171.docx» Expert Hospital issued.
МОЗ України
МЕДИЧНА ДОКУМЕНТАЦІЯ
Форма первинної облікової документації
№ 027/о
МЦ ТОВ "Лікарня ЕКСПЕРТ"
ВИПИСКА
із медичної карти амбулаторного (стаціонарного) хворого № 1332
У поліклініку за місцем проживання
1. Прізвище, ім’я, по батькові хворого
Тест Тест Тестович
5. Дати: а) в амбулаторно-поліклінічному закладі:
захворювання
(число, місяць, рік)
б) у стаціонарі: надходження
18.09.2025
(число, місяць, рік)
виписки або смерті (підкреслити)
19.09.2025
(число, місяць, рік)
6. Повний діагноз (основне захворювання, супутні захворювання та ускладнення):
Діагноз: Викривлена носова перегородка з частковим порушенням носового
дихання
8. Лікувальні і трудові рекомендації:
3. Ванночки з відваром кори дуба 2 рази на добу при відчутті печіння
"""


def test_a_form_027_discharge_is_a_report_titled_and_dated_as_printed():
    found = classify_document("expert-c5777099-1.pdf", "application/pdf", [pdf_page(FORM_027)])
    assert found.clinical_type == "clinical_report"
    assert found.title == "Виписка із медичної карти хворого (форма 027/о)"
    # The day the stay ended, not the admission day above it.
    assert found.report_date == "2025-09-19"


def test_burning_is_not_the_liver():
    assert "liver" not in _diagnosis_areas("Ванночки при відчутті печіння")
    assert "liver" not in _diagnosis_areas("Печіння в ділянці рани")
    assert _diagnosis_areas("Жирова дистрофія печінки") == ("liver",)


def test_the_discharge_diagnosis_ends_where_the_history_begins():
    from anamna.health import _extract_clinical_assessment

    text = FORM_027.replace(
        "8. Лікувальні",
        "7. Короткий анамнез, діагностичні дослідження, перебіг хвороби, проведене\n"
        "лікування: Пацієнт госпіталізований для оперативного втручання.\n8. Лікувальні")
    assessment = _extract_clinical_assessment(text, "clinical_report")
    assert assessment.startswith("Викривлена носова перегородка") and "анамнез" not in assessment


def test_a_two_page_discharge_is_one_report_dated_from_either_page():
    from anamna.ingest.pipeline import page_classifications

    first, second = FORM_027.split("виписки або смерті")
    pages = [pdf_page(first), pdf_page("виписки або смерті" + second + "\nОгляд: стан задовільний")]
    found = page_classifications("expert-c5777099-1.pdf", "application/pdf", pages, {})
    assert {(item.clinical_type, item.title, item.report_date) for item in found} == {
        ("clinical_report", "Виписка із медичної карти хворого (форма 027/о)", "2025-09-19")}
