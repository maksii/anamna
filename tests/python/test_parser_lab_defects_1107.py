"""Parser defects found on 2026-11-07 by cross-checking parsed PDFs against the labs' own result rows.

Word geometry is taken from the real reports (EskuLab, Synevo and Ekspert reports); names, dates and other identifying
lines are left out.  Only the printed result rows are kept.
"""

from __future__ import annotations

from anamna.ingest.parsers import parse_document


def layout(lines, page_number=1):
    """A page from («top», «word@x word@x ...») lines: native text and word boxes."""
    words, text = [], []
    for top, row in lines:
        tokens = []
        for item in row.split():
            word, _, x = item.rpartition("@")
            x0 = float(x)
            words.append((x0, x0 + 3.5 * len(word), float(top), word))
            tokens.append(word)
        text.append(" ".join(tokens))
    return {"page_number": page_number, "native_text": "\n".join(text), "ocr_text": "", "words": words}


def rows_by_name(vendor, lines):
    return {row.raw_name: row for row in parse_document(vendor, "laboratory", [layout(lines)])}


ESKULAB_HEADER = (195.0, "Показник@28.3 Результат@231.0 Одиниці@316.3 Референтні@416.6 значення@480.7")


# --- 1. A «<1» result keeps its comparator ------------------------------------


def test_eskulab_less_than_result_keeps_its_comparator():
    """«Гідроксилізин <1 мкмоль/л» was stored as the measured value 1, and calprotectin
    «<24.0» as 24.0: `parse_decimal` strips the «<» and `_numeric_observation` dropped it."""
    rows = rows_by_name("EskuLab", [
        ESKULAB_HEADER,
        (217.0, "Гідроксилізин@28.3 <1@248.7 мкмоль/л@321.0 <24@378.4 міс.:@395.0 <4@420.0"),
        (220.0, "сироватка@120.0 крові@160.0"),
        (228.0, "2-17@378.4 років:@395.0 <3@425.0"),
        (240.0, "≥18@378.4 років:@395.0 <2@425.0"),
        (251.0, "Гідроксипролін@28.3 8@250.1 мкмоль/л@321.0 <24@378.4 міс.:@395.0 8-61@420.0"),
        (254.0, "сироватка@120.0 крові@160.0"),
    ])
    assert (rows["Гідроксилізин"].comparator, rows["Гідроксилізин"].value_numeric) == ("<", 1.0)
    assert rows["Гідроксипролін"].comparator is None


# --- 3. The specimen label never joins the name; a stool test keeps its whole scale --------


def test_eskulab_stool_specimen_is_not_part_of_the_name():
    """«Приносний» / «матеріал, кал» wrapped back to the margin and was read as more of the
    name; «кал» was missing from the specimen vocabulary.  The same miss treated the
    indented «Приносний матеріал, кал» under calprotectin as a second table and cut its
    reference scale off after the first band."""
    rows = rows_by_name("EskuLab", [
        ESKULAB_HEADER,
        (217.0, "1.@28.3 Кальпротектин@39.8 <24.0@243.5 мг/кг@325.7 негативний:@378.4 <@426.2 50@434.3"),
        (220.0, "Приносний@113.0 матеріал,@149.7 кал@181.8"),
        (228.0, "Час@28.3 відбору:@41.3 09:00@69.3 сумнівний:@378.4 50-120@420.5"),
        (239.0, "позитивний:@378.4 >@426.5 120@434.6"),
        (249.0, "2.@28.3 Панкреатична@39.8 еластаза@110.7 (кал)@156.4 45.83@244.4 мкг@298.0 Ел/г@315.0 калу@332.0 >@378.4 200@386.5"),
        (252.0, "Приносний@180.1"),
        (264.0, "матеріал,@28.3 кал@60.5"),
        (272.0, "Час@28.3 відбору:@41.3 09:00@69.3 100@378.4 -@394.0 200@398.7"),
        (290.0, "Хелікобактер@28.3 пілорі,@80.0 кал@112.0 не@235.0 виявлено@246.0 не@378.4 виявлено@389.5"),
        (293.0, "Приносний@150.0"),
        (305.0, "матеріал,@28.3 кал@60.5"),
    ])
    assert "Панкреатична еластаза (кал)" in rows
    assert "Хелікобактер пілорі, кал" in rows
    assert not [name for name in rows if "матеріал" in name]
    assert rows["Панкреатична еластаза (кал)"].specimen == "кал"
    calprotectin = rows["Кальпротектин"]
    assert (calprotectin.comparator, calprotectin.value_numeric) == ("<", 24.0)
    assert calprotectin.reference_text == "негативний: < 50 сумнівний: 50-120 позитивний: > 120"


