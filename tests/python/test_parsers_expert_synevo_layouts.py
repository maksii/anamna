"""Regression tests for the 2026-11-06 sandbox audit's parser findings (batch F1).

Every fixture is a real printed line, or the real word geometry of a real page,
transcribed from the source file the finding names (documents are referred to
by the audit's 1-based ``n``).  Word positions are written as «text@x0» per
printed line; widths are 3.5 pt a character, as in ``test_parsers.eskulab_page``.
"""

import pytest

from anamna.ingest.parsers import (
    ParseIssue,
    dipstick_threshold,
    garmin_category,
    known_antibiotic,
    label_key,
    parse_document,
    reference_bounds,
    reference_limits,
    same_label,
    scale_interpretation,
)


def layout(lines, page_number=1, ocr_text=""):
    """A page from «top: word@x word@x ...» lines: native text and word boxes."""
    words, text = [], []
    for top, row in lines:
        tokens = []
        for item in row.split():
            word, _, x = item.rpartition("@")
            x0 = float(x)
            words.append((x0, x0 + 3.5 * len(word), float(top), word))
            tokens.append(word)
        text.append(" ".join(tokens))
    return {"page_number": page_number, "native_text": "\n".join(text), "ocr_text": ocr_text, "words": words}


def text_page(text, page_number=1, ocr_text=""):
    return {"page_number": page_number, "native_text": text, "ocr_text": ocr_text}


# --- DOCA-02 / DOCC-02: Garmin's doubled category badge -----------------------


@pytest.mark.parametrize(
    "cell, following, category, note",
    [
        # n82 p2, verbatim from the text layer: the badge drawn twice and merged.
        ("ВиВсиоскоикйи й нормальний", "нормальний", "Високий нормальний", ""),
        ("ННоромрмалаьлньинйий", "10 лют. 2025", "Нормальний", ""),
        ("СтСутпуіпніьн ь1 1", "", "Ступінь 1", ""),
        # n82 p3 and n17: the note column shuffled into the second copy.
        ("ННоромрмалаьлньинйий +valsakor", "", "Нормальний", "+valsakor"),
        ("ВиВсиоскоикйи й нормал+ьванлиьйсакор", "нормальний", "Високий нормальний", "+вальсакор"),
    ],
)
def test_garmin_category_is_read_longest_first_through_the_doubled_badge(cell, following, category, note):
    assert garmin_category(cell, following) == (category, note)


def test_garmin_high_normal_reading_is_not_filed_as_normal():
    rows = parse_document(
        "Garmin Connect",
        "blood_pressure",
        [text_page(
            "10 лют. 2025\n"
            "18:18 135 Сис. / 83 Діас. 72 bpm ВиВсиоскоикйи й нормальний\n"
            "нормальний\n"
            "15:51 139 Сис. / 90 Діас. 73 bpm СтСутпуіпніьн ь1 1\n"
            "21:12 123 Сис. / 76 Діас. 62 bpm ННоромрмалаьлньинйий +valsakor\n"
        )],
    )
    categories = {row.observed_at: row for row in rows if row.raw_name == "Blood pressure category"}
    assert categories["2025-02-10T18:18:00"].value_text == "Високий нормальний"
    assert categories["2025-02-10T15:51:00"].value_text == "Ступінь 1"
    assert categories["2025-02-10T21:12:00"].value_text == "Нормальний"
    assert categories["2025-02-10T21:12:00"].note == "+valsakor"
    # The note travels on every row of the reading, and the evidence is the
    # row as printed rather than the shuffled glyphs.
    systolic = next(row for row in rows if row.raw_name == "Systolic blood pressure" and row.value_numeric == 123)
    assert systolic.note == "+valsakor"
    assert systolic.evidence_text == "21:12 123 Сис. / 76 Діас. 62 bpm Нормальний +valsakor"


# --- DOCB-02 / DOCA-06: Synevo's multi-line reference block --------------------

SYNEVO_HEADER = (135.6, "Показник@124 Результат@275 Од.@358 Референтний@442 інтервал@491")
#: n63 (2025-08-28 annual panel) page 1, the red-cell row and its whole block.
SYNEVO_RBC = [
    SYNEVO_HEADER,
    (410.9, "Еритроцити@75 (RBC)@122 5.06@285 10^12@352 Діти:@392 <1@409 року:@419 3.3@438 -@450 4.9@454"),
    (422.3, "клітин/л@349 1-6@392 років:@404 3.5@424 -@436 4.5@441"),
    (432.8, "6-12@392 років:@408 3.5@428 -@440 4.7@445"),
    (443.3, "12-16@392 років:@412 3.6@432 -@444 5.1@449"),
    (453.8, "Дорослі:@392"),
    (464.3, "Чоловіки:@392 4.0@425 -@437 5.0@441"),
    (474.8, "Жінки:@392 3.7@415 -@427 4.7@431"),
    (485.3, "Гідродинамічне@392 фокусування@445 з@491 імпедансним@496"),
    (495.8, "методом@392 (метод@423 прямого@448 визначення)@477"),
    (507.4, "Гемоглобін@75 (HGB)@119 152@286 г/л@358 Діти:@392 <1@409 року:@419 100.0@438 -@458 140.0@462"),
    (518.8, "1-6@392 років:@404 110.0@424 -@444 145.0@449"),
]


