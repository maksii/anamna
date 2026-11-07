"""Round-2 value-by-value review (2026-11-07): the EskuLab and Synevo readers, concepts and units.

Every line is synthetic, shaped like the evidence the reviewers quoted: invented names,
orders and numbers, real column positions.  Nothing here identifies anyone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.health import display_unit
from anamna.i18n import activate_locale, reset_locale
from anamna.ingest.classifier import classify_document, extract_issued_at, extract_title
from anamna.ingest.concepts import stable_concept_id
from anamna.ingest.parsers import (
    ParsedObservation,
    ParseIssue,
    _antibiogram_material,
    method_note,
    parse_document,
    parse_microbiology_narrative,
    parse_unit_rows,
)
from anamna.ingest.pipeline import _inferred_category, ensure_concept, ensure_vendor, observation_specimen, seed_concepts
from anamna.ingest.text import normalized_key
from anamna.reference import canonical_unit

from test_parser_eskulab_review_1107 import page
from test_parser_lab_defects_1107 import layout


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def filed(connection, raw_name, *, vendor="EskuLab", value_type="text", clinical_type="laboratory", **row):
    concept_id, _unit = ensure_concept(
        connection, raw_name, ensure_vendor(connection, vendor, None), value_type=value_type,
        clinical_type=clinical_type, **row,
    )
    return concept_id


def concept(connection, concept_id):
    return connection.execute("SELECT canonical_name, category FROM concepts WHERE id=?", (concept_id,)).fetchone()


# --- EskuLab 1-3: the partner laboratory's coprogram ------------------------------------

PARTNER_COPROGRAM = [
    (245.0, "Показники@100.8-153.1 Результат@249.3-299.0 Од.@352.4-369.3 виміру@372.1-406.0 Реф.@451.1-474.9 значення@477.7-523.6"),
    (260.6, "30511@44.8-71.5 Копрограма@74.3-133.6"),
    (279.3, "Колір@44.8-67.3 коричневий@250.0-298.6 коричневий@462.6-511.2"),
    (291.3, "Реакція@44.8-76.3 (рН)@78.8-96.3 6,9@265.5-283.0 6,75-7,5@470.3-503.3"),
    (303.3, "Лейкоцити@44.8-89.1 поодинокі@228.1-269.3 в@271.8-276.6 препараті@279.1-319.5 кількість@349.6-384.8 "
            "в@387.3-392.1 п/з@397.1-408.6 поодинокі@455.7-496.9 у@499.4-503.8 п/з@506.3-517.8"),
    (315.3, "Еритроцити@44.8-91.5 не@250.2-261.7 виявлено@264.2-303.4 кількість@349.6-384.8 в@387.3-392.1 "
            "п/з@397.1-408.6 не@462.1-473.6 виявлено@476.1-515.3"),
    (327.3, "Яйця@44.8-70.5 глистів@73.0-108.7 не@250.2-261.7 виявлено@264.2-303.4 не@462.1-473.6 виявлено@476.1-515.3"),
    (696.9, "КОМЕНТАРІ:@44.8-105.9"),
]


def test_coprogram_names_stay_as_printed_and_the_per_field_unit_is_kept():
    """«Форма (кал)» was a label no report prints, and «кількість в п/з» was dropped on 20 rows."""
    parsed = {item.raw_name: item for item in parse_document("EskuLab", "laboratory", [page(PARTNER_COPROGRAM, 2)])}
    assert set(parsed) == {"Колір", "Реакція (рН)", "Лейкоцити", "Еритроцити", "Яйця глистів"}
    assert {item.specimen for item in parsed.values()} == {"кал"}
    assert (parsed["Лейкоцити"].value_text, parsed["Лейкоцити"].unit_raw) == ("поодинокі в препараті", "кількість в п/з")
    assert (parsed["Еритроцити"].value_text, parsed["Еритроцити"].unit_raw) == ("не виявлено", "кількість в п/з")
    # A word result printed without a unit still carries none.
    assert parsed["Яйця глистів"].unit_raw is None
    # The per-field unit is the same quantity as «в п/з» and is shown as it.
    assert canonical_unit("кількість в п/з") == canonical_unit("в п/з")


@pytest.mark.parametrize(
    "raw_name, value_type, expected",
    [
        ("Реакція (рН)", "numeric", "Stool pH"),
        ("Яйця глистів", "text", "Stool helminth eggs"),
        ("Епітеліальні клітини", "text", "Stool epithelium"),
        ("Клітковина перетравна", "text", "Stool plant fibre, digested"),
        ("Клітковина неперетравна", "text", "Stool plant fibre, undigested"),
        ("М'язові волокна незмінені", "text", "Stool muscle fibres, unaltered"),
        ("М'язові волокна слабкозмінені", "text", "Stool muscle fibres, slightly altered"),
        ("Краплі нейтрального жиру", "text", "Stool neutral fat"),
        ("Кристали жирних кислот", "text", "Stool fatty acids"),
        ("Крохмаль внутрішньоклітинний", "text", "Stool starch, intracellular"),
        ("Домішки", "text", "Stool undigested food residue"),
        ("Колір", "text", "Stool colour"),
    ],
)
def test_the_partner_coprograms_wording_reaches_the_stool_concepts(connection, raw_name, value_type, expected):
    assert filed(connection, raw_name, value_type=value_type, specimen="кал") == stable_concept_id(expected)


def test_urine_turbidity_is_the_urine_appearance(connection):
    assert filed(connection, "Каламутність(рівень) (C-CLOUD)", specimen="сеча", value_text="-") == (
        stable_concept_id("Urine appearance")
    )


def test_an_unknown_stool_row_is_a_stool_concept_of_its_own(connection):
    """Without the « (кал)» in the name, «Солі» from a coprogram must still not be urine's «Солі»."""
    stool = filed(connection, "Солі", specimen="кал", value_text="не виявлено")
    urine = filed(connection, "Солі", specimen="сеча", value_text="не виявлено", context="Аналіз сечі загальний")
    assert stool != urine
    assert tuple(concept(connection, stool)) == ("Солі (кал)", "stool")
    assert concept(connection, urine)["category"] == "urinalysis"