# --- 5. Panel numbering in front of a chemical position ------------------------


def test_eskulab_numbering_before_a_chemical_position_is_stripped():
    """«2. 25-Гідроксивітамін D (Вітамін D» / «загальний)»: the numbering was only stripped
    before a letter, so the name kept «2. » and the row was rejected outright."""
    rows = rows_by_name("EskuLab", [
        ESKULAB_HEADER,
        (275.0, "2.@28.3 25-Гідроксивітамін@39.8 D@132.6 (Вітамін@142.4 D@183.3 35.3@247.2 нг/мл@324.9"),
        (278.0, "Ризик@378.4 дефіциту:@401.9 <@441.0 10.0@449.1 Дорослі:@472.7 30.0-50.0@506.0"),
        (286.0, "загальний)@28.3 Ризик@378.4 недостатнього@401.9 Інтоксикація:@472.7 >150.0@524.3"),
        (290.0, "сироватка@81.0 крові@115.5"),
        (299.0, "вживання:@378.4 <@419.7 30.0@427.8"),
    ])
    vitamin_d = rows["25-Гідроксивітамін D (Вітамін D загальний)"]
    assert vitamin_d.value_numeric == 35.3
    assert vitamin_d.specimen == "сироватка крові"


# --- 6. «крові» at the margin: name tail or specimen tail -----------------------


def test_eskulab_margin_specimen_word_ends_the_name_until_the_specimen_starts():
    """«Концентрація Ig А в сироватці» / «крові» (margin) / «сироватка крові» (indented):
    «крові» finishes the name.  Under TSH, «сироватка» (indented) / «крові» (margin) is the
    specimen wrapping, and stays out of the name."""
    rows = rows_by_name("EskuLab", [
        ESKULAB_HEADER,
        (209.0, "1.@28.3 Тиреотропний@39.8 гормон@110.6 (TSH)@147.5 1.02@247.2 мкМО/мл@300.0"),
        (212.0, "сироватка@172.5 Дорослі:@378.4 0,27@410.0 -@430.0 4,2@436.0"),
        (224.0, "крові@28.3"),
        (240.0, "2.@28.3 Концентрація@39.8 Ig@108.4 А@119.6 в@128.6 сироватці@136.8 2.28@247.2 г/л@331.3 Дорослі:@378.4 0,70-4,0@410.0"),
        (249.0, "крові@28.3"),
        (252.0, "сироватка@52.8 крові@87.3"),
    ])
    assert "Тиреотропний гормон (TSH)" in rows
    assert rows["Концентрація Ig А в сироватці крові"].value_numeric == 2.28
    assert rows["Концентрація Ig А в сироватці крові"].specimen == "сироватка крові"


# --- 2. Synevo coprogram: the wrapped result wins over the norm -----------------


SYNEVO_HEADER = (136.0, "Показник@124 Результат@275 Од.@358 Референтний@442 інтервал@491")
COPROGRAM = [
    SYNEVO_HEADER,
    (170.0, "Аналіз@69 калу@97 на@116 кишкові@128 паразити@161"),
    (196.0, "Вегетативні@75 форми@122 і@150 цисти@154 не@270 виявлені@281 не@392 виявлені@402"),
    (207.0, "найпростіших@75"),
    (239.0, "Копрограма@69"),
    (255.0, "Форма@75 не@262 оформлений@273 оформлений@392"),
    (308.0, "Запах@75 специфічний@268 специфічний@392 каловий@436"),
    (320.0, "каловий@277"),
    (332.0, "Реакція@75 слабокисла@270 нейтральна@392"),
    (350.0, "pH@75 6.75@285 7.@392 0@400 -@406 7.5:@410 в@424 нормі@430 нейтральна@450"),
    (361.0, "5.5@392 –@404 6.75:@410 кисла@427"),
    (372.0, "<@392 5.5:@398 різко@412 кисла@430"),
    (404.0, "Сполучна@75 тканина@114 не@269 виявлена@280 не@392 виявлена@402"),
    (481.0, "Жирні@75 кислоти@100 в@270 невеликій@277 не@392 виявлені@402"),
    (493.0, "кількості@276"),
    (567.0, "Крохмальні@75 зерна@120 позаклітинні@144 поодинокі@270 в@312 не@392 виявлені@402"),
    (579.0, "препараті@274"),
    (663.0, "Лейкоцити@75 (копрограма)@117 не@252 виявлені@262 (в@293 нормі@301 -@322 не@326 виявлені)@336"),
    (726.0, "Дріжджовий@75 грибок@122 виявлений@268 в@313 не@392 виявлений@402"),
    (739.0, "невеликій@274"),
    (750.0, "кількості@276"),
    (764.0, "Яйця@75 гельмінтів@97 не@270 виявлені@281 не@392 виявлені@402"),
    (782.0, "Результати@62 лабораторних@92 досліджень@129 не@160 є@167 достатньою@171 діагнозу.@270"),
]


