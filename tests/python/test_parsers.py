from anamna.ingest.concepts import CONCEPT_DEFINITIONS
from anamna.ingest.parsers import (
    ESKULAB_GLUE,
    NON_NORMAL_BAND_RE,
    ParsedObservation,
    parse_document,
    parse_pcr_sections,
    parse_unit_rows,
    reference_bounds,
)
from anamna.ingest.pipeline import interpretation
from anamna.reference import canonical_unit


def page(text: str):
    return [{"page_number": 1, "native_text": text}]


def hybrid_page(native_text: str, ocr_text: str):
    return [{"page_number": 1, "native_text": native_text, "ocr_text": ocr_text}]


def test_ana_uses_categorical_thresholds_instead_of_numeric_low_range():
    observation = ParsedObservation(
        raw_name="Antinuclear antibodies",
        value_numeric=0.89,
        value_text=None,
        comparator=None,
        unit_raw="index",
        reference_text="Negative <1.0; equivocal 1.0–1.2; positive >1.2",
        reference_low=1.0,
        reference_high=1.2,
        page_number=1,
        evidence_text="ANA 0.89",
        confidence=0.99,
    )

    # Keyed on the concept: the printed label is no longer the English one.
    assert interpretation(observation, "antinuclear-antibodies") == "within_vendor_range"


def test_st_paraskeva_cbc_form_parses_numeric_table():
    observations = parse_document(
        "St. Paraskeva Medical Center",
        "laboratory",
        page(
            """
            ФОРМА № 225/о
            ШОЕ (ESR) мм/год 6,0 0 - 15.0
            Гемоглобін(HGB): г/л 152,0 130,0 - 165,0
            Гематокрит (НСТ): % 44,9 35,0 - 54,0
            """
        ),
    )
    # Stored under the label the form prints, not an English substitute.
    values = {item.raw_name: item.value_numeric for item in observations}
    assert values == {
        "ШОЕ (ESR)": 6.0,
        "Гемоглобін(HGB)": 152.0,
        "Гематокрит (НСТ)": 44.9,
    }


def test_garmin_blood_pressure_keeps_measurement_datetime():
    observations = parse_document(
        "Garmin Connect",
        "blood_pressure",
        page("7 лип. 2024\n22:37 118 Сис. / 75 Діас. 93 bpm Нормальний"),
    )
    numeric = {item.raw_name: item for item in observations if item.value_numeric is not None}
    assert numeric["Systolic blood pressure"].value_numeric == 118
    assert numeric["Diastolic blood pressure"].value_numeric == 75
    assert numeric["Pulse rate"].value_numeric == 93
    assert numeric["Systolic blood pressure"].observed_at == "2024-07-07T22:37:00"


def test_kardia_ecg_keeps_the_rhythm_it_was_recorded_to_find():
    """A 6-lead ECG that enters the record as one number is not an ECG.

    This test used to assert `len(observations) == 1` with the determination
    sitting in its own fixture text, unread: the parser took the pulse rate and
    dropped "Normal Sinus Rhythm", so the whole reason for taking the recording
    -- the rhythm -- was in the stored page text and nowhere a person could see
    it.  A pulse rate is what a finger on a wrist produces.
    """
    observations = parse_document(
        "Kardia",
        "electrocardiogram",
        page(
            """EKG Recording Overview
            Recorded on:
            Monday, Aug 03, 2026, 1:44 PM
            Heart Rate:
            77 BPM
            Duration:
            30s
            Kardia Advanced Determination:
            Normal Sinus Rhythm
            * Kardia Advanced Determination is done on Lead I."""
        ),
    )
    by_name = {item.raw_name: item for item in observations}
    # The recording's duration is metadata about the recording, not a
    # measurement of the person (DOCC-35): it travels as the rhythm's note.
    assert set(by_name) == {"Pulse rate", "Heart rhythm"}
    assert by_name["Pulse rate"].value_numeric == 77
    assert by_name["Heart rhythm"].value_text == "Normal Sinus Rhythm"
    # The footnote begins with "*" on the same capture; stopping at it is what
    # keeps the stored result from carrying a sentence about Lead I.
    assert "Lead I" not in (by_name["Heart rhythm"].value_text or "")
    assert by_name["Heart rhythm"].note == "Duration: 30s"
    # Every one of them is the same recording, so they share its timestamp.
    assert {item.observed_at for item in observations} == {"2026-08-03T13:44:00"}


def test_an_abnormal_kardia_determination_is_read_the_same_way():
    """The normal result is the one that must not be the only one it can read."""
    observations = parse_document(
        "Kardia",
        "electrocardiogram",
        page(
            """EKG Recording Overview
            Recorded on:
            Monday, Aug 03, 2026, 1:44 PM
            Heart Rate:
            132 BPM
            Duration:
            30s
            Kardia Advanced Determination:
            Atrial Fibrillation"""
        ),
    )
    by_name = {item.raw_name: item for item in observations}
    assert by_name["Heart rhythm"].value_text == "Atrial Fibrillation"
    assert by_name["Pulse rate"].value_numeric == 132


def test_expert_numeric_and_categorical_rows_are_typed():
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Глікований гемоглобін (HbA1C) 5.60% 4.0 - 5.7
    Швидкий тест для виявлення ВІЛ І та ІІ типу Негативний Негативний результат
    Результати досліджень не є клінічним діагнозом
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))
    by_name = {item.raw_name: item for item in observations}
    # The label as printed («HbA1C») and the reference as printed.
    assert by_name["Глікований гемоглобін (HbA1C)"].value_numeric == 5.6
    assert by_name["Глікований гемоглобін (HbA1C)"].unit_raw == "%"
    assert by_name["Глікований гемоглобін (HbA1C)"].reference_text == "4.0 - 5.7"
    assert by_name["Швидкий тест для виявлення ВІЛ І та ІІ типу"].value_text == "Негативний"


def test_numeric_reference_continuations_are_not_analyte_names():
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Абсолютне значення суміші (MID#),
    0,6 від 0,1 до 0,9
    х 10*9/л
    Результати досліджень не є клінічним діагнозом
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))
    assert all(not item.raw_name[0].isdigit() for item in observations)


def test_pcr_section_uses_section_heading_not_instrument_name():
    text = """
    Показник Результат Одиниці Референтні значення
    Виявлення ДНК Ureaplasma parvum (ПЛР) (кількісне визначення)
    Вид дослідження U.parvum
    Метод дослідження ПЛР в реальному часі
    Прилад Rotor-Gene 6000
    Результат не виявлено ГЄ/мл
    Дослідження виконала(-ли) Лаборант
    """
    observations = parse_document("EskuLab", "laboratory", page(text))
    assert len(observations) == 1
    assert observations[0].raw_name.startswith("Виявлення ДНК Ureaplasma parvum")
    assert observations[0].value_text == "не виявлено"


def test_categorical_parser_rejects_embedded_numeric_reference_lines():
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Вірус гепатиту B (HBV), HBsAg 0.312 COI <0.9 Негативний
    Вірус паротиту, антитіла IgM 0.36 R R < 0.8 Негативний
    Гепатит B, ПЛР Не виявлено Не виявлено
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))

    assert [(item.raw_name, item.value_text) for item in observations if item.value_text] == [
        ("Гепатит B, ПЛР", "Не виявлено")
    ]