# --- EskuLab 4: an antibiogram continued on a page of its own ---------------------------

def test_an_antibiogram_page_is_typed_as_the_culture_it_continues():
    """Typed «laboratory», page 2 was read as a report of its own and lost the stool specimen."""
    continued = classify_document(
        "eskulab-10000001.pdf", "application/pdf",
        [{"page_number": 2, "native_text": "Замовлення: 10000001 / 01.01.2026 10:00\n"
          "Антибіотики/Антимікотики Staphylococcus epidermidis\nКліндаміцин 2 мкг Чутливий\n"}], {},
    )
    assert continued.clinical_type == "microbiology"


def antibiotic(name, organism, specimen, page_number):
    return ParsedObservation(
        raw_name=name, value_numeric=None, value_text="Стійкий", comparator=None, unit_raw=None,
        reference_text=None, reference_low=None, reference_high=None, page_number=page_number,
        evidence_text=f"{name} Стійкий", confidence=0.95, specimen=specimen, note=organism, section=organism,
    )


def test_a_continued_antibiogram_takes_the_material_of_the_nearest_one_above():
    """One order can test the same organism from urine and from stool."""
    rows = _antibiogram_material([
        antibiotic("Амікацин", "Escherichia coli", "сеча", 1),
        antibiotic("Меропенем", "Escherichia coli", None, 2),
        antibiotic("Амікацин", "Escherichia coli", "кал", 3),
        antibiotic("Меропенем", "Escherichia coli", None, 4),
        antibiotic("Цефепім", "Klebsiella pneumoniae", None, 4),
    ])
    assert [(item.page_number, item.note, item.specimen) for item in rows] == [
        (1, "Escherichia coli", "сеча"),
        (2, "Escherichia coli", "сеча"),
        (3, "Escherichia coli", "кал"),
        (4, "Escherichia coli", "кал"),
        (4, "Klebsiella pneumoniae", None),
    ]