def test_synevo_coprogram_wrapped_result_is_the_value_not_the_norm():
    """Yeast the laboratory found («виявлений в невеликій кількості») was stored as
    «не виявлений», the norm, under the name «Дріжджовий грибок виявлений в»."""
    rows = rows_by_name("Synevo", COPROGRAM)
    found = {name: (row.value_text, row.reference_text) for name, row in rows.items()}
    assert found["Дріжджовий грибок"] == ("виявлений в невеликій кількості", "не виявлений")
    assert found["Жирні кислоти"] == ("в невеликій кількості", "не виявлені")
    assert found["Крохмальні зерна позаклітинні"] == ("поодинокі в препараті", "не виявлені")
    assert found["Вегетативні форми і цисти найпростіших"] == ("не виявлені", "не виявлені")
    assert found["Запах"] == ("специфічний каловий", "специфічний каловий")
    # The bracket is printed in the result cell, not the reference column: it is
    # no reference (review 2026-11-07, second pass).
    assert found["Лейкоцити (копрограма)"] == ("не виявлені", None)
    # Rows the categorical vocabulary does not know are read at all now.
    assert found["Форма"] == ("не оформлений", "оформлений")
    assert found["Реакція"] == ("слабокисла", "нейтральна")
    # The misreads are gone, not kept beside the right rows.
    assert not [name for name in rows if name.endswith((" в", " невеликій")) or name.startswith("pH ")]
    assert not [name for name in rows if name.startswith(("Результати", "Копрограма", "Аналіз калу"))]


def test_synevo_coprogram_ph_scale_gives_a_value_and_no_bounds():
    """pH printed its value with a five-band scale; the first pair of numbers in «7. 0 -
    7.5» reads as 0 - 7.5, which would put an acidic 6.75 inside the normal range."""
    ph = rows_by_name("Synevo", COPROGRAM)["pH"]
    assert ph.value_numeric == 6.75 and ph.value_text is None and ph.unit_raw is None
    assert ph.reference_text.startswith("7. 0 - 7.5: в нормі")
    assert "5.5 – 6.75: кисла" in ph.reference_text
    assert (ph.reference_low, ph.reference_high) == (None, None)


def test_synevo_rows_with_a_unit_stay_with_the_text_passes():
    rows = rows_by_name("Synevo", [
        SYNEVO_HEADER,
        (410.0, "Еритроцити@75 (RBC)@122 5.06@285 10^12@352 Дорослі:@392 3.7@430 -@442 4.7@448"),
        (422.0, "клітин/л@349"),
        (654.0, "Звіт@69 з@86.8 описом@92.9 лабораторних@124 Ваш@264 результат@282.8"),
        (666.0, "готовий@275 і@308"),
    ])
    assert rows["Еритроцити (RBC)"].value_numeric == 5.06
    assert not [name for name in rows if name.startswith("Звіт")]


# --- 4. Ekspert blood count with a «РЕФЕРЕНТНІ ЗНАЧЕННЯ» header ---------------