def test_expert_urinalysis_microscopy_and_dipstick_rows_are_not_swallowed():
    """Five of thirty rows on urinalysis 4239932 vanished without a trace.

    Each line below is verbatim from the source page.  «в нормі» was missing
    from CATEGORICAL_VALUE, and no pass accepted an HPF range (0-1, 0-0-1,
    0-1-2) or a bare «+» as a value -- so the rows produced no observation, no
    review task, no error.  The mucus «+», present against a «не виявлено»
    reference, was an abnormal finding entirely absent from the record.
    """
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Глюкоза, ммоль/л в нормі
    Еритроцити не змінені, в п/з 0-0-1 0-2
    Лейкоцити (WBC), в п/з 0-1 0-5
    Клітини плоского епітелію, в п/з 0-1-2 (не виявлено ); 1-15
    Слиз, в п/з + (не виявлено)
    Результати досліджень не є клінічним діагнозом
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))
    by_name = {item.raw_name: item for item in observations}
    assert by_name["Глюкоза"].value_text == "в нормі"
    assert by_name["Еритроцити не змінені"].value_text == "0-0-1"
    assert by_name["Лейкоцити (WBC)"].value_text == "0-1"
    assert by_name["Клітини плоского епітелію"].value_text == "0-1-2"
    assert by_name["Слиз"].value_text == "+"
    # Microscopy ranges are counts per field, never a single number.
    assert all(item.value_numeric is None for item in observations)


def test_expert_unit_behind_a_comma_is_split_off_the_name():
    """Result 4239932 printed «<name>, <unit>» and the unit stayed in the name.

    Lines verbatim from the page.  The hospital's own structured record names
    these «Питома вага» in «г/мл», «Лейкоцити (WBC)» in «в п/з», «Лейкоцити в
    сечі» in «кл/мкл» -- the unit is a unit, not part of what was measured.
    """
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Питома вага, г/мл 1,035 від 1,01 до 1,03
    Білок в сечі, г/л негативний
    Лейкоцити в сечі, кл/мкл негативний
    Нітрити, ммоль/л негативний негативний
    Еритроцити змінені, в п/з 0 0-2
    Лейкоцити (WBC), в п/з 0-1 0-5
    Клітини перехідного епітелію , в п/з не виявлено (не виявлено ); 1-15
    Результати досліджень не є клінічним діагнозом
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))
    rows = {item.raw_name: (item.value_numeric, item.value_text, item.unit_raw) for item in observations}
    # The unit leaves the name either way; a word result keeps none at all
    # ("Not detected mg/dL" is not a quantity, CLIN-30), while a count or an
    # HPF range keeps the unit it is a count in.
    assert rows == {
        "Питома вага": (1.035, None, "г/мл"),
        "Білок в сечі": (None, "негативний", None),
        "Лейкоцити в сечі": (None, "негативний", None),
        "Нітрити": (None, "негативний", None),
        "Еритроцити змінені": (0.0, None, "в п/з"),
        "Лейкоцити (WBC)": (None, "0-1", "в п/з"),
        "Клітини перехідного епітелію": (None, "не виявлено", None),
    }
    # Folded, or they would start second series: «в п/з» is the HPF unit the
    # app already knew, and «г/мл» joins the unitless specific gravity every
    # other laboratory here prints.
    assert canonical_unit("в п/з") == canonical_unit("per HPF")
    assert canonical_unit("г/мл") == canonical_unit(None)


def test_expert_wrapped_mid_label_keeps_its_code_and_unit():
    """The MID rows wrap, and the line under the value says which one it was.

    Text as pdfplumber stores it for results 4278372 (code wrapped below) and
    4990495 (code on the first line, unit alone below).  The name's first line
    is identical for the count and the fraction, so without the tail a 0.7
    ×10⁹/L count and an 11 % fraction become one analyte with no unit -- the
    Synevo RDW-SD/RDW-CV trap in another laboratory's layout.
    """
    head_abs = "Абсолютне значення суміші (моноцити, базофіли та еозинофіли)"
    head_rel = "Відносне значення суміші (моноцити, базофіли та еозинофіли)"
    code_below = f"""
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    Абсолютне значення лімфоцитів (LYM#), х 10*9/л 2,5 від 0,6 до 4,1
    {head_abs}
    0,7 від 0,1 до 0,9
    (MID#), х 10*9/л
    Абсолютне значення гранулоцитів (GRA#), х 10*9/л 3,3 від 2 до 7,8
    Відносне значення лімфоцитів (LYM%), % 37,8 від 20 до 50
    {head_rel}
    11,0 від 3 до 10
    (MID%), %
    Відносне значення гранулоцитів (GRA%), % 51,2 від 40 до 70
    Результати досліджень не є клінічним діагнозом
    """
    code_above = f"""
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    {head_abs} (MID#),
    0,6 від 0,1 до 0,9
    х 10*9/л
    Абсолютне значення гранулоцитів (GRA#), х 10*9/л 3,3 від 2 до 7,8
    {head_rel} (MID%),
    9,0 від 3 до 10
    %
    Відносне значення гранулоцитів (GRA%), % 51,0 від 40 до 70
    Результати досліджень не є клінічним діагнозом
    """
    # The same wrap with the tail printed above the value line instead.
    tail_first = f"""
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    {head_abs} (MID#),
    х 10*9/л
    0,6 від 0,1 до 0,9
    {head_rel}
    (MID%), %
    9,0 від 3 до 10
    Результати досліджень не є клінічним діагнозом
    """
    for text, absolute, relative in (
        (code_below, 0.7, 11.0), (code_above, 0.6, 9.0), (tail_first, 0.6, 9.0)
    ):
        rows = {
            item.raw_name: (item.value_numeric, item.unit_raw)
            for item in parse_document("Expert Hospital", "laboratory", page(text))
        }
        assert rows[f"{head_abs} (MID#)"] == (absolute, "х 10*9/л")
        assert rows[f"{head_rel} (MID%)"] == (relative, "%")
        # Neither the cut-off name nor a unit-as-name survives anywhere.
        assert head_abs not in rows and head_rel not in rows
        assert not any(name.startswith(("х ", "(", "%")) for name in rows)
    neighbours = {
        item.raw_name: (item.value_numeric, item.unit_raw)
        for item in parse_document("Expert Hospital", "laboratory", page(code_below))
    }
    assert neighbours["Абсолютне значення гранулоцитів (GRA#)"] == (3.3, "х 10*9/л")
    assert neighbours["Відносне значення лімфоцитів (LYM%)"] == (37.8, "%")
    assert len(neighbours) == 6