# --- EskuLab 5 and Synevo 11: the specimen keeps auto concepts apart --------------------

def test_urine_and_stool_counts_of_one_organism_are_two_series(connection):
    urine = filed(connection, "Lactobacillus spp.", value_type="numeric", clinical_type="microbiology",
                  unit_raw="КУО/мл", specimen="сеча")
    stool = filed(connection, "Lactobacillus spp.", value_type="numeric", clinical_type="microbiology",
                  unit_raw="КУО/г", specimen="кал")
    assert urine != stool
    assert concept(connection, stool)["canonical_name"] == "Lactobacillus spp. (кал)"


def test_smear_readings_are_kept_apart_by_site_and_from_urine(connection):
    urine = filed(connection, "Trichomonas vaginalis", clinical_type="microbiology", specimen="сеча",
                  value_text="Не виявлено")
    vagina = filed(connection, "Trichomonas vaginalis", vendor="Synevo", specimen="VAGINA", value_text="не виявлена")
    cervix = filed(connection, "Trichomonas vaginalis", vendor="Synevo", specimen="CERVIX", value_text="не виявлена")
    assert len({urine, vagina, cervix}) == 3
    # A smear's «Епітелій» is no urinalysis row, even with a urine concept of that name in the record.
    filed(connection, "Епітелій", vendor="Synevo", context="Аналіз сечі загальний", value_text="поодинокий")
    smear = filed(connection, "Епітелій", vendor="Synevo", specimen="VAGINA", value_text="в помірній кількості")
    assert tuple(concept(connection, smear)) == ("Епітелій (VAGINA)", "microbiology")


# --- EskuLab 6: a wrapped heading is no antibiotic --------------------------------------

EXPRESS = [
    (130.0, "(матеріал:@28.3-89.0 Приносний@92.5-155.6 матеріал,@159.1-215.0 сеча)@218.5-249.3"),
    (140.0, "Дослідження:@28.3-90.0 Мікробіологічна@92.0-170.0 експрес-діагностика@172.0-260.0 гострих@262.0-300.0 "
            "урогенітальних@302.0-370.0 інфекцій@372.0-410.0 із@412.0-420.0 визначенням@422.0-480.0 чутливостей@482.0-540.0"),
    (150.0, "до@28.3-40.0 антибіотиків@42.0-100.0"),
    (160.0, "Мікробіологічна@28.3-110.0 експрес-діагностика@112.0-200.0 гострих@202.0-240.0 урогенітальних@242.0-310.0 "
            "інфекцій@312.0-350.0 із@352.0-360.0 визначенням@362.0-420.0 чутливостей@422.0-480.0"),
    (175.0, "Результат@351.7-405.1"),
    (185.0, "Мікроорганізми:@28.3-96.9 Candida@189.9-230.9 spp.@234.1-255.2 Не@483.2-494.5 виявлено@497.1-537.6"),
]


def test_a_heading_that_wraps_after_its_noun_is_not_sent_to_review():
    issues: list[ParseIssue] = []
    parsed = parse_document("EskuLab", "microbiology", [page(EXPRESS)], issues=issues)
    assert [(item.raw_name, item.value_text) for item in parsed] == [("Candida spp.", "Не виявлено")]
    assert issues == []


def test_every_verdict_form_is_still_a_verdict():
    lines = [
        (224.8, "Мікроорганізм@28.3-112.8 Результат@243.8-302.2 Референтні@378.4-446.2 значення@449.6-503.0"),
        (236.0, "Антибіотики/Антимікотики@28.3-182.5 Escherichia@243.8-300.0 coli@303.0-320.0"),
        (248.0, "Амікацин@28.3-80.0 Чутливий@384.8-425.9"),
        (260.0, "Меропенем@28.3-88.5 Стійка@384.8-420.0"),
        (272.0, "Ципрофлоксацин@28.3-100.0 Чутливий,@384.8-430.0 збільшена@432.0-480.0 експозиція@482.0-540.0"),
        (284.0, "Цефепім@28.3-70.0 резистентний@384.8-440.0"),
    ]
    parsed = {item.raw_name: item.value_text for item in parse_document("EskuLab", "microbiology", [page(lines)])}
    assert parsed == {
        "Амікацин": "Чутливий", "Меропенем": "Стійка", "Ципрофлоксацин": "Чутливий, збільшена експозиція",
        "Цефепім": "резистентний",
    }