EXPERT_CBC = [
    (168.0, "ПОКАЗНИК@124.5 РЕЗУЛЬТАТ@316.6 РЕФЕРЕНТНІ@441.1 ЗНАЧЕННЯ@495.1"),
    (180.0, "Лейкоцити@17.1 (WBC),@65.7 х@95.7 10*9/л@102.3 10,05@329.5 від@470.2 4@485.2 до@492.4 9@505.6"),
    (204.0, "Абсолютне@17.1 значення@66.3 суміші@108.3 (моноцити,@138.3 базофіли@188.7 та@230.2"),
    (209.0, "1,9@334.3 від@463.0 0,1@478.0 до@492.4 0,9@505.6"),
    (215.0, "еозинофіли)@17.1 (MID#),@72.3 х@104.7 10*9/л@111.3"),
    (322.0, "Середній@17.1 об'єм@57.9 еритроцита@83.7 (MCV),@133.5 F/л@162.9 83,1@331.9 від@465.7 76@480.7 до@492.7 96@505.3"),
    (334.0, "Середній@17.1 вміст@57.9 гемоглобіну@81.9 в@134.7 еритроциті@141.9 (MCH),@189.3 pg@219.4 27,1@331.9 від@465.7 27@480.7 до@492.7 33@505.3"),
    (465.0, "ШОЕ,@17.1 мм/год@41.7 4,0@334.3 від@468.1 2@483.1 до@490.3 15@502.9"),
    (561.0, "Результати@17.1 досліджень@64.5 не@115.5 є@128.1 клінічним@134.7 діагнозом@178.5"),
]


def test_expert_blood_count_with_referentni_znachennya_header_is_read():
    """One Ekspert blood count printed «РЕФЕРЕНТНІ ЗНАЧЕННЯ» where other panels print «НОРМА»; the
    header was matched word for word, so 27 results yielded nothing at all."""
    rows = rows_by_name("Expert Hospital", EXPERT_CBC)
    assert (rows["Лейкоцити (WBC)"].value_numeric, rows["Лейкоцити (WBC)"].unit_raw) == (10.05, "х 10*9/л")
    assert (rows["Лейкоцити (WBC)"].reference_low, rows["Лейкоцити (WBC)"].reference_high) == (4.0, 9.0)
    mid = rows["Абсолютне значення суміші (моноцити, базофіли та еозинофіли) (MID#)"]
    assert (mid.value_numeric, mid.reference_high) == (1.9, 0.9)
    assert (rows["Середній об'єм еритроцита (MCV)"].value_numeric, rows["Середній об'єм еритроцита (MCV)"].unit_raw) == (83.1, "F/л")
    assert rows["Середній вміст гемоглобіну в еритроциті (MCH)"].unit_raw == "pg"
    assert rows["ШОЕ"].value_numeric == 4.0


def test_expert_referentni_znachennya_header_also_reaches_the_text_passes():
    """A page without word positions (a scan) falls back to the text passes, which had the
    same literal header check."""
    page = layout(EXPERT_CBC)
    del page["words"]
    rows = {row.raw_name: row for row in parse_document("Expert Hospital", "laboratory", [page])}
    assert rows["Лейкоцити (WBC)"].value_numeric == 10.05
    assert rows["ШОЕ"].value_numeric == 4.0


# --- Synevo units the allowlist lacked, and the rows they took with them -------


SYNEVO_TEXT_HEADER = "Показник Результат Од. Референтний інтервал\n"


def synevo_text_rows(body):
    page = {"page_number": 1, "native_text": SYNEVO_TEXT_HEADER + body, "ocr_text": ""}
    return {row.raw_name: row for row in parse_document("Synevo", "laboratory", [page])}


def test_synevo_rows_in_ng_dl_micro_units_and_units_per_ml_are_read():
    """«нг/дл», «мкОд/мл» and «Од/мл» were not in the unit allowlist, so free T4, insulin
    and the CA 15-3 / CA 125 markers were dropped with no observation and no review task."""
    rows = synevo_text_rows(
        "Тироксин вільний (T4 вільний) 1.22 нг/дл Дорослі: 0.93 - 1.7\n"
        "Інсулін 6.45 мкОд/мл 2.6 - 24.9\n"
        "Онкомаркер молочної залози (СА 15-3) 17.4 Од/мл <26.2\n"
        "Онкомаркер яєчників (СА 125) 18.3 Од/мл <35.0\n"
    )
    assert (rows["Тироксин вільний (T4 вільний)"].value_numeric, rows["Тироксин вільний (T4 вільний)"].unit_raw) == (1.22, "нг/дл")
    assert (rows["Інсулін"].value_numeric, rows["Інсулін"].unit_raw) == (6.45, "мкОд/мл")
    assert (rows["Інсулін"].reference_low, rows["Інсулін"].reference_high) == (2.6, 24.9)
    assert (rows["Онкомаркер молочної залози (СА 15-3)"].value_numeric, rows["Онкомаркер молочної залози (СА 15-3)"].reference_high) == (17.4, 26.2)
    assert rows["Онкомаркер яєчників (СА 125)"].unit_raw == "Од/мл"