def test_expert_label_without_a_unit_is_not_given_one():
    """Liver enzymes print no unit anywhere; nothing below may lend them one."""
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    АСАТ(АСТ) 21,0 до 40
    АЛАТ(АЛТ) 25,0 до 41
    Глюкоза, ммоль/л 5,1 від 3,3 до 5,5
    Результати досліджень не є клінічним діагнозом
    """
    rows = {
        item.raw_name: (item.value_numeric, item.unit_raw)
        for item in parse_document("Expert Hospital", "laboratory", page(text))
    }
    assert rows == {
        "АСАТ(АСТ)": (21.0, None),
        "АЛАТ(АЛТ)": (25.0, None),
        "Глюкоза": (5.1, "ммоль/л"),
    }


def test_other_vendors_are_untouched_by_the_expert_unit_rules():
    """The categorical split and the new units are shared code; outputs of a
    Synevo page are the same as before them (checked against the previous
    parser, and over every document in the record)."""
    text = """
    Показник Результат Одиниці Референтні значення
    Гемоглобін (HGB) 152 г/л 130 - 160
    Ширина розподілення еритроцитів 36.6 фл 35.0 - 46.0
    (RDW-SD)
    Вірус гепатиту C (HCV), антитіла сумарні негативний
    Абсолютне значення суміші (моноцити, базофіли та еозинофіли)
    0,7 від 0,1 до 0,9
    (MID#), х 10*9/л
    """
    rows = sorted(
        (item.raw_name, item.value_numeric, item.value_text, item.unit_raw)
        for item in parse_document("Synevo", "laboratory", page(text))
    )
    # The MID lines are Expert's layout and stay unread here, as before.
    assert rows == [
        ("Вірус гепатиту C (HCV), антитіла сумарні", None, "негативний", None),
        ("Гемоглобін (HGB)", 152.0, None, "г/л"),
        ("Ширина розподілення еритроцитів (RDW-SD)", 36.6, None, "фл"),
    ]


def test_synevo_rdw_tail_on_the_next_line_separates_sd_from_cv():
    """Two Synevo rows print an identical first line; the tail is the truth.

    Without NAME_CONTINUATION both resolve to RDW-CV and a 36.6 fL spread is
    published as 36.6 % -- four times the upper limit, an alarm raised over a
    normal result.
    """
    observations = parse_document(
        "Synevo",
        "laboratory",
        page(
            "Ширина розподілення еритроцитів 36.6 фл 35.0 - 46.0\n"
            "(RDW-SD)\n"
            "Ширина розподілення еритроцитів 12.1 % 12.0 - 15.0\n"
            "(RDW-CV)\n"
        ),
    )
    by_unit = {item.unit_raw: item for item in observations}
    assert by_unit["фл"].raw_name.endswith("(RDW-SD)")
    assert by_unit["фл"].value_numeric == 36.6
    assert by_unit["%"].raw_name.endswith("(RDW-CV)")
    assert by_unit["%"].value_numeric == 12.1


def test_hybrid_pdf_uses_embedded_table_without_conflating_native_text():
    native = "ЕКСПЕРТ Результати дослідження №4990429"
    ocr = """
    Назва дослідження Результат Одиниці вимірювання Референтні значення
    Kanin (ioHi30BaHUN) (K) сироватка крові 5.9 ммоль/л 3.8-5.0
    Натрій (іонізований) (Ма) сироватка крові 146 ммоль/л 135.0-156.5
    Кальцій іонізований (сироватка) 1.32 ммоль/л 1,16-1,32
    """
    observations = parse_document(
        "Expert Hospital", "laboratory", hybrid_page(native, ocr)
    )
    by_name = {item.raw_name: item for item in observations}

    assert by_name["Калій (іонізований) (K), сироватка крові"].value_numeric == 5.9
    assert by_name["Натрій (іонізований) (Na), сироватка крові"].value_numeric == 146
    assert by_name["Кальцій іонізований (сироватка)"].value_numeric == 1.32
    assert all(item.extraction_method == "embedded_image_ocr_parser" for item in observations)
    assert all(item.confidence <= 0.90 for item in observations)


def test_wrapped_hba1c_result_is_read_after_analyte_heading():
    text = """
    ПОКАЗНИК РЕЗУЛЬТАТ НОРМА
    < 5.7% – здорове населення
    Глікований гемоглобін (HbA1c)цільна
    5.24% 5.7% - 6.5% - предіабет
    кров
    > 6.5% - при цукровому діабеті
    """
    observations = parse_document("Expert Hospital", "laboratory", page(text))
    hba1c = [item for item in observations if item.raw_name == "Глікований гемоглобін (HbA1c)"]
    assert len(hba1c) == 1
    assert hba1c[0].value_numeric == 5.24
    # The printed scale, never a constant (DOCB-03); the specimen split off.
    assert hba1c[0].reference_text == (
        "< 5.7% – здорове населення 5.7% - 6.5% - предіабет > 6.5% - при цукровому діабеті"
    )
    assert hba1c[0].reference_high == 5.7 and hba1c[0].reference_high_inclusive is False
    assert hba1c[0].specimen == "цільна кров"


def test_alex_panel_parses_each_result_line_and_total_ige():
    text = """
    Позначення E/M Алерген Сімейство білків kUA/L
    Цинодон пальчатий Cyn d 0,11
    Cyn d 1 Beta-Expansin 0,12
    Пажитниця багаторічна Lol p 1 Beta-Expansin < 0,10
    < 0,10
    Mal d 3 nsLTP
    Загальний IgE: 39 kU/L
    Дорослі: < 100 kU/l
    """
    observations = parse_document("Synevo", "allergy", page(text))
    assert len(observations) == 5
    assert observations[2].comparator == "<"
    assert observations[2].value_numeric == 0.10
    assert observations[3].raw_name == "Mal d 3 nsLTP"
    assert observations[4].raw_name == "Загальний IgE"
    assert observations[4].reference_high == 100


def test_microbiology_narrative_no_growth_is_not_result_not_present():
    text = """
    Мікробіологічне дослідження сечі
    Росту аеробної та факультативно-анаеробної мікробіоти не виявлено
    """
    observations = parse_document("EskuLab", "microbiology", page(text))
    assert len(observations) == 1
    assert observations[0].value_text == "не виявлено"


def test_autoimmune_ocr_recovers_collapsed_decimal_columns_provisionally():
    ocr = """
    антигени діапазон
    Ro/SS-A 52 0 <0.15
    La/SS-B 0 <0.15
    MPO <0 15
    U1-snRNP. <0 15
    """
    observations = parse_document(
        "Expert Hospital", "laboratory", hybrid_page("", ocr)
    )
    assert [item.raw_name for item in observations] == [
        "Ro/SS-A 52", "La/SS-B", "MPO", "U1-snRNP"
    ]
    # «<0.15» is below the assay's floor, not zero, and not a reference: the
    # value keeps its comparator.  This fixture prints no legend, so there is
    # no reference band to state.
    assert all(item.value_numeric == 0.15 and item.comparator == "<" for item in observations)
    assert all(item.reference_high is None for item in observations)
    assert all(item.extraction_method == "embedded_image_ocr_parser" for item in observations)


def test_synevo_units_outside_the_allowlist_are_not_silently_dropped():
    """Every unit below appeared on a real Synevo panel and matched nothing in
    UNIT_PATTERN, so the row was discarded with no observation, no review task
    and no error -- the failure looked like "the lab did not run that test".
    HBsAg, TSH and six CBC indices were lost this way.  The values here are
    invented; only the line shape and the units are reproduced from source.
    """
    observations = parse_document(
        "Synevo",
        "laboratory",
        page(
            """
            Показник Результат
            Вірус гепатиту B (HBV), HBsAg 0.500 COI <0.9 - негативний результат
            Тиреотропний гормон. 2.22 мкМО/мл 0.27 - 4.2
            Середній об'єм еритроцита (MCV) 88.8 фл 80.0 - 99.0
            Середній вміст гемоглобіну в еритроциті (MCH) 31.1 пг 27.0 - 34.0
            Середня концентрація гемоглобіну в еритроциті (MCHC) 33.3 г/дл 32.0 - 37.0
            Середній об'єм тромбоцитів (MPV) 11.1 фл 9.0 - 13.0
            Аналіз крові: Швидкість осідання еритроцитів 5.0 мм/год. 0 - 15
            Коефіцієнт атерогенності (КА) 3.33 Од 1.5 - 3.0
            """
        ),
    )
    parsed = {item.unit_raw: item.value_numeric for item in observations}
    assert parsed == {
        "COI": 0.5,
        "мкМО/мл": 2.22,
        "фл": 11.1,          # MCV and MPV share the unit; last row wins the key
        "пг": 31.1,
        "г/дл": 33.3,
        "мм/год.": 5.0,
        "Од": 3.33,
    }
    # MCV must survive alongside MPV rather than being collapsed into it.
    assert sorted(i.value_numeric for i in observations if i.unit_raw == "фл") == [11.1, 88.8]


def test_antibiogram_disk_potency_is_never_read_as_a_result():
    """"Бензилпеніцилін 1 од Стійкий" has the shape of a unit row, but the 1 is
    the disk potency and "Стійкий" is the finding.  Storing 1.0 Од would show a
    meaningless number and drop the resistance result entirely.
    """
    observations = parse_document(
        "EskuLab",
        "microbiology",
        page(
            """
            Бензилпеніцилін 1 од Стійкий
            Амікацин 30 мкг Чутливий
            Левофлоксацин 5 мкг Чутливий, збільшена експозиція
            """
        ),
    )
    assert [item for item in observations if item.value_numeric in (1.0, 30.0, 5.0)] == []


#: One printed spelling per unit a concept declares, chosen so the parser has
#: to accept it.  UNIT_PATTERN is an allowlist, so a concept whose unit no
#: spelling here produces is a concept whose rows are dropped in silence -- no
#: observation, no review task, no error, the page simply reads as though the
#: laboratory never ran the test.  The equality assertion below is what stops a
#: new concept from being added into that hole without anyone noticing.
UNIT_SPELLINGS = {
    "%": "%",
    "10^9/L": "10^9/L",
    "10^12/L": "10^12/L",
    "IU/mL": "IU/mL",
    "U/L": "од/л",
    "cells/µL": "кл/мкл",
    "fL": "фл",
    "g/L": "г/л",
    "index": "індекс",
    "kU/L": "kU/L",
    "mIU/L": "мкМО/мл",
    "mL": "мл",
    "mg/L": "мг/л",
    "mg/dL": "мг/дл",
    "mm/h": "мм/год",
    "mmol/L": "ммоль/л",
    "ng/mL": "нг/мл",
    "nmol/L": "нмоль/л",
    "pg": "пг",
    "pg/mL": "пг/мл",
    "pmol/L": "пмоль/л",
    "ratio": "коефіцієнт",
    "s": "сек",
    "units": "Од",
    "µmol/L": "мкмоль/л",
}

#: Units that are correctly absent from the allowlist, because no result line
#: ever carries them.  Each is written by a parser that recognises its whole
#: document -- Garmin's blood-pressure export and Kardia's ECG mint mmHg, bpm
#: and count directly -- or, for «в п/з», belongs to a microscopy result stored
#: as text ("1-2 в п/з") rather than as a number with a unit beside it.
UNITS_NOT_PRINTED_ON_A_RESULT_LINE = {"mmHg", "bpm", "count", "per HPF"}
#: Units of concepts no laboratory result line in the record carries: the eGFR
#: the record calculates itself (``anamna.derived``), and measurements a
#: narrative imaging report states in prose («Товщина КІМ справа 0,6 мм»),
#: which the line allowlist must not learn -- «мм» and «см/с» on a result line
#: are exactly the ultrasound dimensions and doses UNIT_PATTERN refuses.
UNITS_NOT_PRINTED_ON_A_RESULT_LINE |= {"mL/min/1.73m²", "mm", "cm/s", "g/m²", "mL"}
#: Left ventricular mass in grams: an echo value, and a bare «г» on a result
#: line is a drug dose the allowlist must keep refusing.
UNITS_NOT_PRINTED_ON_A_RESULT_LINE |= {"g"}
#: Vital signs and ECG intervals from visit notes.  ``parse_visit_measurements``
#: accepts each unit only behind the label or under the column that gives it
#: its meaning («Зріст: 186 см», «ЧД … 16 хв»); on a result line «см», «кг» and
#: «хв» are exactly the dimensions, doses and durations the allowlist refuses.
UNITS_NOT_PRINTED_ON_A_RESULT_LINE |= {"°C", "breaths/min", "kg", "cm", "kg/m²", "ms"}


def test_every_concept_unit_has_a_spelling_the_parser_accepts():
    declared = {str(item["unit"]) for item in CONCEPT_DEFINITIONS if item.get("unit")}
    assert declared == set(UNIT_SPELLINGS) | UNITS_NOT_PRINTED_ON_A_RESULT_LINE

    for unit, printed in UNIT_SPELLINGS.items():
        observations = parse_unit_rows(f"Гемоглобін 12.3 {printed} 1.0 - 99.0", 1)
        assert [item.unit_raw for item in observations] == [printed], unit
        # Parsing it is only half the job: an accepted spelling that does not
        # fold onto the unit its concept declares gives that analyte a second
        # unit, splitting the trend into two series and making every curated
        # rule written in the canonical unit skip the value in silence.
        assert canonical_unit(printed) == canonical_unit(unit), unit


def test_english_unit_rows_are_parsed_rather_than_dropped():
    """A report that writes "mmol/L" instead of «ммоль/л» kept nothing at all.

    Every spelling below is the printed Latin form of a unit the allowlist
    already accepted in Cyrillic, so each one used to take its whole row with
    it -- silently, since a dropped row raises nothing.
    """
    spellings = [
        "U/L", "IU/L", "IU/mL", "mIU/L", "µIU/mL", "mmol/L", "µmol/L", "umol/L",
        "nmol/L", "pmol/L", "mg/dL", "mg/L", "g/dL", "g/L", "ng/mL", "pg/mL",
        "µg/L", "cells/µL", "mm/h", "mEq/L", "mL",
    ]
    for printed in spellings:
        observations = parse_unit_rows(f"Ferritin 12.3 {printed} 1.0 - 99.0", 1)
        assert [item.unit_raw for item in observations] == [printed], printed


def test_doses_and_dimensions_are_still_not_units():
    """The allowlist gained Latin spellings; it must not have gained tolerance.

    Antibiotic disk potencies, ultrasound dimensions and drug doses print in
    the identical "<name> <number> <token>" shape as a result, on the same
    pages.  «мкг», «мм», «мм.», "mm" and «мг» are theirs, and a pattern that
    accepted them would ingest a kidney's length as a laboratory value.
    """
    observations = parse_document(
        "EskuLab",
        "laboratory",
        page(
            """
            Амікацин 30 мкг Чутливий
            Права нирка 105 мм x 48 мм
            Вузлове утворення 12 мм.
            Nodule 12 mm
            Ібупрофен 200 мг тричі на добу
            Тиреотропний гормон 2.22 мкМО/л 0.27 - 4.2
            """
        ),
    )
    assert observations == []


#: Where EskuLab prints each column, measured off the six reports in this
#: record.  The specimen sits in the name column but indented, which is the
#: whole reason these tests exist: flattened to text it is indistinguishable
#: from the analyte name it hangs under.
#: `ref2` is the reference cell's own second printed sub-column.  EskuLab puts
#: the paediatric table there, beside the adult one, and both are inside the
#: single cell the page's column boundaries describe.
ESKULAB_X = {
    "name": 28.3, "specimen": 117.1, "result": 246.0, "unit": 321.9,
    "ref": 378.4, "ref2": 472.7,
}
ESKULAB_STOOL_X = {"name": 28.3, "result": 200.4, "ref": 402.0}
ESKULAB_CULTURE_X = {"name": 28.3, "result": 243.8}


def eskulab_page(rows, columns=None):
    """The page an EskuLab report of these rows would produce.

    Each row maps a column to its text.  Tokens are laid out at 3.5pt per
    character, close enough to the printed font that a full-width analyte name
    still stops short of the result column exactly as the real one does.
    """
    columns = columns or ESKULAB_X
    words = []
    for index, row in enumerate(rows):
        top = 200.0 + index * 12.0
        for column, text in row.items():
            x = columns[column]
            for token in str(text).split():
                width = 3.5 * len(token)
                words.append((x, x + width, top, token))
                x += width + 2.5
    text = "\n".join(" ".join(str(value) for value in row.values()) for row in rows)
    return [{"page_number": 1, "native_text": text, "words": words}]


ESKULAB_HEADER = {
    "name": "Показник", "result": "Результат", "unit": "Одиниці", "ref": "Референтні значення",
}

ESKULAB_ROWS = [
    ESKULAB_HEADER,
    # A reference cell that wraps over the four lines below its own row.
    {"name": "Глюкоза (плазма крові)", "result": "5.95", "unit": "ммоль/л"},
    {"specimen": "плазма крові", "ref": "новонароджені (1 день): 2.22 - 3.33"},
    {"ref": "діти: 3.33 - 5.55"},
    {"ref": "Вагітні: < 5.1"},
    {"ref": "Дорослі: 4.11 - 5.89"},
    # The specimen wraps, and its tail returns to the left margin where it is
    # indistinguishable by position from a name that wrapped.
    {"name": "Лейкоцити в мкл (WBC)", "result": "4.1", "unit": "кл/мкл", "ref": "жінки < 28.0"},
    {"specimen": "Приносний матеріал,", "ref": "чоловіки < 11.2"},
    {"name": "сеча"},
    {"name": "Час відбору: 07:40"},
    # A name too long for its column, continued on the next line.
    {"name": "Скупчення лейкоцитів (WBC", "result": "0.4", "unit": "кл/мкл", "ref": "-"},
    {"name": "Clumps)"},
    {"specimen": "Приносний матеріал, сеча"},
    # An empty unit column, printed as a dash.
    {"name": "рН (C-PH)", "result": "5.5", "unit": "-", "ref": "5.5 - 7.0"},
    {"specimen": "Приносний матеріал, сеча"},
    # A dipstick pad: nothing in the result column, and a legend that says what
    # the empty column means.
    {"name": "Глюкоза (C-GLU)", "result": "-", "unit": "мг/дл"},
    {"specimen": "Приносний матеріал, сеча", "ref": "не виявлена (-) 250 = ++"},
    {"name": "Час відбору: 07:40", "ref": "50 = +- 500 = +++"},
    # A section heading: an empty result and nothing else.
    {"name": "Мікроскопія сечі", "result": "-"},
    {"specimen": "Приносний матеріал, сеча"},
    # The adult band is named, and sits below the paediatric one that happens
    # to share a line with the value.
    {"name": "Об'єм еритроцитів (MCV)", "result": "83.6", "unit": "фл", "ref": "До 1р.: 77-100"},
    {"specimen": "цільна кров ЗАК", "ref": "1-16р.: 78-98"},
    {"ref": "Дорослі: 80-100"},
    # An age range printed before its interval rather than after it.
    {"name": "Кальцій загальний", "result": "2.37", "unit": "ммоль/л"},
    {"specimen": "сироватка крові", "ref": "діти 0-10 днів: 1,9-2,6 дорослі 18-60 років:"},
    {"ref": "2,25-2,75 60-90 років: 2,2-2,55"},
    {"name": "Дослідження виконала(-ли) Лаборант: Насанович Н.Ю."},
]


def eskulab():
    return {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(ESKULAB_ROWS))
    }


def test_eskulab_reference_table_rows_are_not_read_as_results():
    """The wrapped reference column looks exactly like a result once flattened.

    «діти: 3.33 - 5.55» reached the record as an analyte named "children" worth
    3.33, and «Вагітні: < 5.1» as one named "pregnant" worth 5.1 -- six such
    rows from one order, each carrying a threshold from somebody else's band.
    """
    names = set(eskulab())
    assert not [name for name in names if name.rstrip(":") in {"діти", "Вагітні", "Чоловіки", "Жінки"}]
    assert "Глюкоза (плазма крові)" in names
    assert eskulab()["Глюкоза (плазма крові)"].value_numeric == 5.95


def test_eskulab_specimen_never_becomes_part_of_the_analyte_name():
    """The specimen is indented under the name, and wraps back to the margin.

    Reading the page as text glued it onto the analyte above it: thirteen of
    fifteen urinalysis rows arrived named "... Приносний матеріал," and matched
    no concept.  «сеча» is the specimen; «сечі», one letter away, is the tail of
    "К-сть клітин схожих на атипові в мкл сечі".
    """
    parsed = eskulab()
    assert "Лейкоцити в мкл (WBC)" in parsed
    assert not [name for name in parsed if "Приносний" in name or "Час відбору" in name]
    assert not [name for name in parsed if name.endswith("сеча")]


def test_eskulab_keeps_both_sex_specific_thresholds():
    """This patient is male, and the male limit is the one that matters.

    Taking only the line beside the value kept «жінки < 28.0» and dropped
    «чоловіки < 11.2» -- the difference between a normal white cell count in
    urine and four times the limit.  Neither may be reduced to a number, so
    both are kept as text and `reference_bounds` refuses them.
    """
    white_cells = eskulab()["Лейкоцити в мкл (WBC)"]
    assert "жінки < 28.0" in white_cells.reference_text
    assert "чоловіки < 11.2" in white_cells.reference_text
    assert (white_cells.reference_low, white_cells.reference_high) == (None, None)


def test_eskulab_wrapped_analyte_name_is_rejoined_from_the_line_below():
    parsed = eskulab()
    assert "Скупчення лейкоцитів (WBC Clumps)" in parsed
    assert parsed["Скупчення лейкоцитів (WBC Clumps)"].value_numeric == 0.4


def test_eskulab_empty_unit_column_still_yields_the_result():
    """Urine pH and relative density print a dash where the unit goes.

    Both were absent from every urinalysis in this record because the shared
    parser requires a unit, and a dash is not one.
    """
    acidity = eskulab()["рН (C-PH)"]
    assert acidity.value_numeric == 5.5
    assert acidity.unit_raw is None
    assert (acidity.reference_low, acidity.reference_high) == (5.5, 7.0)


def test_eskulab_negative_dipstick_pad_is_a_finding_not_a_missing_row():
    """An empty result column with a legend under it means the pad read negative.

    The legend defines the dash: «не виявлена (-) 250 = ++ …».  Read as text
    the phrase was picked up as a *result* and named after the specimen line it
    shared, which is how «Приносний матеріал, сеча» became an analyte three
    times over in one urinalysis.
    """
    glucose = eskulab()["Глюкоза (C-GLU)"]
    assert glucose.value_text == "не виявлена"
    assert glucose.value_numeric is None
    # A word result carries no unit (CLIN-30): «не виявлена мг/дл» is not a
    # quantity of anything.
    assert glucose.unit_raw is None
    # A heading has an empty result and no unit or legend, and is not a finding.
    assert "Мікроскопія сечі" not in eskulab()


def test_eskulab_adult_band_wins_over_the_paediatric_one_beside_the_value():
    """MCV prints the infant band on the result line and the adult band below.

    The parser keeps the whole printed block now rather than reducing it to the
    line beginning «Дорослі» -- that reduction threw away every band an adult
    row is headed «Чоловіки» or «Дорослі (ч)» instead, which on order 41015004
    was the only band eleven analytes had.  Choosing among them moved to
    `applicable_band`, which knows the reader's age and sex; what must not
    change is which interval the reader ends up measured against.
    """
    from anamna.health import applicable_reference_bounds

    mcv = eskulab()["Об'єм еритроцитів (MCV)"]
    assert "Дорослі: 80-100" in mcv.reference_text
    assert applicable_reference_bounds(mcv.reference_text, 34, "male") == (80.0, 100.0)


def test_eskulab_never_reads_an_age_range_as_a_reference_interval():
    """«дорослі 18-60 років: 2,15-2,5» names the group first, the band second.

    Reading the first pair gave total calcium a reference of 18-60 mmol/L, and
    every real calcium on earth is critically low against that.
    """
    calcium = eskulab()["Кальцій загальний"]
    assert (calcium.reference_low, calcium.reference_high) != (18.0, 60.0)
    assert calcium.reference_low is None or calcium.reference_low < 10.0


COPROGRAM_ROWS = [
    {"name": "1. F9014 Копрограма (матеріал: Приносний матеріал, кал)"},
    {"result": "Результат", "ref": "Референтні значення"},
    {"name": "Шматочки", "result": "не виявлено", "ref": "не виявлено"},
    {"name": "тканини"},
    # A parent that reports no result of its own, then alternating sub-heading
    # and quantity lines sharing the one column.
    {"name": "М'язові волокна", "ref": "не виявлено"},
    {"result": "змінені"},
    {"result": "поодиноко"},
    {"result": "не змінені"},
    {"result": "невелика к-сть."},
    {"name": "Реакція", "result": "6.5", "ref": "дорослі: 7 - 7.5"},
    {"name": "Дослідження виконала(-ли) : Шекета Н.."},
]


def coprogram():
    return {
        item.raw_name: item
        for item in parse_document(
            "EskuLab", "laboratory", eskulab_page(COPROGRAM_ROWS, ESKULAB_STOOL_X)
        )
    }


def test_eskulab_coprogram_is_read_at_all():
    """Two pages of a stool analysis produced nothing whatsoever.

    The table gives its first column no heading, so every pass that looks for
    "Показник Результат" skipped it and the report read as empty.
    """
    parsed = coprogram()
    assert parsed["Шматочки тканини (кал)"].value_text == "не виявлено"
    assert parsed["Реакція (кал)"].value_numeric == 6.5


def test_eskulab_coprogram_pairs_each_subheading_with_its_own_quantity():
    """«М'язові волокна» reports three sub-results in one column, alternating.

    Pairing them by position alone mis-pairs the moment a sub-heading wraps, so
    the quantities are named rather than counted.
    """
    parsed = coprogram()
    assert parsed["М'язові волокна змінені (кал)"].value_text == "поодиноко"
    assert parsed["М'язові волокна не змінені (кал)"].value_text == "невелика к-сть."
    assert "М'язові волокна (кал)" not in parsed


CULTURE_ROWS = [
    {"name": "Мікроорганізм виявлено", "result": "Результат"},
    {"name": "Staphylococcus aureus", "result": "1.0 x 10^2 КУО/г"},
    # The organism's own antibiogram sub-heading, printed in the right column.
    {"result": "Staphylococcus aureus"},
    # Antibiogram rows, verbatim from throat culture 40095487: with a disk
    # potency, without one, with EUCAST's increased-exposure qualifier, and
    # with the potency wrapped onto its own line.
    {"name": "Азитроміцин", "result": "Чутливий"},
    {"name": "Бензилпеніцилін 1 од", "result": "Стійкий"},
    {"name": "Амікацин 30 мкг", "result": "Чутливий"},
    {"name": "Амоксицилін-клавуланова кислота", "result": "Чутливий"},
    {"name": "Ципрофлоксацин 5 мкг", "result": "Чутливий, збільшена експозиція"},
    {"name": "Триметоприм-сульфаметоксазол", "result": "Чутливий"},
    {"name": "1,25-23,75 мкг"},
]


def test_eskulab_culture_reads_the_count_and_the_antibiogram_verdicts():
    """40095487 held 33 susceptibility verdicts and the record held none of them.

    The skip was deliberate once -- the verdicts had no concepts -- and then
    stale: the same verdicts from an Expert Hospital culture were already
    ingested as '<antibiotic> susceptibility' observations.  The verdict is
    text; the disk potency («Бензилпеніцилін 1 од») is what the paper disk
    held and must never become a value.
    """
    parsed = {
        item.raw_name: item
        for item in parse_document(
            "EskuLab", "microbiology", eskulab_page(CULTURE_ROWS, ESKULAB_CULTURE_X)
        )
    }
    assert parsed["Staphylococcus aureus"].value_numeric == 100.0
    assert parsed["Staphylococcus aureus"].unit_raw == "КУО/г"
    assert parsed["Азитроміцин"].value_text == "Чутливий"
    assert parsed["Бензилпеніцилін"].value_text == "Стійкий"
    assert parsed["Амікацин"].value_text == "Чутливий"
    assert parsed["Амоксицилін-клавуланова кислота"].value_text == "Чутливий"
    # EUCAST's "I" is not plain susceptibility; the qualifier travels with it.
    assert parsed["Ципрофлоксацин"].value_text == "Чутливий, збільшена експозиція"
    assert parsed["Триметоприм-сульфаметоксазол"].value_text == "Чутливий"
    # No disk potency became a number, wrapped or inline.
    verdicts = [item for item in parsed.values() if item.value_text and item.raw_name != "Staphylococcus aureus"]
    assert all(item.value_numeric is None for item in verdicts)
    assert not [name for name in parsed if "мкг" in name or "од" in name.split()]


CONTINUATION_ROWS = [
    {"name": "Найпростіші", "result": "не виявлено", "ref": "не виявлено"},
    {"name": "Яйця гельмінтів", "result": "не виявлено", "ref": "не виявлено"},
    {"name": "Елементи гриба,", "result": "поодиноко в п/з", "ref": "не виявлено"},
    {"name": "подібного до"},
    {"name": "дріжджевого"},
    {"name": "Дослідження виконала(-ли) : Шекета Н.."},
]


def test_eskulab_coprogram_continues_onto_a_page_with_no_header():
    """The second page of a coprogram announces itself in no way at all.

    No panel heading, no header row -- «Найпростіші | не виявлено | не
    виявлено» simply continues the table, and three results went unread:
    protozoa, helminth eggs and yeast-like fungal elements.
    """
    parsed = {
        item.raw_name: item
        for item in parse_document(
            "EskuLab", "laboratory", eskulab_page(CONTINUATION_ROWS, ESKULAB_STOOL_X)
        )
    }
    assert parsed["Найпростіші (кал)"].value_text == "не виявлено"
    assert parsed["Яйця гельмінтів (кал)"].value_text == "не виявлено"
    assert "Елементи гриба, подібного до дріжджевого (кал)" in parsed


def test_a_page_announcing_its_own_table_is_not_a_coprogram_continuation():
    """The culture report was read as one, and it is nothing like one.

    Both organisms came back relabelled «(кал)», and «Амоксицилін-клавуланова»
    -- half an antibiotic name -- was published as an analyte whose result was
    the other half.
    """
    rows = [
        {"name": "Мікроорганізм виявлено", "result": "Результат"},
        {"name": "Staphylococcus aureus", "result": "1.0 x 10^2 КУО/г"},
        {"name": "Амоксицилін-клавуланова", "result": "кислота"},
    ]
    parsed = {
        item.raw_name: item
        for item in parse_document(
            "EskuLab", "microbiology", eskulab_page(rows, ESKULAB_CULTURE_X)
        )
    }
    assert not [name for name in parsed if "(кал)" in name]
    assert parsed["Staphylococcus aureus"].value_numeric == 100.0


MULTI_PANEL_ROWS = [
    ESKULAB_HEADER,
    {"name": "1. С-пептид", "result": "2.41", "unit": "нг/мл", "ref": "0,9-7,1"},
    {"specimen": "сироватка крові"},
    # A signature block *between* panels, not at the end of the table.
    {"name": "Дослідження виконала(-ли) : Кушнір І.."},
    {"name": "Завідувач клініко-діагностичної лабораторії"},
    {"name": "2. L0610 Пакет №375. D3+B9+B12"},
    ESKULAB_HEADER,
    {"name": "25-Гідроксивітамін D (Вітамін D", "result": "31.7", "unit": "нг/мл"},
    {"ref": "Ризик дефіциту: < 10.0 Дорослі: 30.0-50.0"},
    {"name": "загальний)"},
    {"specimen": "сироватка крові"},
    {"name": "Фолієва кислота", "result": "5.43", "unit": "нг/мл", "ref": "3.1-19.9"},
]


def test_eskulab_reads_every_panel_on_a_page_not_just_the_first():
    """A report of many panels prints a signature block between each pair.

    Treating that as the end of the table stopped the parser at the first panel
    of every page — eleven of the twelve panels in order 41015004 — and what
    was left of each page then fell through to the parser that reads it as flat
    text.
    """
    parsed = {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(MULTI_PANEL_ROWS))
    }
    assert parsed["С-пептид"].value_numeric == 2.41
    assert parsed["25-Гідроксивітамін D (Вітамін D загальний)"].value_numeric == 31.7
    assert parsed["Фолієва кислота"].value_numeric == 5.43
    # The catalogue heading is not an analyte; the analyte numbering is not a name.
    assert not [name for name in parsed if "L0610" in name or name.startswith(("1.", "2."))]


def test_eskulab_strips_the_analyte_numbering_but_keeps_a_chemical_position():
    """«1. С-пептид» is C-peptide, first in its panel. «25-Гідроксивітамін D»
    is 25-hydroxyvitamin D, and the 25 is part of the molecule."""
    parsed = parse_document("EskuLab", "laboratory", eskulab_page(MULTI_PANEL_ROWS))
    names = {item.raw_name for item in parsed}
    assert "С-пептид" in names
    assert "25-Гідроксивітамін D (Вітамін D загальний)" in names


def test_a_page_that_draws_a_table_never_falls_back_to_the_text_parsers():
    """The fallback is what re-created the bug the column parser exists to fix.

    A page whose every panel was skipped looked like "no table here", so it went
    to the shared passes, and the glucose reference block came back as analytes:
    «діти: 3.33 - 5.55» worth 3.33, «Вагітні: < 5.1» worth 5.1.
    """
    rows = [
        ESKULAB_HEADER,
        # Nothing here the column parser will accept as a result...
        {"name": "Фізико-хімічні властивості", "result": "-"},
        # ...and a reference block that the flat-text parser reads as results.
        {"ref": "діти: 3.33 - 5.55 60-90 років: 4.56 - 6.38"},
        {"ref": "Вагітні: < 5.1 > 90 років: 4.16 - 6.72"},
        {"ref": "Чоловіки: <50.0"},
    ]
    parsed = parse_document("EskuLab", "laboratory", eskulab_page(rows))
    assert parsed == []


def test_eskulab_rejoins_a_name_broken_at_its_hyphen():
    """«Ширина розподілу еритроцитів (RDW-» / «SD)» is (RDW-SD).

    The abbreviation is the only thing separating a 36.1 fL red-cell spread
    from a 12.0 % one; rejoined with a space it matches neither alias, and
    published under the wrong one it is four times the upper limit.
    """
    rows = [
        ESKULAB_HEADER,
        {"name": "Ширина розподілу еритроцитів (RDW-", "result": "36.1", "unit": "фл",
         "ref": "35,0-56,0"},
        {"name": "SD)"},
        {"specimen": "цільна кров ЗАК"},
        {"name": "Ширина розподілу еритроцитів по", "result": "12.0", "unit": "%",
         "ref": "11,5-14,5"},
        {"name": "об'ємі (RDW-CV)"},
    ]
    parsed = {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(rows))
    }
    assert parsed["Ширина розподілу еритроцитів (RDW-SD)"].unit_raw == "фл"
    assert parsed["Ширина розподілу еритроцитів по об'ємі (RDW-CV)"].unit_raw == "%"


def test_a_named_risk_tier_is_never_published_as_a_reference_interval():
    """«Помірно підвищений рівень ризику: 75-125» is a tier, not a range.

    The label sits thirty-four characters ahead of its own numbers, so a
    narrower guard window missed it and a lipoprotein(a) of 178 nmol/L was
    judged against the moderately-raised band as though that were healthy.
    """
    scale = ("Низький рівень ризику: < 75 Помірно підвищений рівень ризику: 75-125 "
             "Високий рівень ризику: ≥ 125")
    assert reference_bounds(scale) == (None, None)
    # A plain interval still resolves.
    assert reference_bounds("Дорослі: 4.11 - 5.89") == (4.11, 5.89)


def test_eskulab_keeps_the_two_halves_of_a_reference_block_apart():
    """The reference cell is often two printed columns, and reading order
    interleaves them: «оптимальний рівень: < 2,59» beside «Високий пороговий
    рівень: 4,14-4,89» came back as one unreadable run of both."""
    rows = [
        ESKULAB_HEADER,
        {"name": "Глюкоза (плазма крові)", "result": "5.95", "unit": "ммоль/л"},
        {"specimen": "плазма крові", "ref": "новонароджені (1 день):"},
        {"ref": "2.22 - 3.33"},
        {"ref": "Дорослі: 4.11 - 5.89"},
    ]
    from anamna.health import applicable_reference_bounds

    parsed = {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(rows))
    }
    glucose = parsed["Глюкоза (плазма крові)"]
    assert "новонароджені (1 день): 2.22 - 3.33" in glucose.reference_text
    assert "Дорослі: 4.11 - 5.89" in glucose.reference_text
    assert applicable_reference_bounds(glucose.reference_text, 34, "male") == (4.11, 5.89)


def test_a_renamed_concept_does_not_keep_its_old_aliases():
    """Renaming a concept mints a new id, because the id is a slug of the name.

    The old id kept its seeded aliases, so «резус-фактор» went on resolving to
    a "Rh factor" concept no definition described any more. An alias with no
    vendor is owned by the definition file and by nothing else, so seeding
    removes the ones the file no longer lists.
    """
    import sqlite3
    from anamna.ingest.pipeline import seed_concepts

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE concepts(id TEXT PRIMARY KEY, canonical_name TEXT, category TEXT,
               value_type TEXT, preferred_unit TEXT, created_at TEXT);
           CREATE TABLE concept_aliases(concept_id TEXT, vendor_id TEXT, alias TEXT,
               normalized_alias TEXT, UNIQUE(concept_id, vendor_id, normalized_alias));
           CREATE TABLE reference_sets(id TEXT PRIMARY KEY, name TEXT, publisher TEXT,
               jurisdiction TEXT, version TEXT, effective_from TEXT, effective_to TEXT,
               source_url TEXT, reviewed_at TEXT, notes TEXT, region TEXT);"""
    )
    connection.execute(
        "INSERT INTO concepts(id, canonical_name) VALUES ('stale-concept', 'Gone')"
    )
    connection.execute(
        """INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
           VALUES ('stale-concept', NULL, 'резус-фактор', 'резус-фактор')"""
    )
    # A vendor's own learned alias is not the file's to remove.
    connection.execute(
        """INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
           VALUES ('stale-concept', 'vendor-1', 'Резус-фактор', 'резус-фактор')"""
    )
    try:
        seed_concepts(connection)
    except sqlite3.OperationalError:
        pass  # the reference library needs tables this fixture does not create

    remaining = {
        (r["concept_id"], r["vendor_id"])
        for r in connection.execute("SELECT concept_id, vendor_id FROM concept_aliases")
    }
    assert ("stale-concept", None) not in remaining
    assert ("stale-concept", "vendor-1") in remaining