# --- EskuLab 7: the POLYCHECK print date ------------------------------------------------

def test_the_polycheck_print_date_is_the_issue_date():
    text = "Тестова Харчовa 20-I\nОльга Іванівна /\n01.01.1990 03.02.2025\n03.02.2025 (V. 6.01.21 )\n"
    assert extract_issued_at(text) == "2025-02-03"


# --- EskuLab 8: urea in the title is not urine ------------------------------------------

AMINO_TITLE = "Амінокислоти (скринінг 39 показників в сироватці) · Сечовина"


def test_urea_in_the_title_files_nothing_as_urinalysis():
    assert _inferred_category(normalized_key("Аланін"), "laboratory", AMINO_TITLE) == "unmapped"
    assert _inferred_category(normalized_key("Аланін"), "laboratory", AMINO_TITLE, "hematology") == "unmapped"
    assert _inferred_category(normalized_key("Сечова кислота"), "laboratory", None) == "unmapped"
    # Urine itself still is, by the row or by the title.
    assert _inferred_category(normalized_key("Солі"), "laboratory", "Аналіз сечі загальний") == "urinalysis"
    assert _inferred_category(normalized_key("Клітини у сечі"), "laboratory", None) == "urinalysis"
    assert _inferred_category(normalized_key("Солі"), "laboratory", None, "urinalysis") == "urinalysis"
    # The row's own specimen outranks the title.
    assert _inferred_category(normalized_key("Солі"), "laboratory", "Аналіз сечі загальний", "hematology") == "unmapped"


def test_an_auto_concept_filed_as_urinalysis_by_the_old_rule_moves_back(connection):
    connection.execute(
        "INSERT INTO concepts(id, canonical_name, category, value_type, created_at) "
        "VALUES ('old-alanine', 'Аланін', 'urinalysis', 'numeric', '2026-01-01')"
    )
    assert filed(connection, "Аланін", value_type="numeric", unit_raw="мкмоль/л", specimen="сироватка крові",
                 context=AMINO_TITLE) == "old-alanine"
    assert concept(connection, "old-alanine")["category"] == "unmapped"
    # Urea itself stays the catalogue's blood chemistry concept.
    urea = filed(connection, "Сечовина", value_type="numeric", unit_raw="ммоль/л", context=AMINO_TITLE)
    assert concept(connection, urea)["category"] != "urinalysis"


# --- Synevo ------------------------------------------------------------------------------

SYNEVO_HEADER = (135.6, "Показник@124.1 Результат@274.6 Од.@357.7 Референтний@442.2 інтервал@491")
SYNEVO_FOOTER = (781.5, "Результати@62.1 лабораторних@92.4 досліджень@129.3 не@159.5 є@167 достатньою@171.3")


def synevo(lines):
    return parse_document("Synevo", "laboratory", [layout([SYNEVO_HEADER, *lines, SYNEVO_FOOTER])])


def test_a_wrapped_test_heading_is_never_a_result():
    """The «з» of «... автоматизований з» sat in the result column, the flag column's header beside it."""
    rows = synevo([
        (150.0, "Загальний@62 аналіз@100 крові@125 (Тестовий@150 аналіз@185 автоматизований@205 з@262 "
                "Індикатор@391.6 зони@430 підвищеної@452 уваги@497"),
        (161.0, "формулою@62 +@96 ручна@104 лейкоформула)@128"),
        (175.0, "Гемоглобін@62 (HGB)@105 131@280 г/л@360 120.0@391.6 -@415 140.0@421"),
    ])
    assert [(row.raw_name, row.value_numeric) for row in rows] == [("Гемоглобін (HGB)", 131.0)]


