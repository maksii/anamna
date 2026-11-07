"""Second value-by-value review (2026-11-07): Synevo rows named by their headings, whole
reference blocks, and how a printed reference becomes bounds and a reading.

Word geometry is copied from real Synevo reports; only the result rows are kept, and no
line that names a person, an order or a barcode.  The lab-record rows are synthetic copies
of the shapes a lab's online record delivers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.health import applicable_reference_bounds
from anamna.ingest.parsers import ParsedObservation, parse_document, reference_limits
from anamna.ingest.pipeline import interpretation

from test_parser_lab_defects_1107 import layout

HEADER = (135.6, "Показник@124.1 Результат@274.6 Од.@357.7 Референтний@442.2 інтервал@491")
FOOTER = (781.5, "Результати@62.1 лабораторних@92.4 досліджень@129.3 не@159.5 є@167 достатньою@171.3")


def synevo(lines):
    return parse_document("Synevo", "laboratory", [layout([HEADER, *lines, FOOTER])])


def by_name(lines):
    return {row.raw_name: row for row in synevo(lines)}


# --- 1. A heading with no value names the rows under it -------------------------------


GENOTYPES = [
    (568.0, "ПЛР.@69 Фолатний@89.6 цикл.@130.6 MTR@153.4 (2756@172.5 A>G)@194.6"),
    (583.4, "В12-залежна@75 метіонін-синтаза@126.2 Мутація@259.9 відсутня@292.5 Відсутність@391.6 мутаціі@430.6 –@455.6 норма@461.6"),
    (594.8, "Гетерозиготне@391.6 носійство@441.7 –@475.4 ризик@481.3"),
    (605.3, "Гомозиготне@391.6 носійство@435.4 –@469.1 ризик@477"),
    (619.2, "ПЛР.@69 Фолатний@89.6 цикл.@130.6 MTHFR@153.4 (1298@182.9 A>C)@205"),
    (634.5, "Метілентетрагідрофолатредуктаза@75 Мутація@259.9 відсутня@292.5 Відсутність@391.6 мутаціі@430.6 –@455.6 норма@461.6"),
    (645.9, "Гетерозиготне@391.6 носійство@441.7 –@475.4 ризик@481.3"),
    (656.4, "Гомозиготне@391.6 носійство@435.4 –@469.1 ризик@477"),
    (670.3, "ПЛР.@69 Фолатний@89.6 цикл.@130.6 MTHFR@153.4 (677@182.9 C>T)@200.7"),
    (685.7, "Метілентетрагідрофолатредуктаза@75 Мутація@259.9 відсутня@292.5 Відсутність@391.6 мутаціі@430.6 –@455.6 норма@461.6"),
    (697.1, "Гетерозиготне@391.6 носійство@441.7 –@475.4 ризик@481.3"),
    (707.6, "Гомозиготне@391.6 носійство@435.4 –@469.1 ризик@477"),
    (721.5, "ПЛР.@69 Фолатний@89.6 цикл.@130.6 MTRR@153.4 (66@178.1 A>G)@191.6"),
    (736.8, "Метіонін-синтаза@75 редуктаза@141.4 Мутація@258.1 виявлена@290.7 Відсутність@391.6 мутаціі@430.6 –@455.6 норма@461.6"),
    (748.2, "Гетерозиготне@391.6 носійство@441.7 –@475.4 ризик@481.3"),
    (758.7, "Гомозиготне@391.6 носійство@435.4 –@469.1 ризик@477"),
]


def test_genotype_rows_carry_the_gene_and_variant_of_their_pcr_heading():
    """MTHFR 1298 A>C and 677 C>T were both stored as «Метілентетрагідрофолатредуктаза»,
    so two different genetic tests merged into one series; every row lost its gene."""
    rows = synevo(GENOTYPES)
    assert [row.raw_name for row in rows] == [
        "В12-залежна метіонін-синтаза (MTR 2756 A>G)",
        "Метілентетрагідрофолатредуктаза (MTHFR 1298 A>C)",
        "Метілентетрагідрофолатредуктаза (MTHFR 677 C>T)",
        "Метіонін-синтаза редуктаза (MTRR 66 A>G)",
    ]
    assert [row.value_text for row in rows] == ["Мутація відсутня"] * 3 + ["Мутація виявлена"]
    # The risk lines are part of the reference, not cut off at the first line without a number.
    assert {row.reference_text for row in rows} == {
        "Відсутність мутаціі – норма Гетерозиготне носійство – ризик Гомозиготне носійство – ризик"
    }


LUPUS = [
    (494.4, "Фібриноген@69 2.854@283.2 г/л@357.8 1.8@391.6 –@403.5 3.5@409.5"),
    (505.3, "Метод:@391.6 клоттінговий@416.9"),
    (561.2, "Вовчаковий@69 антикоагулянт@118.3"),
    (576.6, "Скринінговий@75 тест@127.2 37.9@285.4 сек@356.8 31.0@391.6 -@407.5 44.0@411.9"),
    (588.0, "Метод:@391.6 клоттінговий@416.9"),
    (598.5, "Реагенти:@391.6 Siemens@426.1 (Німеччина)@455.9"),
    (641.6, "Підтверджуючий@75 тест@140.2 34.3@285.4 сек@356.8 30.0@391.6 -@407.5 38.0@411.9"),
    (653.0, "Метод:@391.6 клоттінговий@416.9"),
    (706.6, "LA-AUTO@75 1.1@287.6 Індекс@351.7 0.8@391.6 -@403.5 1.2@407.9 -@419.8 відсутність@424.2 ризику@462.3"),
]


def test_a_screening_and_a_confirming_test_are_named_by_the_test_above_them():
    rows = by_name(LUPUS)
    assert rows["Вовчаковий антикоагулянт, скринінговий тест"].value_numeric == 37.9
    assert rows["Вовчаковий антикоагулянт, підтверджуючий тест"].value_numeric == 34.3
    # Rows that name themselves keep their own name.
    assert {"Фібриноген", "LA-AUTO"} <= set(rows)
    assert not {"Скринінговий тест", "Підтверджуючий тест"} & set(rows)


def test_the_cross_check_pairs_a_heading_named_row_with_the_labs_bare_name():
    lab = [{"test": name, "result": "Мутація відсутня", "units": "", "norm": [], "state": "normal",
            "resulttype": "string", "packet": ""} for name in ("Метілентетрагідрофолатредуктаза",) * 2]
    observations = [
        {"id": f"o{index}", "raw_name": name, "value_numeric": None, "value_text": "Мутація відсутня",
         "unit_raw": None, "comparator": None, "vendor_reference_text": None, "vendor_reference_low": None,
         "vendor_reference_high": None, "vendor_interpretation": None, "vendor_interpretation_source": None,
         "concept_id": None, "document_id": "d", "page_number": 2, "unit_canonical": None,
         "verification_status": "extracted"}
        for index, name in enumerate(("Метілентетрагідрофолатредуктаза (MTHFR 1298 A>C)",
                                      "Метілентетрагідрофолатредуктаза (MTHFR 677 C>T)"))
    ]
    result = labsync.cross_check(lab, observations)
    assert [item["cls"] for item in result["items"]] == ["match", "match"]
    assert [item["obs"]["id"] for item in result["items"]] == ["o0", "o1"]  # in page order


# --- 2. Rows that are not results ---------------------------------------------------


PAGE_ONE = [
    (148.9, "Пакет@62.4 №183@86.5 (CHECK-UP.@110.4 Все@158.5 під@175 контролем@189 для@232.9 жінок@249.6 +@272.8 "
            "звіт@279.5 з@296.4 описом@302.4 Індикатор@462.2 зони@492.3 підвищеної@507.3 уваги@541.6"),
    (160.1, "лабораторних@62.4 показників)@119.7"),
    (175.2, "Аналіз@69 крові:@96.8 Швидкість@122 осідання@165.6 4@290.9 мм/год.@349.9 Нормативні@391.6 значення@432.2 "
            "(метод@464.9 Вестергрена):@489.5"),
    (186.4, "еритроцитів@69 (ШОЕ,@118.8 ESR)@144.8 Діти@391.6 до@407.3 17@417.4 років:@427.4 до@447.8 10.0@457.9"),
    (195.9, "Чоловіки@391.6 (17@423 -@435.3 50@439.7 років):@449.6 до@472.4 15.0@482.6"),
    (237.9, "Виконано@391.6 на@425.3 аналізаторі@435.2 Alifax@474.9 Test-1@494.4"),
    (251.8, "Аналіз@69 крові@96.8 розгорнутий@119.4 (ЗАК)@170.2"),
    (363.7, "Лейкоцити@75 (WBC)@117.1 6.35@285.4 10^9@354.4 Діти:@391.6 <1@409.3 року:@419.4 6.5@438 -@450 12.5@454.3"),
    (375.1, "клітин/л@349 1-3@391.6 роки:@403.9 5.0@423 -@434.9 12.0@439.3"),
    (385.6, "Дорослі:@391.6 4.0@421.7 -@433.6 9.0@438"),
    (399.0, "Еритроцити@75 (RBC)@117.1 5.11@285.4 10^12@352.4 Діти:@391.6 <1@409.3 року:@419.4 3.3@438 -@450 4.9@454.3"),
    (410.4, "клітин/л@349 Дорослі:@391.6 3.7@421.7 -@433.6 4.7@438"),
    (421.0, "Гідродинамічне@391.6 фокусування@445 з@490 імпедансним@497"),
]


def test_a_package_heading_is_not_a_result_and_the_specimen_label_leaves_the_name():
    rows = by_name(PAGE_ONE)
    assert not [name for name in rows if name.startswith("Пакет")]
    esr = rows["Швидкість осідання еритроцитів (ШОЕ, ESR)"]
    assert esr.value_numeric == 4.0 and esr.unit_raw == "мм/год."


def test_a_count_unit_wrapped_onto_the_next_line_is_joined_and_still_folds():
    from anamna.reference import canonical_unit

    rows = by_name(PAGE_ONE)
    assert rows["Лейкоцити (WBC)"].unit_raw == "10^9 клітин/л"
    assert rows["Еритроцити (RBC)"].unit_raw == "10^12 клітин/л"
    # Same measurement as the bare «10^12»: the trend must not split.
    assert canonical_unit("10^12 клітин/л") == canonical_unit("10^12")
    assert canonical_unit("10^9 клітин/л") == canonical_unit("10^9")
    # A method note under the bands is not part of the reference.
    assert "фокусування" not in rows["Еритроцити (RBC)"].reference_text


COPROGRAM_CELL = [
    (663.0, "Лейкоцити@75 (копрограма)@117 не@252 виявлені@262 (в@293 нормі@301 -@322 не@326 виявлені)@336"),
]


def test_a_normal_printed_inside_the_result_cell_is_the_rows_reference():
    """Round-2 review: the bracket is where the coprogram prints this row's norm."""
    row = by_name(COPROGRAM_CELL)["Лейкоцити (копрограма)"]
    assert (row.value_text, row.reference_text) == ("не виявлені", "в нормі - не виявлені")