def test_synevo_reference_is_the_whole_printed_block():
    rbc = next(
        row for row in parse_document("Synevo", "laboratory", [layout(SYNEVO_RBC)])
        if row.raw_name == "Еритроцити (RBC)"
    )
    assert rbc.reference_text == (
        "Діти: <1 року: 3.3 - 4.9 1-6 років: 3.5 - 4.5 6-12 років: 3.5 - 4.7 "
        "12-16 років: 3.6 - 5.1 Дорослі: Чоловіки: 4.0 - 5.0 Жінки: 3.7 - 4.7"
    )
    # The method note under the block is not part of it.
    assert "Гідродинамічне" not in rbc.reference_text
    # Without the patient, a block for several populations yields no bounds.
    assert (rbc.reference_low, rbc.reference_high) == (None, None)


def test_synevo_block_gives_this_patients_bounds_when_the_patient_is_known():
    """RBC 5.06 x10^12/L, a 33-year-old man: the laboratory's limit is 5.0."""
    rbc = next(
        row
        for row in parse_document("Synevo", "laboratory", [layout(SYNEVO_RBC)], age_years=33, sex="male")
        if row.raw_name == "Еритроцити (RBC)"
    )
    assert (rbc.reference_low, rbc.reference_high) == (4.0, 5.0)
    assert rbc.value_numeric > rbc.reference_high


# --- DOCB-03 / DOCB-17 / DOCB-11 / DOCA-17: Expert's wrapped cells, printed labels ---

EXPERT_HEADER_237 = (237.3, "ПОКАЗНИК@148 РЕЗУЛЬТАТ@350 НОРМА@480")
#: n46, result N6 (2025-02-15), HbA1c with its scale wrapped around it.
EXPERT_HBA1C = [
    (210.1, "Пацієнт:@34 Петренко@79 Іван@139 Петрович,@184 14.03.1990@249 р.н.@307 15.02.2025@507"),
    EXPERT_HEADER_237,
    (252.4, "<@457 5.7%@465 –@492 здорове@501"),
    (267.0, "населення@473"),
    (274.4, "Глікований@82 гемоглобін@141 (HbA1c)цільна@200"),
    (281.7, "5.24%@364 5.7%@442 -@468 6.5%@474 -@501 предіабет@507"),
    (289.0, "кров@165"),
    (296.3, ">@440 6.5%@449 -@475 при@482 цукровому@504"),
    (311.0, "діабеті@482"),
    (330.0, "Результати@43 досліджень@103 не@168 є@183 клінічним@191 діагнозом@246"),
]


def test_expert_hba1c_reference_is_the_printed_scale_and_its_evidence_the_row():
    (row,) = parse_document("Expert Hospital", "laboratory", [layout(EXPERT_HBA1C)])
    assert row.raw_name == "Глікований гемоглобін (HbA1c)"
    assert row.specimen == "цільна кров"
    assert row.value_numeric == 5.24 and row.unit_raw == "%"
    assert row.reference_text == (
        "< 5.7% – здорове населення 5.7% - 6.5% - предіабет > 6.5% - при цукровому діабеті"
    )
    assert (row.reference_high, row.reference_high_inclusive) == (5.7, False)
    # DOCB-17: the evidence is the result row, not the heading with the name.
    assert "Пацієнт" not in row.evidence_text and "5.24%" in row.evidence_text