PARASEP = [
    (150.0, "Загальна@62 клініка@100 Індикатор@391.6 зони@430 підвищеної@452 уваги@497"),
    (161.0, "Аналіз@62 калу@92 на@113 кишкові@125 паразити@157 (метод@193"),
    (172.0, "концентрування@62 Parasep)@123"),
    (183.0, "Яйця@62 гельмінтів@83 не@262 виявлені@274 не@391.6 виявлені@403"),
    (194.0, "Копрограма@62"),
    (205.0, "Яйця@62 гельмінтів@83 не@262 виявлені@274 не@391.6 виявлені@403"),
]


def test_a_concentration_method_keeps_its_name_beside_the_coprogram_row(connection):
    rows = {row.raw_name: row for row in synevo(PARASEP)}
    assert set(rows) == {"Яйця гельмінтів (Parasep)", "Яйця гельмінтів"}
    assert {observation_specimen(row) for row in rows.values()} == {"кал"}
    # Both still answer the same question: helminth eggs in the stool.
    for row in rows.values():
        assert filed(connection, row.raw_name, vendor="Synevo", specimen=observation_specimen(row)) == (
            stable_concept_id("Stool helminth eggs")
        )


def test_a_scale_explanation_is_the_reference_of_both_rows_it_explains():
    """The rank kept its bracket and the percentage lost its own to the «визначення» in it."""
    assert not method_note("Автоматизована система використовує алгоритми для визначення відповідного рангу")
    assert method_note("Гідродинамічне фокусування з імпедансним методом (метод прямого визначення)")


PARTNER_HPV = [
    (150.0, "ПЛР@62 Київ@80 Індикатор@391.6 зони@430 підвищеної@452 уваги@497"),
    (161.0, "ПЛР.@62 ВПЛ@80 ВКР@97 (генотипування@115 16,@175 18,@190"),
    (172.0, "33,@62 35,@75 у/г@88"),
    (183.0, "зішкріб,@62 кількісне@95 визначення)@135"),
    (194.0, "16@62 генотип@72 не@262 виявлено@274 <3@391.6 LgВПЛ/10^5@402 клітин:@445 клінічно@474 малозначуще@505"),
    (205.0, "3@391.6 Lg@397 -@406 5@411 Lg@416 ВПЛ/10^5@425 клітин:@457 клінічно@486 значуще@517"),
    (216.0, ">5@391.6 LgВПЛ/10^5@402 клітин:@445 клін.@474 високозначуще@493"),
    (227.0, "Метод:@391.6 Real-Time@417 PCR@452"),
    (238.0, "Аналізатор:@391.6 CFX-96@432 (BioRad,@458 США)@489"),
    (249.0, "18@62 генотип@72 не@262 виявлено@274 <3@391.6 LgВПЛ/10^5@402 клітин:@445 клінічно@474 малозначуще@505"),
    (260.0, "3@391.6 Lg@397 -@406 5@411 Lg@416 ВПЛ/10^5@425 клітин:@457 клінічно@486 значуще@517"),
]