# --- 3. A reference block runs past prose, footnotes and citations --------------------


HOMOCYSTEINE = [
    (371.4, "Гомоцистеїн@69 7.7@287.6 мкмоль/л@346.7 Діти@391.6 <15@407.3 років:@421.4 <10.0@441.8"),
    (382.3, "Дорослі:@391.6"),
    (392.8, "15-65@391.6 років:@411.9 <15.0@432.3"),
    (403.3, ">65@391.6 років:@405.7 <20.0@426.2"),
    (413.8, "Вагітні@391.6 жінки:@415.3 <10.0@436.8"),
    (424.3, "Для@391.6 людей@406.5 з@430.1 додатковим@435.4 споживанням@476.8"),
    (434.8, "фолатів:@391.6"),
    (445.3, "Діти@391.6 <15@407.3 років:@421.4 <8.0@441.8"),
    (455.8, "Дорослі:@391.6"),
    (466.3, "15-65@391.6 років:@411.9 <12.0@432.3"),
    (476.8, ">65@391.6 років:@405.7 <16.0@426.2"),
    (487.3, "Вагітні@391.6 жінки:@415.3 <8.0@436.8"),
    (501.2, "Ціанокобаламін@69 (вітамін@132.6 B12)@165.2 776@286.5 пг/мл@353.4 Дорослі@391.6 (20-78@419.7 "
            "років):@442.3 197.0@465.2 -@485 771.0@489.4"),
]


