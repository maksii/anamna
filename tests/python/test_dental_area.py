"""Teeth & mouth as a health area.

Synthetic text in the shape of Expert Hospital's therapist visit that the
validator flagged: no diagnosis written, an examination that names no organ
(«підщелепний лімфовузол» is a neck node, not the jaw), complaints of jaw pain
and a referral to a dentist.  It was filed nowhere, so it never reached a
health area at all.
"""
import html

import pytest
from fastapi.testclient import TestClient

from anamna.health import _diagnosis_areas, finding_attention
from anamna.security import create_session
from anamna.web.app import create_app
from test_clinical_findings import add_report, findings, ledger  # noqa: F401

GP_VISIT = (
    "Консультація терапевта\nЛікарня «Експерт» · Expert Hospital\nДата: 01.01.2024\n"
    "Лікар: Лікаренко Олег (Терапевт)\n"
    "Скарги:\nна біль в ділянці нижньої щелепи справа\n"
    "Анамнез:\nскарги появились 2 дні назад. Туберкульоз, вірусний гепатит заперечує.\n"
    "Огляд:\nЗагальний стан: задовільний\nЗів - нормальний, рожевий, не гіперемований\n"
    "Мигдалики не збільшені, підщелепний лімфовузол злегка збільшений справа.\nТемпература тіла 37*С\n"
    "Рекомендації:\n1. Консультація стоматолога\n"
)


def test_a_gp_visit_without_a_diagnosis_is_filed_by_its_complaints(ledger):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "gp", "consultation", "Консультація терапевта", [GP_VISIT],
               report_date="2024-01-01")
    [row] = [row for row in findings(settings) if row["document_id"] == "gp"]
    assert (row["health_area"], row["title"], row["finding_date"]) == (
        "dental", "General practitioner consultation", "2024-01-01")
    assert "Консультація стоматолога" in row["recommendations"]


def test_a_gp_visit_with_a_diagnosis_is_still_filed_by_the_diagnosis(ledger):  # noqa: F811
    settings, owner, patient = ledger
    diagnosed = GP_VISIT.replace("Рекомендації:", "Діагноз:\nJ20.9 Гострий бронхіт\nРекомендації:")
    add_report(settings, owner, patient, "gp", "consultation", "Консультація терапевта", [diagnosed])
    assert [row["health_area"] for row in findings(settings) if row["document_id"] == "gp"] == ["lungs"]


def test_the_jaw_teeth_and_their_icd_block_name_the_area_and_a_neck_node_does_not():
    assert _diagnosis_areas("біль в ділянці нижньої щелепи") == ("dental",)
    assert _diagnosis_areas("Хронічний пародонтит") == ("dental",)
    assert _diagnosis_areas("K02.1 Карієс дентину") == ("dental",)
    # A neck node, in every general examination and neck ultrasound.
    assert _diagnosis_areas("підщелепний лімфовузол злегка збільшений") == ()
    # K00-K14 is the mouth, salivary glands and jaws: a salivary gland stays
    # with ENT, the rest of chapter K with the digestive tract.
    assert _diagnosis_areas("K11.2 Сіалоаденіт") == ("ent",)
    assert _diagnosis_areas("K29.5 Хронічний гастрит") == ("digestive",)


def test_a_neck_node_or_a_haemorrhoid_is_no_thyroid_nodule_outside_the_thyroid():
    swollen = "Мигдалики не зібльшені, підщелепний лімфовузол злегка збільшений справа"
    assert finding_attention(swollen, ("dental",)) == ["lymph_inflammation"]
    assert finding_attention("Внутрішні гемороїдальні вузли незначно збільшені", ("digestive",)) == []
    # A node is the thyroid's in a thyroid report, or where the clause names the gland.
    assert finding_attention("Вузол правої частки 8 мм, TI-RADS 3", ("thyroid",)) == ["thyroid_nodule"]
    assert finding_attention("Вузол щитоподібної залози 8 мм", ("heart",)) == ["thyroid_nodule"]
    assert finding_attention("Шийні лімфовузли не збільшені", ("ent",)) == []


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_the_teeth_area_page_explains_itself_in_both_languages(ledger, locale):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "gp", "consultation", "Консультація терапевта", [GP_VISIT],
               report_date="2024-01-01")
    findings(settings)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, owner)
    client.cookies.set("anamna_session", token)
    page = client.get(f"/areas/dental?lang={locale}")
    assert page.status_code == 200
    name, explained = (("Teeth & mouth", "referral to a dentist") if locale == "en"
                       else ("Зуби й ротова порожнина", "направляють до стоматолога"))
    assert html.escape(name) in page.text and explained in page.text
    assert "Мигдалики не збільшені" in page.text or "біль в ділянці нижньої щелепи" in page.text