def test_a_synevo_report_printed_for_a_partner_clinic_is_read_as_synevo():
    """No «Сінево (Synevo)» line: the vendor was Unknown and the generic reader glued lines together."""
    text = "\n".join(
        ["Результати досліджень", "Показник Результат Од. Референтний інтервал"]
        + [" ".join(item.rpartition("@")[0] for item in row.split()) for _, row in PARTNER_HPV]
    )
    found = classify_document("main-offline.pdf", "application/pdf", [{"page_number": 1, "native_text": text}], {})
    assert found.vendor == "Synevo"
    assert found.title == "ПЛР. ВПЛ ВКР (генотипування 16, 18, 33, 35, у/г зішкріб, кількісне визначення)"
    # The screenshot print of the same lab names its information system instead.
    shot = "Мікробіологія\nОбробка матеріалу виконується за допомогою лабораторної Інформаційної системи SILAB,\n"
    assert classify_document("file.pdf", "application/pdf", [{"page_number": 1, "ocr_text": shot}], {}).vendor == "Synevo"
    rows = {row.raw_name: row for row in synevo(PARTNER_HPV)}
    # «heading, name», the name the lab's own record gives these rows too.
    assert set(rows) == {"ПЛР. ВПЛ ВКР, 16 генотип", "ПЛР. ВПЛ ВКР, 18 генотип"}
    assert rows["ПЛР. ВПЛ ВКР, 16 генотип"].reference_text == (
        "<3 LgВПЛ/10^5 клітин: клінічно малозначуще 3 Lg - 5 Lg ВПЛ/10^5 клітин: клінічно значуще "
        ">5 LgВПЛ/10^5 клітин: клін. високозначуще"
    )


def test_colonies_per_millilitre_are_a_unit_of_their_own():
    """«КУО/мл» was not allowed, so a urogenital culture's count was dropped."""
    found = parse_microbiology_narrative("Gardnerella vaginalis 10^5 КУО/мл\nLactobacillus spp. 10^6 КУО/г\n", 1)
    assert [(row.raw_name, row.value_numeric, row.unit_raw) for row in found] == [
        ("Gardnerella vaginalis", 1e5, "КУО/мл"), ("Lactobacillus spp.", 1e6, "КУО/г"),
    ]
    assert canonical_unit("КУО/мл") != canonical_unit("КУО/г")
    token = activate_locale("en")
    try:
        assert display_unit("КУО/мл") == "CFU/mL"
    finally:
        reset_locale(token)
    token = activate_locale("uk")
    try:
        assert display_unit("КУО/мл") == "КУО/мл"
    finally:
        reset_locale(token)


SYNEVO_HEAD = (
    "Результати досліджень Сінево (Synevo)\nДата замовлення: 01.02.2017 08:00 Оформлено: у відділенні\n"
    "Показник Результат Од. Референтний інтервал\n"
)


def test_titles_name_the_tests_the_paper_holds():
    hcg = SYNEVO_HEAD + (
        "Імунохімія Індикатор зони підвищеної уваги\n"
        "β-ХГЛ загальний (хоріонічний < 0.1 мМО/мл Невагітні жінки: ≤1.0\n"
        "гонадотропін загальний) Невагітні жінки (постменопауза): ≤7.0\n"
    )
    assert extract_title(hcg, "main-offline.pdf", "laboratory") == "β-ХГЛ загальний (хоріонічний гонадотропін загальний)"
    rows = parse_unit_rows(hcg, 1)
    assert [(row.raw_name, row.comparator, row.value_numeric, row.unit_raw) for row in rows] == [
        ("β-ХГЛ загальний (хоріонічний гонадотропін загальний)", "<", 0.1, "мМО/мл")
    ]
    both = SYNEVO_HEAD + (
        "Загальний аналіз крові (Тестовий аналіз крові з Індикатор зони підвищеної уваги\n"
        "формулою)\n"
        "Гемоглобін (HGB) 131 г/л 120.0 - 140.0\n"
        "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)\n"
        "Аналіз сечі загальний\n"
        "Колір жовтий жовтий\n"
    )
    assert extract_title(both, "main-offline.pdf", "laboratory") == (
        "Загальний аналіз крові (Тестовий аналіз крові з формулою) · Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"
    )
    culture = (
        "Мікробіологія\nБакпосів на мікрофлору (урогенітальний) + антибіотикограма (у разі виявлення\n"
        "умовно-патогенної та патогенної мікрофлори)\nМікроорганізм кількість\n"
    )
    assert extract_title(culture, "file.pdf", "microbiology") == (
        "Бакпосів на мікрофлору (урогенітальний) + антибіотикограма (у разі виявлення умовно-патогенної та "
        "патогенної мікрофлори)"
    )