def test_homocysteine_keeps_the_bands_for_extra_folate_intake():
    reference = by_name(HOMOCYSTEINE)["Гомоцистеїн"].reference_text
    assert reference.endswith("Для людей з додатковим споживанням фолатів: Діти <15 років: <8.0 Дорослі: "
                              "15-65 років: <12.0 >65 років: <16.0 Вагітні жінки: <8.0")


INR = [
    (152.7, "Протромбіновий@69 тест@136.3 (ПЧ,@154.8 %@172.8 за@181.9 Квіком,@192.3"),
    (163.9, "МНВ@69 /@88.9 INR)@93.3"),
    (178.9, "Міжнародне@75 нормалізоване@122.9 1.06@285.4 Згідно@391.6 з@414.2 рекомендаціями@419.5 міжнародних@476"),
    (190.2, "відношення@75 (МНВ/INR)@121.4 протоколів@391.6 лікування@429.3 та@463.3 моніторингу@472.6"),
    (199.9, "антикоагулянтної@391.6 терапії:@451.2"),
    (210.4, "Не@391.6 приймають@402.7 антикоагулянтні@441.8 препарати:@497.1"),
    (220.9, "0.8@391.6 –@403.5 1.2@409.5"),
    (231.4, "Терапевтичні@391.6 межі@438.1 на@455.3 фоні@465.2 прийому@482.6"),
    (262.9, "Тромбозу@391.6 глибоких@425.7 вен,@457.3 тромбоемболії@473 (ТЕЛА):@523.9"),
    (273.4, "2.0@391.6 –@403.5 3.0@409.5"),
    (346.9, "Критичний@391.6 ризик@428.7 кровотечі:@449 більше@484.4 5.0@509.7"),
    (361.5, "Активований@69 частковий@122.3 29.9@285.4 сек@356.7 22.7@391.6 -@407.5 31.8@411.9"),
]