def test_expert_hba1c_on_a_report_printing_another_reference_keeps_that_one():
    """n60, result N9: «4.0 - 5.7», where a constant three-band scale was stored."""
    page = layout([
        (171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494"),
        (183.3, "Глікований@17 гемоглобін@70 (HbA1C)@129 5.60%@366 4.0@470 -@485 5.7@490"),
        (231.9, "Результати@24 досліджень@72 не@124 є@137"),
    ])
    (row,) = parse_document("Expert Hospital", "laboratory", [page])
    assert row.reference_text == "4.0 - 5.7"
    assert (row.reference_low, row.reference_high) == (4.0, 5.7)


def test_expert_vitamin_d_and_ana_keep_the_printed_label_unit_and_reference():
    vitamin_d = layout([
        (171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494"),
        (183.3, "від@448 30@463 до@475 50@488 (ризик@500 дефіциту@529 <@569"),
        (194.7, "10,0;@457 ризик@478 недостатнього@505"),
        (200.1, "Вітамін@17 D@50 загальний,@58 нг/мл@106 32,122@366"),
        (206.1, "вживання@445 <@489 30,0;@496 інтоксикація@518 >@572"),
        (217.5, "150,0)@498"),
        (231.9, "Результати@24 досліджень@72 не@124 є@137"),
    ])
    (row,) = parse_document("Expert Hospital", "laboratory", [vitamin_d])
    assert (row.raw_name, row.unit_raw) == ("Вітамін D загальний", "нг/мл")
    assert row.reference_text == (
        "від 30 до 50 (ризик дефіциту < 10,0; ризик недостатнього вживання < 30,0; інтоксикація > 150,0)"
    )
    assert (row.reference_low, row.reference_high) == (30.0, 50.0)
    assert row.value_printed == "32,122"

    ana = layout([
        EXPERT_HEADER_237,
        (252.4, "Негативний@451 (-):<1.0@513"),
        (259.7, "Антинуклеарні@75 антитіла@153 (ANA)сироватка@198"),
        (267.0, "0.89@369 Сумнівний:@453 1.0-1.2@513"),
        (274.4, "крові@164"),
        (281.7, "Позитивний@449 (+):>1.2@513"),
        (300.8, "Результати@43 досліджень@103 не@168 є@183"),
    ])
    (row,) = parse_document("Expert Hospital", "laboratory", [ana])
    assert row.raw_name == "Антинуклеарні антитіла (ANA)"
    assert row.specimen == "сироватка крові"
    assert row.reference_text == "Негативний (-):<1.0 Сумнівний: 1.0-1.2 Позитивний (+):>1.2"
    assert row.vendor_interpretation == "within_vendor_range"


def test_ana_equivocal_value_is_borderline_not_high():
    scale = "Негативний (-):<1.0 Сумнівний: 1.0-1.2 Позитивний (+):>1.2"
    assert scale_interpretation(0.89, scale) == "within_vendor_range"
    assert scale_interpretation(1.1, scale) == "borderline"
    assert scale_interpretation(1.3, scale) == "positive"


def test_st_paraskeva_rows_keep_the_form_label():
    """n5, 2018-07-21: «Еритроцити (RBC):» was stored as "Red blood cell count"."""
    text = (
        "ФОРМА № 225/о\n"
        "Еритроцити (RBC): 10*12 клітин/л 5,22\n4,0 ­ 5,0\n"
        "Середня концентрація HGB в г/ л 339,0 310 ­ 380\nеритроциті(MCHC):\n"
        "Лімфоцити (LYM)­% % 18,60 15,0 ­ 50,0\n"
    )
    rows = {row.raw_name: row for row in parse_document("St. Paraskeva Medical Center", "laboratory", [text_page(text)])}
    assert set(rows) == {
        "Еритроцити (RBC)", "Середня концентрація HGB в еритроциті(MCHC)", "Лімфоцити (LYM)-%"
    }
    assert rows["Лімфоцити (LYM)-%"].value_printed == "18,60"


# --- DOCB-07 / DOCB-08 / DOCC-34 / DOCA-09: reading a printed reference ---------


def test_a_share_of_another_analyte_is_not_a_bound():
    """n41/n54/n56: «До 75% від загального» stored as an upper limit of 75 µmol/L."""
    assert reference_bounds("До 75% від загального") == (None, None)
    assert reference_bounds("75% від білірубіну загального") == (None, None)


def test_expert_cholesterol_scale_wrapped_round_its_value_is_read_whole():
    """n58, result N10: the reference was NULL, the scale wrapped above and below."""
    page = layout([
        (171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494"),
        (195.3, "Ліпопротеїди@17 високої@74 щільності,@106 ммоль/л@151 1,51@371 від@495 1,04@510"),
        (207.3, "До@443 5,2;@456 5,2-6,2@473 гранично@503 високий@544"),
        (212.7, "Холестерин@17 загальний,@67 ммоль/л@115 7,35@371"),
        (218.7, "рівень;@453 >6,2@485 високий@504 рівень@541"),
        (230.7, "Тригліцериди,@17 ммоль/л@79 1,02@371 до@498 1,7@511"),
        (269.1, "Результати@24 досліджень@72 не@124 є@137"),
    ])
    rows = {row.raw_name: row for row in parse_document("Expert Hospital", "laboratory", [page])}
    cholesterol = rows["Холестерин загальний"]
    assert cholesterol.reference_text == "До 5,2; 5,2-6,2 гранично високий рівень; >6,2 високий рівень"
    assert (cholesterol.reference_low, cholesterol.reference_high) == (None, 5.2)
    assert rows["Ліпопротеїди високої щільності"].reference_low == 1.04
    assert rows["Тригліцериди"].reference_high == 1.7


def test_a_negative_band_bound_is_read_whatever_the_decimal_separator():
    """n71, HBsAg: «…сумнівний: 0,9-1,0…» lost the 0.9 the old parser had."""
    limits = reference_limits("негативний: <0.9 сумнівний: 0,9-1,0 позитивний: ≥1,0")
    assert tuple(limits) == (None, 0.9, True, False)
    # The other way round: Synevo prints the interval first.
    assert reference_bounds("<0.9 - негативний результат 0.9 - <1.0 - сіра зона ≥1.0 - позитивний результат") == (None, 0.9)
    assert reference_bounds(">1.0 - негативний результат ≤1.0 - позитивний результат") == (1.0, None)


@pytest.mark.parametrize(
    "reference, expected",
    [
        ("< 0.2", (None, 0.2, True, False)),
        ("≤ 5.0", (None, 5.0, True, True)),
        ("до 2,59", (None, 2.59, True, True)),
        ("> 1.0", (1.0, None, False, True)),
        ("від 1,04", (1.04, None, True, True)),
        ("4.0 - 5.0", (4.0, 5.0, True, True)),
        ("20.0 - <30.0", (20.0, 30.0, True, False)),
    ],
)
def test_bound_inclusivity_follows_the_printed_comparator(reference, expected):
    assert tuple(reference_limits(reference)) == expected


def test_a_value_on_a_strict_limit_is_outside_it():
    """n16, EskuLab YLC 0.2 against the men's «< 0.2»: shown green before."""
    row = next(
        item for item in parse_document(
            "Synevo", "laboratory",
            [text_page("Показник Результат\nДріжджеподібні клітини (YLC) 0.2 кл/мкл чоловіки < 0.2 жінки < 0.7")],
            age_years=26, sex="male",
        )
    )
    assert (row.reference_high, row.reference_high_inclusive) == (0.2, False)
    assert row.vendor_interpretation == "high"


# --- DOCA-11 / DOCC-05 / CLIN-36: semi-quantitative scales ---------------------


def test_dipstick_scales_state_their_first_positive_tier():
    assert dipstick_threshold("не виявлені 25 = + 75 = ++ 500 = +++") == 25
    assert dipstick_threshold("нормальний або сліди в ранковій порції; +-=8,5; +=17; ++=50; +++≥100") == 17
    assert dipstick_threshold("негативний; +-=5-10; +=50; ++=80; +++≥300") == 50
    assert dipstick_threshold("4.0 - 5.0") is None


def test_positive_leukocyte_pad_is_flagged():
    """n16, EskuLab order N11: «Лейкоцити (C-LEU) 25 кл/мкл», the scale's «+»."""
    row = next(iter(parse_document(
        "Synevo", "laboratory",
        [text_page("Показник Результат\nЛейкоцити (C-LEU) 25 кл/мкл не виявлені 25 = + 75 = ++ 500 = +++")],
    )))
    assert (row.reference_high, row.reference_high_inclusive) == (25.0, False)
    assert row.vendor_interpretation == "high"


EXPERT_HEADER_171 = (171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494")
#: n79, result N3 (2025-09-16), three rows of the urinalysis.
EXPERT_URINE = [
    EXPERT_HEADER_171,
    (383.1, "нормальний@460 або@515 сліди@532 в@557"),
    (394.5, "Уробіліноген,@17 мкмоль/л@75 35@374 ранковій@451 порції;@490 +-=8,5;@519 +=17;@549"),
    (405.9, "++=50;@480 +++≥100@508"),
    (417.9, "Нітрити,@17 ммоль/л@53 негативний@355 негативний@486"),
    (610.0, "Слиз,@17 в@42 п/з@49 +@377 (не@482 виявлено)@497"),
    (648.4, "Результати@24 досліджень@72 не@124 є@137"),
]


def test_expert_urinalysis_scales_judge_their_pads():
    rows = {row.raw_name: row for row in parse_document("Expert Hospital", "laboratory", [layout(EXPERT_URINE)])}
    urobilinogen = rows["Уробіліноген"]
    assert urobilinogen.reference_text == (
        "нормальний або сліди в ранковій порції; +-=8,5; +=17; ++=50; +++≥100"
    )
    assert (urobilinogen.reference_high, urobilinogen.vendor_interpretation) == (17.0, "high")
    # A «+» against «(не виявлено)» is a finding (DOCC-05).
    assert rows["Слиз"].value_text == "+" and rows["Слиз"].vendor_interpretation == "positive"
    # CLIN-30: a word result carries no unit.
    assert rows["Нітрити"].value_text == "негативний" and rows["Нітрити"].unit_raw is None


# --- DOCC-03: the autoimmune chip ----------------------------------------------

#: n67, result N12: the chip as OCR reads it (stored OCR text, verbatim lines).
AUTOIMMUNE_OCR = """[Embedded image region 1]
діапазон 1 2 з 4
антигени LY]
IgG [kU/I] 0.3 0.8 4.5 10.0 100)
Ro/SS-A 52 «0.15
La/SS-B «0.15
МРО «0 15
РВЗ «0 15
LC 1 «0 15
Ku <0 15
Scl-70
діапазон Kony. IgG [kU/I] Інтерпретація 1 діапазон Конц. IgG [kU/I] Інтерпретація
0 <0.30 негативний результат 3 4.50 - <10 позитивний
1 0.30 - «0.80 гранична норма 4 >= 10 високо позитивний
2 0.80 - «4.50 низько позитивний
"""


def test_autoimmune_chip_keeps_comparator_class_and_legend():
    issues: list[ParseIssue] = []
    rows = parse_document(
        "Expert Hospital", "laboratory", [text_page("АУТОІМУННА СТАНДАРТНА - Х ПАНЕЛЬ (G4003)", ocr_text=AUTOIMMUNE_OCR)],
        issues=issues,
    )
    by_name = {row.raw_name: row for row in rows}
    assert list(by_name) == ["Ro/SS-A 52", "La/SS-B", "MPO", "PR3", "LC 1", "Ku"]
    for row in rows:
        assert (row.value_numeric, row.comparator, row.unit_raw) == (0.15, "<", "kU/L")
        assert row.reference_text == "<0.30 негативний результат"
        assert (row.reference_high, row.reference_high_inclusive) == (0.30, False)
        assert row.vendor_interpretation == "within_vendor_range"
    # A known antigen whose line carries no readable result is reported, not dropped.
    assert [(issue.kind, issue.raw_name) for issue in issues] == [("unparsed_known_analyte", "Scl-70")]


# --- DOCC-22: antibiotics ------------------------------------------------------


def test_ocr_misread_antibiotic_is_filed_under_the_known_name_and_unknowns_go_to_review():
    """n68, result N13: «ImineHem резистентний» became its own antibiotic."""
    ocr = (
        "Результат дослідження\nАнтибіотик\nPseudomonas aeruginosa\n"
        "Піперацилін-тазобактам помірночутливий\nImineHem резистентний\n"
        "Меропенем чутливий\nQwertyzolid резистентний\n"
    )
    issues: list[ParseIssue] = []
    rows = parse_document("Expert Hospital", "microbiology", [text_page("", ocr_text=ocr)], issues=issues)
    names = [row.raw_name for row in rows if row.value_text and "чутлив" in row.value_text or row.value_text == "резистентний"]
    assert "Іміпенем" in names and "ImineHem" not in names
    assert "Qwertyzolid" not in names
    assert [(issue.kind, issue.raw_name) for issue in issues] == [("unknown_antibiotic", "Qwertyzolid")]
    assert known_antibiotic("Цефтазидим-авіабактам") == "Цефтазидим-авіабактам"


# --- DOCC-29: ALEX wrapped names -----------------------------------------------

ALEX_HEADER = (64.4, "Позначення@40 E/M@204 Алерген@234 Сімейство@317 білків@364 kUA/L@529")


def test_alex_wrapped_common_name_and_wrapped_code_are_rejoined():
    """n69, ALEX² N14: «Aca m» lost its name, «Подорожник ланцетолистий» its code."""
    pages = [
        layout([
            ALEX_HEADER,
            (384.8, "Пилок@30 дерев@71"),
            (408.9, "Акація@30 срібляста@60 (Рід@103 тропічних@122"),
            (415.1, "Aca@233 m@251 <@429 0,10@437"),
            (421.4, "дерев)@30"),
            (438.5, "Айлант@30 найвищий@63 Ail@233 a@245 <@429 0,10@437"),
            (552.8, "Подорожник@30 ланцетолистий@86 <@429 0,10@437"),
            (557.5, "Pla@233 l@248"),
            (580.1, "Pla@233 l@248 1@253 Ole@315 e@332 1-Family@339 <@429 0,10@437"),
            (709.7, "Пшениця@30 Alpha-Amylase@315 Trypsin-@378"),
            (716.0, "Tri@233 a@246 aA_TI@253 <@429 0,10@437"),
            (722.2, "Inhibitor@315"),
            (807.9, "Екстракт@45 алергену@80 Молекулярний@187 алерген@244 IgE@319 <@334 0,3@341 негативна@356 або@396 сумнівна@411"),
        ])
    ]
    rows = [row.raw_name for row in parse_document("Synevo", "allergy", pages)]
    assert rows == [
        "Акація срібляста (Рід тропічних дерев) Aca m",
        "Айлант найвищий Ail a",
        "Подорожник ланцетолистий Pla l",
        "Pla l 1 Ole e 1-Family",
        "Пшениця Tri a aA_TI Alpha-Amylase Trypsin-Inhibitor",
    ]
    first = parse_document("Synevo", "allergy", pages)[0]
    # The cut-off as the report prints it, not an English paraphrase.
    assert first.reference_text == "IgE < 0,3 негативна або сумнівна"
    assert (first.reference_high, first.reference_high_inclusive) == (0.3, False)


# --- DOCC-35 / DOCC-38 / DOCB-19 / CLIN-30 ------------------------------------


def test_blood_group_answer_list_is_not_a_reference_and_its_value_is_one_spelling():
    """n71 prints «А (II)» over every possible answer; n75 prints «А(ІІ)»."""
    eskulab_style = parse_document(
        "Synevo", "laboratory",
        [text_page("Показник Результат\nГрупа крові А (II) III - (B-) II -(A-) I - (0-) IV + (AB+)")],
    )
    expert = parse_document(
        "Expert Hospital", "laboratory",
        [layout([(171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494"), (183.3, "Група@17 крові@44 А(ІІ)@355"),
                 (195.3, "Резус-фактор@17 (+)@355 позитивний@368"), (245.1, "Результати@24 досліджень@72")])],
    )
    groups = [row for row in eskulab_style + expert if row.raw_name == "Група крові"]
    assert {row.value_text for row in groups} == {"A(II)"}
    assert all(row.reference_text is None for row in groups)
    assert any(row.raw_name == "Резус-фактор" and row.value_text == "(+) позитивний" for row in expert)


def test_eskulab_specimen_line_becomes_the_rows_specimen():
    """Doc 97, EskuLab N15: «цільна кров ЗАК» printed under every blood-count row."""
    page = layout([
        (212.5, "Показник@28 Результат@231 Одиниці@316 Референтні@417 значення@481"),
        (234.7, "Гемоглобін@28 (HGB)@84 155@249 г/л@331 Жінки:@378 120-150@406"),
        (238.1, "цільна@111 кров@134 ЗАК@150"),
        (245.7, "Чоловіки:@378 130-170@416"),
    ])
    (row,) = parse_document("EskuLab", "laboratory", [page])
    assert row.raw_name == "Гемоглобін (HGB)"
    assert row.specimen == "цільна кров"
    assert row.reference_text == "Жінки: 120-150 Чоловіки: 130-170"


def test_a_reference_block_over_a_page_break_is_read_whole():
    """Doc 97, ESR: the men-over-50 and both women's bands are on the next page (DOCC-36)."""
    header = "Показник@28 Результат@231 Одиниці@316 Референтні@417 значення@481"
    page5 = layout([
        (212.5, header),
        (741.6, "ШОЕ@28 за@54 Вестергреном@67 (Швидкість@137 2@254 мм/год@322 Діти@378 до@397 17р:@408 <10мм/год@426"),
        (752.4, "осідання@28 еритроцитів)@73 Чоловіки@378 17@413 -@424 50р:@429 <@447 15мм/год@455"),
        (755.8, "цільна@138 кров@160 ЗАК@177"),
    ], page_number=5)
    page6 = layout([
        (195.0, header),
        (205.8, "вимірювання@304"),
        (217.6, "Чоловіки@378 старші@413 50р:@440 <20мм/год@458"),
        (228.1, "Жінки@378 17-50р:@404 <20мм/год@433"),
        (238.6, "Жінки@378 старші@404 50р.@431 :.@448 <30мм/год@455"),
        (271.1, "1-20@153 1-20@422"),
        (379.9, "Лімфоцити@28 (на@84 100@101 лейкоцитів)@121 42.8@247 %@334 Дорослі:@378 19-37@412"),
    ], page_number=6)
    rows = parse_document("EskuLab", "laboratory", [page5, page6])
    esr = next(row for row in rows if row.raw_name.startswith("ШОЕ"))
    assert esr.reference_text == (
        "Діти до 17р: <10мм/год Чоловіки 17 - 50р: < 15мм/год Чоловіки старші 50р: <20мм/год "
        "Жінки 17-50р: <20мм/год Жінки старші 50р. :. <30мм/год"
    )
    # The correlation table under it belongs to nobody.
    assert "1-20" not in esr.reference_text
    assert any(row.raw_name == "Лімфоцити (на 100 лейкоцитів)" for row in rows)


def test_hbsag_label_keeps_the_tail_that_wrapped_under_its_value():
    """n74, result N16 (DOCC-33)."""
    page = layout([
        (171.3, "ПОКАЗНИК@143 РЕЗУЛЬТАТ@355 НОРМА@494"),
        (207.3, "Швидкий@17 тест@58 для@77 виявлення@94 антитіл@142 до@174 вірусу@187 гепатиту@214 С@251 Негативний@354 Негативний@465 результат@517"),
        (219.3, "Швидкий@17 тест@58 для@77 виявлення@94 поверхневого@142 антигену@201 до@240 вірусу@253 гепатиту@280"),
        (224.7, "Негативний@354 Негативний@465 результат@517"),
        (230.7, "В@17 (HbsAg)@25"),
        (245.1, "Результати@24 досліджень@72 не@124"),
    ])
    names = [row.raw_name for row in parse_document("Expert Hospital", "laboratory", [page])]
    assert names == [
        "Швидкий тест для виявлення антитіл до вірусу гепатиту С",
        "Швидкий тест для виявлення поверхневого антигену до вірусу гепатиту В (HbsAg)",
    ]


def test_labels_pair_across_unit_suffixes_and_wrapped_tails():
    """The rule a re-read uses to find the stored row it re-reads (DOCC-08/33)."""
    assert label_key("Лейкоцити (WBC), в п/з") == label_key("Лейкоцити (WBC)")
    assert label_key("Середній вміст гемоглобіну в еритроциті (МСН)") == label_key(
        "Середній вміст гемоглобіну в еритроциті (MCH)"
    )
    assert same_label(
        "Швидкий тест для виявлення поверхневого антигену до вірусу гепатиту",
        "Швидкий тест для виявлення поверхневого антигену до вірусу гепатиту В (HbsAg)",
    )
    assert not same_label("Лейкоцити", "Лейкоцити в мкл (WBC)")


def test_printed_precision_survives():
    """DOCA-26: «1,80» and «0.40» are two-decimal results."""
    rows = parse_document(
        "Synevo", "laboratory",
        [text_page("Показник Результат\nЛімфоцити (абс.) 1,80 10^9 1.0 - 4.8\nЕлементи слизу в мкл (MUCUS) 0.40 кл/мкл 0 - 0.99")],
    )
    assert [row.value_printed for row in rows] == ["1,80", "0.40"]


# --- DOCA-16 / DOCC-28: ultrasound measurements --------------------------------


def test_echo_lv_mass_index_takes_this_patients_band():
    """n23 (2025-02-13): LVMI 178 g/m² against «49-115 г/м2 (чоловіки)»."""
    text = (
        "Виміри Межі норми\n"
        "Ліве передсердя 3.3 1,9 – 4,0 см\n"
        "Індекс маси міокарда ЛШ 43-95 г/м2 (жінки)\n"
        "178 49-115 г/м2 (чоловіки)\n"
        "Об'єм лівого передсердя 22-52 мл\n"
    )
    # The left atrium beside it is a row of its own now (test_ultrasound_measurements).
    (row,) = [
        item for item in parse_document("Expert Hospital", "ultrasound", [text_page(text)], age_years=32, sex="male")
        if item.raw_name == "Left ventricular mass index"
    ]
    assert (row.raw_name, row.value_numeric, row.unit_raw) == ("Left ventricular mass index", 178.0, "г/м2")
    assert row.reference_text == "43-95 г/м2 (жінки) 49-115 г/м2 (чоловіки)"
    assert (row.reference_low, row.reference_high) == (49.0, 115.0)
    # The other printed layout (n89) wraps the value under the label.
    wrapped = "Ліве передсердя 1,9 – 4,0 см\n3.3\n43-95 г/м2 (жінки)\nІндекс маси міокарда ЛШ 49-115 г/м2\n178\n(чоловіки)\n"
    (row,) = parse_document("Expert Hospital", "ultrasound", [text_page(wrapped)], sex="male")
    assert (row.value_numeric, row.reference_high) == (178.0, 115.0)


def test_carotid_duplex_rows_and_intima_media_thickness():
    """n32 and n90 (2025-08-26), both printed layouts."""
    flat = (
        "Загальна сонна артерія, права 89 N=50-104 Кровоплин магістральний, хід правильний\n"
        "Внутрішня сонна артерія, права 67 N=37-105 Кровоплин магістральний, хід правильний\n"
        "Загальна сонна артерія, ліва 104 N=50-104 Кровоплин магістральний, хід правильний\n"
        "Товщина КІМ справа 0,6 мм, КІМ зліва 0,6 мм. Атеросклеротичні бляшки – не виявлено.\n"
    )
    wrapped = (
        "Загальна сонна артерія, Кровоплин магістральний, хід\n89 N=50-104\nправа правильний\n"
        "Загальна сонна артерія, Кровоплин магістральний, хід\n104 N=50-104\nліва правильний\n"
        "Диференціювання КІМ на шари збережене. Товщина КІМ справа 0,6 мм, КІМ зліва 0,6\nмм.\n"
    )
    for text in (flat, wrapped):
        rows = parse_document("Expert Hospital", "ultrasound", [text_page(text)])
        psv = sorted((row.specimen, row.value_numeric, row.reference_low, row.reference_high)
                     for row in rows if row.raw_name == "Peak systolic velocity, common carotid artery")
        assert psv == [("ліва", 104.0, 50.0, 104.0), ("права", 89.0, 50.0, 104.0)]
        imt = sorted((row.specimen, row.value_numeric) for row in rows if row.raw_name == "Carotid intima-media thickness")
        assert imt == [("зліва", 0.6), ("справа", 0.6)]


def test_thyroid_volumes_and_abdominal_sizes_with_their_printed_norms():
    thyroid = (
        "Права частка : 15.4 / 17.8 / 47мм. Об’єм : 6 N- 7.5 cm3\n"
        "Ліва частка : 18.5 / 16.4 / 45.7 мм. Об’єм : 6.5 N- 7.5 cm3\n"
        "Сумарний об’єм: 12.5 сm3 N- 13cm3 (за класифікацією Brunn)\n"
    )
    rows = [row for row in parse_document("Expert Hospital", "ultrasound", [text_page(thyroid)]) if row.raw_name == "Thyroid volume"]
    assert [(row.specimen, row.value_numeric, row.reference_high) for row in rows] == [
        ("Права частка", 6.0, 7.5), ("Ліва частка", 6.5, 7.5), ("Сумарний", 12.5, 13.0)
    ]
    abdomen = (
        "Печінка збільшена в розмірах:\n"
        "Права частка: Косий вертикальний (по середньо-ключичній лінії) 164.7 мм.\n"
        "Холедох на всьому проміжку нерозширений 3.1 мм. (норма 7 мм).\n"
        "Стінка потовщена – 4.5 мм. Внутрішньопорожнинних утворів не виявлено.\n"
    )
    rows = {row.raw_name: row for row in parse_document("Expert Hospital", "ultrasound", [text_page(abdomen)])}
    assert (rows["Liver craniocaudal size"].value_numeric, rows["Liver craniocaudal size"].vendor_interpretation) == (164.7, "high")
    assert (rows["Common bile duct diameter"].value_numeric, rows["Common bile duct diameter"].reference_high) == (3.1, 7.0)
    assert (rows["Bladder wall thickness"].value_numeric, rows["Bladder wall thickness"].vendor_interpretation) == (4.5, "high")
    # A soft-tissue scan prints no such table and yields nothing.
    assert parse_document("Expert Hospital", "ultrasound", [text_page("Ліпома розмірами 12 мм")]) == []


# --- confirmations: DOCA-07, DOCB-15, DOCB-16 stay fixed ----------------------


def test_expert_wrapped_mid_code_and_unprinted_liver_units_stay_fixed():
    """DOCB-15 (MID# wrapped under its value) and DOCB-16 (no unit printed -> none stored).

    n44, result N6 p1 and n41, result N17 p1, word geometry verbatim.
    """
    page = layout([
        (171.3, "ПОКАЗНИК@145 РЕЗУЛЬТАТ@358 НОРМА@495"),
        (195.3, "Абсолютне@17 значення@65 лімфоцитів@107 (LYM#),@156 х@188 10*9/л@195 2,6@376 від@484 0,6@499 до@513 4,1@526"),
        (207.3, "Абсолютне@17 значення@65 суміші@107 (моноцити,@136 базофіли@186 та@226 еозинофіли)@237 (MID#),@290"),
        (212.7, "0,6@376 від@484 0,1@499 до@513 0,9@526"),
        (218.7, "х@17 10*9/л@24"),
        (230.7, "АСАТ(АСТ)@17 26,0@373 до@500 40@512"),
        (281.1, "Результати@24 досліджень@72 не@124"),
    ])
    rows = {row.raw_name: row for row in parse_document("Expert Hospital", "laboratory", [page])}
    mid = rows["Абсолютне значення суміші (моноцити, базофіли та еозинофіли) (MID#)"]
    assert (mid.value_numeric, mid.unit_raw, mid.reference_low, mid.reference_high) == (0.6, "х 10*9/л", 0.1, 0.9)
    assert rows["АСАТ(АСТ)"].unit_raw is None


def test_synevo_sediment_rows_stay_read():
    """DOCA-07: n3 (Synevo 2016-07-21) lost five microscopy rows; the column reader keeps them."""
    page = layout([
        SYNEVO_HEADER,
        (615.8, "Еритроцити@75 не@270 виявлені@281 Ery/µL@352 не@392 виявлені@402"),
        (700.0, "Ручна@75 мікроскопія@100 осаду@150 сечі@180"),
        (742.4, "Еритроцити@75 не@270 виявлені@281 не@392 виявлені,@402 поодинокі@435 в@469 препараті@475"),
        (760.1, "Еритроцити,@75 стан@124 незмінені@275 незмінені@392"),
        (780.0, "Примітка:@75"),
    ])
    rows = parse_document("Synevo", "laboratory", [page])
    sediment = [row for row in rows if row.section == "sediment"]
    assert [row.raw_name for row in sediment] == ["Еритроцити", "Еритроцити, стан"]
    # The dipstick row of the same name is kept apart from its microscopy.
    assert sum(1 for row in rows if row.raw_name == "Еритроцити") == 2


def test_hla_b27_tolerates_one_stray_ocr_glyph_before_ne_without_flipping_the_result():
    from anamna.ingest.parsers import parse_hla_b27

    page = "1. 00044 Виявлення носійства гену HLA B-27\nПоказник Результат Одиниці Референтні значення\nвимірювання\n"
    rows = parse_hla_b27(page + "Результат іне виявлено", 1)
    assert [row.value_text for row in rows] == ["не виявлено"]
    assert [row.value_text for row in parse_hla_b27(page + "Результат не виявлено", 1)] == ["не виявлено"]
    assert [row.value_text for row in parse_hla_b27(page + "Результат виявлено", 1)] == ["виявлено"]
    assert parse_hla_b27(page + "Результат і виявлено", 1) == []  # a detached mark is not read as anything