def test_new_cyrillic_units_fold_onto_their_latin_spelling_only():
    from anamna.reference import canonical_unit

    assert canonical_unit("нг/дл") == canonical_unit("ng/dL")
    assert canonical_unit("Од/мл") == canonical_unit("U/mL")
    assert canonical_unit("мкОд/мл") == canonical_unit("µU/mL")
    # Micro-units are not micro-international units in general; that
    # equivalence is per assay, so it is not a global fold.
    assert canonical_unit("мкОд/мл") != canonical_unit("мкМО/мл")
    # Bare «Од» stays "units" and «Од/л» stays U/L.
    assert canonical_unit("Од") == "units"
    assert canonical_unit("Од/л") == canonical_unit("U/L")


def test_synevo_comma_label_takes_the_abbreviation_after_its_lowercase_tail():
    """«Пероксидаза щитоподібної залози,» / «антитіла (АТПО) Метод: ...»: the tail stopped at
    the bracket, so the row was named without the abbreviation the lab files it under."""
    rows = synevo_text_rows(
        "Пероксидаза щитоподібної залози, < 9 МО/мл <34.0\n"
        "антитіла (АТПО) Метод: Електрохемілюмінесцентний аналіз\n"
    )
    row = rows["Пероксидаза щитоподібної залози, антитіла (АТПО)"]
    assert (row.comparator, row.value_numeric, row.reference_high) == ("<", 9.0, 34.0)


def test_synevo_genotype_under_its_own_pcr_heading_is_read():
    """A genotype printed under its PCR heading with no norm («ПЛР. Фолатний цикл. MTRR
    (66 A>G)» over «Гомозиготне носійство») was dropped: the column reader skips a row with
    no reference, and the categorical vocabulary does not know the phrase."""
    rows = rows_by_name("Synevo", [
        SYNEVO_HEADER,
        (152.0, "ПЛР.@69 Фолатний@89.6 цикл.@130.6 MTRR@153.4 (66@178.1 A>G)@191.6"),
        (167.0, "Гомозиготне@251.8 носійство@299.6"),
        (185.0, "Примітка:@75"),
    ])
    assert rows["ПЛР. Фолатний цикл. MTRR (66 A>G)"].value_text == "Гомозиготне носійство"


def test_synevo_illustrated_companion_report_yields_no_rows():
    """The companion PDF re-presents the main report as two summary tables side by side.
    Read as text the columns interleave: a patient's name joined an analyte label and free
    T4 was stored under «HBsAg».  Every value is in the main report, so none is read here."""
    page = {
        "page_number": 10,
        "ocr_text": "",
        "native_text": (
            "Інформація про клієнта Kоагуляція Результат Норма\n"
            "ПІБ Пацієнт Тестовий Протромбіновий час 12.4 9.8 - 12.1 сек\n"
            "HBsAg 0.372 T4 вільний 1.22 0.93-1.7\n"
            "Лужна фосфатаза 49 35-104 Од/л CA15-3 17.4 <26.2 Од/мл\n"
            "Пацієнт Тестовий / Пакет № 100 (Тестовий пакет) / 01.01.2000 / cтор. 10\n"
        ),
    }
    issues: list = []
    assert parse_document("Synevo", "laboratory", [page], issues=issues) == []
    # The empty document says what it is, not that the parser missed a panel.
    from anamna.ingest.pipeline import _ingest_review_reasons

    reasons = _ingest_review_reasons(None, [], 0, None, issues)
    assert [reason["key"] for reason in reasons] == ["review.companion_summary"]


def test_synevo_spellings_of_free_t4_and_anti_tpo_resolve_to_their_concepts():
    """Read but unmapped, each would start a nameless concept of its own beside the one the
    record already files these analytes under."""
    from anamna.ingest.concepts import concept_for_alias

    assert concept_for_alias("Тироксин вільний (T4 вільний)", "numeric")["name"] == "Free thyroxine"
    tpo = concept_for_alias("Пероксидаза щитоподібної залози, антитіла (АТПО)", "numeric")
    assert tpo["name"] == "Thyroid peroxidase antibodies"