def test_inr_keeps_the_whole_printed_reference_not_its_first_words():
    """Only «Згідно з рекомендаціями міжнародних» was stored; 0.8 – 1.2 was lost."""
    row = by_name(INR)["Міжнародне нормалізоване відношення (МНВ/INR)"]
    assert "Не приймають антикоагулянтні препарати: 0.8 – 1.2" in row.reference_text
    assert row.reference_text.endswith("Критичний ризик кровотечі: більше 5.0")
    # One band for people off anticoagulants, others for treatment targets: nothing on
    # the page says which applies, so no single interval is taken from it.
    assert (row.reference_low, row.reference_high) == (None, None)


IMMATURE = [
    (168.3, "Незрілі@75 гранулоцити@104.1 (на@153.5 100@167.4 0.2@287.6 %@359 *Діти:@391.6 <2@412.1 років:@422.2 ≤0.4@442.6"),
    (179.5, "лейкоцитів)@75 2-5@391.6 років:@403.9 ≤0.3@424.4"),
    (220.8, "20-60@391.6 років:@411.9 ≤0.9@432.3"),
    (241.8, "*Згідно@391.6 наданих@417 рекомендацій@446.5 Roehrl@494.3 et@517.3 al.,@525.3"),
    (252.3, "Reference@391.6 Ranges@426.6 for@453.2 Immature@463.5"),
    (262.8, "GranulocytesArch@391.6 PatholLab@450.4 Med—Vol@484.6 135,@518 2011@533.9"),
    (273.3, "**Вагітні@391.6 жінки:@420.9"),
    (283.8, "І@391.6 триместр:@395.6 ≤0.92@430.5"),
    (294.3, "ІІ@391.6 триместр:@397.6 ≤2.00@432.5"),
    (315.3, "**Згідно@391.6 наданих@419.8 рекомендацій@449.3 Ling-Ling@497 Yuet@528.4"),
    (346.8, "according@391.6 to@424.6 pregnancy@432.5 trimesterInt@467.9 J@505.6 Clin@511.2 Exp@525.5 Med@539.8"),
    (357.3, "2016;9(5):8169-8175@391.6"),
    (368.9, "Незрілі@75 гранулоцити@104.1 (абс.)@153.5 0.01@285.4 10^9@354.4 *Діти:@391.6 <1@412.1 року:@422.2 ≤0.05@440.8"),
]