# The γ-GT block as EskuLab prints it: the adult rows in the left sub-column,
# the whole paediatric table in the right one.  Three lines leave a wide gap
# between the columns and three do not, which is the entire difficulty.
GGT_ROWS = [
    ESKULAB_HEADER,
    {"name": "Гамма-глутамілтрансфераза", "result": "34.9", "unit": "Од/л"},
    {"ref": "Жінки: 5.0-36.0", "ref2": "Діти 1-3 роки: <18.0"},
    {"name": "(ГГТ)", "ref": "Чоловіки: 8.0-61.0", "ref2": "Діти 3-6 років: <23.0"},
    {"specimen": "сироватка крові"},
    {"ref": "Діти до 5 днів: <185.0", "ref2": "Діти 6-12 років: <17.0"},
    {"ref": "Діти 6-12 місяців: <34.0", "ref2": "Діти чоловіки 12-17"},
    {"ref2": "років: <45.0"},
]


def ggt():
    return {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(GGT_ROWS))
    }["Гамма-глутамілтрансфераза (ГГТ)"]


def test_eskulab_reference_sub_columns_are_split_where_the_page_prints_them():
    """A wide gap finds the column boundary only on the lines that have one.

    «Діти до 5 днів: <185.0 Діти 6-12 років: <17.0» leaves eight points between
    the two printed columns -- under any threshold that does not also split
    ordinary phrases -- so the paediatric table arrived shuffled into the adult
    rows and «Чоловіки: 8.0-61.0» was followed by a child's threshold.  The
    lines that do break measure the column for the lines that do not.
    """
    reference = ggt().reference_text
    assert "Чоловіки: 8.0-61.0" in reference
    # Left sub-column first, top to bottom, then the right one: the order the
    # block was written in.  Every band keeps its own interval.
    for band in (
        "Жінки: 5.0-36.0", "Діти до 5 днів: <185.0", "Діти 6-12 місяців: <34.0",
        "Діти 1-3 роки: <18.0", "Діти 6-12 років: <17.0",
    ):
        assert band in reference
    assert reference.index("Діти 6-12 місяців: <34.0") < reference.index("Діти 1-3 роки: <18.0")