def test_a_citation_footnote_is_skipped_and_the_bands_after_it_kept():
    reference = by_name(IMMATURE)["Незрілі гранулоцити (на 100 лейкоцитів)"].reference_text
    assert reference == ("*Діти: <2 років: ≤0.4 2-5 років: ≤0.3 20-60 років: ≤0.9 **Вагітні жінки: "
                         "І триместр: ≤0.92 ІІ триместр: ≤2.00")


VITAMIN_D = [
    (151.8, "Вітамін@69 Д@99.8 (25-гідроксивітамін@107.5 D,@184.3 25-@194.2 37.1@285.4 нг/мл@353.4 Дорослі@391.6 "
            "(від@419.7 18@433.6 років):@443.5"),
    (163.0, "(OH)D)@69 Дефіцит:@391.6 <20.0@423.2"),
    (183.0, "Достатній@391.6 рівень:@426 ≥30.0@451 –@470.8 50.0*@476.8"),
    (193.5, "*Clinical@391.6 Practice@419.4 in@447.2 the@454.8 Prevention,@466.7 Diagnosis@504.8 and@538.2"),
    (225.0, "Pawel@391.6 Pludowski@413.1 et@447.2 al.,@455.2 2022@466.7"),
    (235.5, "Діти@391.6 (до@407.3 18@419.8 років):@429.7"),
    (246.0, "Дефіцит:@391.6 <20.0@423.2"),
    (256.5, "Оптимальний@391.6 рівень:@439 ≥20.0**@464"),
    (267.0, "**Враховуючи@391.6 рекомендації@439.9 Американської@485.6"),
    (288.0, "Pediatrics,@391.6 Wagner@427 CL@454 et@465.1 al.,@473.1 Pediatrics@484.6 2008@518"),
    (298.5, "Метод:@391.6 Хемілюмінесцентний@416.9 імуноаналіз@488.9 (CMIA)@529.9"),
]


def test_vitamin_d_keeps_the_childrens_bands_after_the_citation():
    reference = by_name(VITAMIN_D)["Вітамін Д (25-гідроксивітамін D, 25-(OH)D)"].reference_text
    assert reference.endswith("Діти (до 18 років): Дефіцит: <20.0 Оптимальний рівень: ≥20.0**")
    assert "Pludowski" not in reference and "Метод" not in reference


# --- 5. Reference semantics ------------------------------------------------------------


def reading(value, reference, comparator=None):
    limits = reference_limits(reference)
    return interpretation(ParsedObservation(
        raw_name="x", value_numeric=value, value_text=None, comparator=comparator, unit_raw=None,
        reference_text=reference, reference_low=limits.low, reference_high=limits.high, page_number=1,
        evidence_text="", confidence=1.0, reference_low_inclusive=limits.low_inclusive,
        reference_high_inclusive=limits.high_inclusive))


ELASTASE = ("> 200 мкг Ел/г калу - нормальна екзокринна функція підшлункової залози 100 - 200 мкг Ел/г калу - "
            "помірна форма недостатності екзокринної функції підшлункової залози. < 100 мкг Ел/г калу - важка "
            "форма недостатності екзокринної функції підшлункової залози")


def test_elastase_normal_band_is_above_200_not_the_insufficiency_tier():
    assert reference_limits(ELASTASE)[:2] == (200.0, None)
    assert reading(277.6, ELASTASE) == "within_vendor_range"
    assert reading(150.0, ELASTASE) == "low"


def test_a_strict_upper_limit_excludes_the_value_on_it():
    """CA-125 35.0 against «Референтне значення < 35» was published as inside the range:
    the start-up repair re-judged it through `interpretation`, which ignored the sign."""
    assert reading(35.0, "Референтне значення < 35") == "high"
    assert reading(34.9, "Референтне значення < 35") == "within_vendor_range"
    assert reading(35.0, "≤ 35") == "within_vendor_range"
    # A result printed with its own sign is not on the limit: carnosine «<1.0» against «<1».
    assert reading(1.0, "< 1", comparator="<") == "within_vendor_range"


CORTISOL = "Ранок (7:00-10:00): 5-25 Вечір (16:00-20:00): 2.5-12.5"


def test_time_of_day_bands_are_not_one_interval():
    """The clock times became the bounds («00-10») and a morning cortisol of 12.0 was high."""
    assert reference_limits(CORTISOL)[:2] == (None, None)
    assert reading(12.0, CORTISOL) == "within_vendor_range"  # inside both bands
    assert reading(30.0, CORTISOL) == "high"  # above both
    assert reading(20.0, CORTISOL) is None  # normal in the morning, high in the evening


AMINO = "<24 міс.: 37-177 2-17 років: 38-153 ≥18 років: 42-156"


def test_age_labelled_amino_acid_bands_give_the_adult_range():
    assert applicable_reference_bounds(AMINO, 31, "female") == (42.0, 156.0)
    assert applicable_reference_bounds(AMINO, 10, "female") == (38.0, 153.0)
    assert applicable_reference_bounds("<24 міс.: 2-20 2-17 років: 1-20 ≥18 років: <7", 31, "female") == (None, 7.0)
    # «<24 міс.» names no population the module can place in a whole year of age.
    assert applicable_reference_bounds(AMINO, 1, "female") == (None, None)


def test_interpretive_tiers_are_no_normal_interval():
    retic = ("<2.0 - показник гіпопроліферативного компонента анемії >2-3 - показник збільшення "
             "виникнення еротроцитів")
    assert reference_limits(retic)[:2] == (None, None)
    assert reading(0.15, retic) is None
    # Risk-group treatment targets name no healthy tier either.
    assert reference_limits("<3.0 - для груп низького ризику <2.6 - для груп помірного ризику")[:2] == (None, None)
    # A scale that names its healthy tier still gives it.
    assert reference_limits("<5.2 - Відсутність ризику 5.2 - <6.2 - Умовний ризик ≥6.2 - Високий ризик")[:2] == (None, 5.2)
    assert reference_limits("0.8 - 1.2 - відсутність ризику 1.2 - 1.5 - слабо виражений ризик")[:2] == (0.8, 1.2)


def test_a_healthy_population_band_is_the_reference():
    vitamin_d = ("Ризик дефіциту: <20.0 Ризик недостатнього вживання: 20.0 - <30.0 Здорове населення: "
                 "30.0 - 100.0 Інтоксикація: >100.0")
    assert reference_limits(vitamin_d)[:2] == (30.0, 100.0)
    assert reading(26.65, vitamin_d) == "low"


def test_a_lone_zero_is_an_upper_limit_of_zero():
    assert reference_limits("0.0")[:2] == (None, 0.0)
    assert reading(0.2, "0.0") == "high"
    assert reading(0.0, "0,0") == "within_vendor_range"
    assert reference_limits("5")[:2] == (None, None)  # a lone non-zero could be either limit


# --- Lab records: site headings, notes, signatures, grades, method lines ------------------


def lab_row(test, result, units="", norm=(), state="normal"):
    return {"test": test, "result": result, "units": units, "norm": list(norm), "state": state,
            "resulttype": "", "packet": ""}


SMEAR = [
    lab_row("Оцінка якості матеріалу/препарату урогенітального зішкрібу", "Матеріал задовільний"),
    lab_row("Виконавець цитологічного аналізу", "Іваненко І.І"),
    lab_row("ТОЧКА 2", "VAGINA"),
    lab_row("Лейкоцити", "в тяжах слизу"),
    lab_row("Еритроцити", "не виявлені"),
    lab_row("ТОЧКА 3", "CERVIX"),
    lab_row("Лейкоцити", "в тяжах слизу- 30-50"),
    lab_row("Еритроцити", "не виявлені"),
    lab_row("Висновок", "Ступінь чистоти III"),
    lab_row("Примітка", "Приналежність генотипів до філогенетичних груп: група А9 (16,31 типи)"),
]