def test_eskulab_line_printed_only_in_the_right_sub_column_stays_there():
    """«Діти чоловіки 12-17» wraps, and its tail is alone on the next line.

    Read as left-column content the tail rejoined the wrong heading, which put
    «років: <45.0» in the middle of the adult rows.
    """
    assert "Діти чоловіки 12-17 років: <45.0" in ggt().reference_text


def test_eskulab_centred_single_column_reference_is_not_split_in_two():
    """A short reference is centred in its cell and can end where the second
    sub-column starts.  Split there, «Чоловік: 0,04-0,54 / Жінки: 0,04-0,36»
    became "Чоловік: Жінки: 0,04-0,36 0,04-0,54" and the men's eosinophil
    count took the women's limit."""
    rows = GGT_ROWS + [
        {"name": "Еозинофіли (абс.)", "result": "0.10", "unit": "кл/мкл", "ref_centred": "Чоловік: 0,04-0,54"},
        {"specimen": "цільна кров", "ref_centred": "Жінки: 0,04-0,36"},
    ]
    columns = dict(ESKULAB_X, ref_centred=439.5)
    parsed = {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(rows, columns))
    }
    assert parsed["Еозинофіли (абс.)"].reference_text == "Чоловік: 0,04-0,54 Жінки: 0,04-0,36"