def test_a_smear_site_heading_is_the_specimen_of_the_rows_under_it():
    values = [parsed for _row, parsed in labsync._record_values(SMEAR) if parsed is not None]
    assert [(item.raw_name, item.value_text, item.specimen) for item in values] == [
        ("Оцінка якості матеріалу/препарату урогенітального зішкрібу", "Матеріал задовільний", None),
        ("Лейкоцити", "в тяжах слизу", "VAGINA"),
        ("Еритроцити", "не виявлені", "VAGINA"),
        ("Лейкоцити", "в тяжах слизу- 30-50", "CERVIX"),
        ("Еритроцити", "не виявлені", "CERVIX"),
        ("Ступінь чистоти", "III", None),
    ]


def test_record_rows_drop_method_lines_and_the_specimen_label():
    esr = labsync._record_value(lab_row(
        "Аналіз крові: Швидкість осідання еритроцитів (ШОЕ, ESR)", "10", "мм/год.",
        ["Жінки (17 - 50 років): до 20.0", "Виконано на аналізаторі VES MATIC CUBE 30"]))
    assert esr.raw_name == "Швидкість осідання еритроцитів (ШОЕ, ESR)"
    assert esr.reference_text == "Жінки (17 - 50 років): до 20.0"
    pad = labsync._record_value(lab_row(
        "Лейкоцити", "не виявлені", "Leu/µL",
        ["не виявлені", "25 = +", "100 = ++", "Лейкоцити визначаються за активністю лейкоцитестерази."]))
    assert pad.reference_text == "не виявлені; 25 = +; 100 = ++"
    hpv = labsync._record_value(lab_row(
        "16 генотип", "не виявлено", "",
        ["<3 LgВПЛ/10^5 клітин: клінічно малозначуще", "Метод: Real-Time PCR",
         "Реагенти: Sacace Biotechnologies (Італія), які сертифіковані системою CE",
         "Аналізатор: CFX-96 (BioRad, США)"]))
    assert hpv.reference_text == "<3 LgВПЛ/10^5 клітин: клінічно малозначуще"
    strict = labsync._record_value(lab_row("Онкомаркер", "35.0", "Од/мл", ["< 35"]))
    assert (strict.reference_high, strict.reference_high_inclusive) == (35.0, False)


def test_the_repair_reads_a_stored_lab_record_again(tmp_path: Path, monkeypatch):
    from test_labsync_nofile import NOFILE, connected, stub_intake, sync

    indicators = [{"id": index, "name": row["test"], "value": row["result"], "unit": None,
                   "reference_text": None, "is_abnormal": False} for index, row in enumerate(SMEAR, 1)]
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    # What the reader filed before: every row a value, no site, the grade under «Висновок».
    never = re.compile(r"(?!x)x")
    monkeypatch.setattr(labsync, "_NOTE_ROW_RE", never)
    monkeypatch.setattr(labsync, "_SITE_ROW_RE", never)
    monkeypatch.setattr(labsync, "_GRADE_RESULT_RE", never)
    sync(settings, user_id, monkeypatch, NOFILE, indicators)
    monkeypatch.undo()
    with connect(settings) as connection:
        before = [tuple(row) for row in connection.execute(
            "SELECT raw_name, specimen FROM observations ORDER BY rowid")]
    assert ("ТОЧКА 2", None) in before and ("Висновок", None) in before
    assert labsync.recheck(settings)["record_values"] == 10 - 6 + 5  # 4 dropped, 5 rewritten
    with connect(settings) as connection:
        after = [tuple(row) for row in connection.execute(
            "SELECT raw_name, value_text, specimen FROM observations ORDER BY rowid")]
    assert after == [
        ("Оцінка якості матеріалу/препарату урогенітального зішкрібу", "Матеріал задовільний", None),
        ("Лейкоцити", "в тяжах слизу", "VAGINA"),
        ("Еритроцити", "не виявлені", "VAGINA"),
        ("Лейкоцити", "в тяжах слизу- 30-50", "CERVIX"),
        ("Еритроцити", "не виявлені", "CERVIX"),
        ("Ступінь чистоти", "III", None),
    ]
    assert labsync.recheck(settings)["record_values"] == 0  # idempotent


@pytest.mark.parametrize("test", ["ТОЧКА 2", "Виконавець цитологічного аналізу"])
def test_a_site_or_signature_row_is_information_in_the_cross_check(test):
    result = labsync.cross_check([lab_row(test, "VAGINA")], [])
    assert result["items"][0]["cls"] == "info"