def test_eskulab_second_table_under_a_row_is_not_read_as_more_of_its_reference():
    """Order 41015004 prints the Панченков/Вестергрен conversion under the ESR
    result.  Its heading crosses the column boundaries and is dropped, but its
    body is two clean columns and was collected as more of the ESR reference --
    a sex-specific limit trailed by seven intervals from another method."""
    rows = [
        ESKULAB_HEADER,
        {"name": "ШОЕ за Вестергреном", "result": "2", "unit": "мм/год"},
        {"ref": "Чоловіки: <15", "ref2": "Жінки: <20"},
        {"ref": "Чол. >50р: <20", "ref2": "Жін. >50р: <30"},
        {"ref": "Діти до 17р: <10", "ref2": "Діти до 1р: <7"},
        # The conversion table: a value in the name column, indented, with no
        # result of its own.
        {"specimen": "1-20", "ref": "1-20"},
        {"specimen": "20-30", "ref": "20-40"},
        {"specimen": "30-40", "ref": "40-70"},
    ]
    parsed = {
        item.raw_name: item
        for item in parse_document("EskuLab", "laboratory", eskulab_page(rows))
    }
    reference = parsed["ШОЕ за Вестергреном"].reference_text
    assert "Чоловіки: <15" in reference
    assert "Жін. >50р: <30" in reference
    # None of the conversion table reached the reference.
    assert "20-40" not in reference and "40-70" not in reference


def test_a_pcr_panel_keeps_the_threshold_that_says_what_the_count_would_mean():
    """Ureaplasma is printed as a labelled panel, not a table row.

    Every other organism on the page carries «не виявлено» in a Референтні
    значення column; these two carry «Клінічно значуща кількість» on the line
    below the result, and it was dropped -- the only two rows on the report
    reaching the record with no reference at all.
    """
    page = (
        "Виявлення ДНК Ureaplasma parvum (ПЛР) (кількісне визначення)\n"
        "Вид дослідження U.parvum\n"
        "Метод дослідження ПЛР в реальному часі (Real-time PCR)\n"
        "Результат не виявлено ГЄ/мл\n"
        "Клінічно значуща кількість >10^4 ГЄ/мл\n"
    )
    (found,) = parse_pcr_sections(page, 1)
    assert found.value_text == "не виявлено"
    assert found.reference_text == "Клінічно значуща кількість >10^4 ГЄ/мл"
    # Read as a number it would be a lower bound of 10 -- a thousandfold low,
    # and inverted: the threshold says where colonisation begins.
    assert (found.reference_low, found.reference_high) == (None, None)
    assert reference_bounds("Клінічно значуща кількість >10^4 ГЄ/мл") == (None, None)
    assert reference_bounds(">10^4 ГЄ/мл") == (None, None)


def test_two_numbers_touching_across_a_column_boundary_are_separated():
    """«Діти (Ж) 13-15 років: 5.4» printed hard against «... (Ч) 13-15: 4.7-19.7».

    The extractor returns one token, «5.44.7-19.7».  Left glued, the girls'
    band reads as 5.44.7 and the boys' band keeps its label and loses its
    interval.  The rule stays narrow: a finished decimal meeting a starting
    one, which an ordinary interval crossing the same x does not look like.

    What starts across the boundary is as often an *age* as a value, and an age
    band is written in whole numbers.  Order 41015004 prints «Жінки 12-17
    років: <24.0» hard against «1-3 років: <33.0» and «... <25.0» against «6-12
    років: <47.0»; requiring the following number to carry a decimal missed
    both, so ALT's 1-3-years band and AST's 6-12-years band were unreachable --
    which is what let «Діти 0-5 днів» win for a child of either age.
    """
    assert [m.start() for m in ESKULAB_GLUE.finditer("5.44.7-19.7")] == [3]
    assert [m.start() for m in ESKULAB_GLUE.finditer("<24.01-3")] == [5]
    assert [m.start() for m in ESKULAB_GLUE.finditer("<25.06-12")] == [5]
    # A whole-number range only, all the way through: the trailing digit of
    # «2,59-3,34» begins a decimal, and «5.83-34.5» ends in one.  Both cross
    # this x innocently, centred in a single reference column.
    for innocent in (
        "13.0-19.0",
        "5.9 - 18.3",
        "180-490",
        "2,59-3,34",
        "5.83-34.5",
        "0.66-1.44",
        "2,25-2,75",
        "32,5-42,5",
        "0.9-<1.0",
    ):
        assert [m.start() for m in ESKULAB_GLUE.finditer(innocent)] == [], innocent


def test_a_band_named_above_optimal_is_not_the_patients_reference():
    """The LDL block on order 41015004, verbatim.

    «висок…» and «підвищ…» miss both «вище оптимального рівня» and «Верхній
    пороговий рівень», so the band immediately *over* the optimum was taken as
    the reference interval: an LDL of 3.0 mmol/L reported as inside the
    laboratory's range on the line where the same laboratory puts the optimum
    below 2.59.
    """
    ldl = (
        "Дорослі: оптимальний рівень: < 2,59 Близький до оптимального рівня/ вище "
        "оптимального рівня: 2,59-3,34 Верхній пороговий рівень: 3,37-4,12 "
        "Високий пороговий рівень: 4,14-4,89 Дуже високий пороговий рівень: ≥ 4,92"
    )
    assert reference_bounds(ldl) == (None, None)
    # 3.0 mmol/L read against whatever bounds that block yields.
    low, high = reference_bounds(ldl)
    above_optimal = ParsedObservation(
        raw_name="Ліпопротеїди низької щільності",
        value_numeric=3.0,
        value_text=None,
        comparator=None,
        unit_raw="ммоль/л",
        reference_text=ldl,
        reference_low=low,
        reference_high=high,
        page_number=1,
        evidence_text="ЛПНЩ 3.0",
        confidence=0.99,
    )
    assert interpretation(above_optimal) != "within_vendor_range"
    # The optimum itself is still an ordinary normal band, named by no tier word.
    assert reference_bounds("оптимальний рівень: < 2,59") == (None, 2.59)
    assert NON_NORMAL_BAND_RE.search("оптимальний рівень") is None
    for tier in (
        "вище оптимального рівня",
        "Верхній пороговий рівень",
        "Високий пороговий рівень",
        "Дуже високий пороговий рівень",
    ):
        assert NON_NORMAL_BAND_RE.search(tier), tier
