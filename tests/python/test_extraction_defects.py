"""Extraction defects that each published a wrong clinical number.

Every case here was found in the live record, not imagined.  They share one
shape: the value was read correctly and then *described* wrongly -- a unit the
measurement was not in, a scale the laboratory does not use, a concept from a
different specimen, or an interval belonging to the other sex -- and each one
produced a confident verdict that was wrong, or silence where there should have
been an alarm.
"""

from __future__ import annotations

import pytest

from anamna.health import applicable_reference_bounds, reference_applies
from anamna.ingest.concepts import concept_for_alias
from anamna.ingest.parsers import (
    parse_expert_page,
    parse_st_paraskeva,
    parse_unit_rows,
    relative_density,
)
from anamna.ingest.pipeline import stored_unit
from anamna.reference import canonical_unit, convert_value, evaluate
from anamna.db import connect

from test_web_panels import build, settings_for


# --- units the value is not in ---------------------------------------------


def test_gram_per_decilitre_is_not_folded_into_gram_per_litre():
    """They differ by ten, and MCHC is printed in both across one record."""
    assert canonical_unit("г/дл") == canonical_unit("g/dL") == "g/dl"
    assert canonical_unit("г/л") == canonical_unit("g/L") == "g/l"
    assert canonical_unit("г/дл") != canonical_unit("г/л")
    concept = "mean-corpuscular-hemoglobin-concentration"
    assert convert_value(36.0, "г/дл", "g/L", concept) == pytest.approx(360.0)
    assert convert_value(360.0, "g/L", "г/дл", concept) == pytest.approx(36.0)


def test_millilitres_canonicalise_with_their_english_spelling():
    assert canonical_unit("мл") == canonical_unit("mL") == "ml"


def test_a_unit_with_no_conversion_is_never_relabelled():
    """`stored_unit` states what the number is in, never what we wish it were.

    Claiming the concept's preferred unit regardless of the printed one is how
    "36 g/dL" became "36 g/L" -- a tenth of the real measurement -- and how the
    application came to report *below range* on an MCHC that is above it.
    """
    assert stored_unit("г/дл", "g/L") == "г/дл"
    assert stored_unit(None, "g/L") == "g/L"
    assert stored_unit("g/L", "g/L") == "g/L"


def test_the_mchc_verdict_follows_the_unit_the_report_printed():
    settings = settings_for_db()
    with connect(settings) as connection:
        printed = evaluate(
            connection,
            concept_id="mean-corpuscular-hemoglobin-concentration",
            value_numeric=36.0,
            unit="g/dL",
            age_years=34,
            sex="male",
        )
        converted = evaluate(
            connection,
            concept_id="mean-corpuscular-hemoglobin-concentration",
            value_numeric=360.0,
            unit="g/L",
            age_years=34,
            sex="male",
        )
    # The same measurement, two spellings, one answer -- and it is "high".
    # Read as 36 g/L it came out "low": the opposite conclusion.
    assert printed["interpretation"] == converted["interpretation"] == "high"


def settings_for_db():
    """A migrated database with the seeded reference library, nothing else."""
    import tempfile
    from pathlib import Path

    from anamna.db import migrate
    from anamna.ingest.pipeline import seed_reference_rules

    global _SEEDED
    try:
        return _SEEDED
    except NameError:
        pass
    settings = settings_for(Path(tempfile.mkdtemp()))
    migrate(settings)
    with connect(settings) as connection:
        seed_reference_rules(connection)
    _SEEDED = settings
    return settings


# --- scales the laboratory does not use ------------------------------------


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("1005", "1.005"),   # the integer column of the MOH 210/o form
        ("1030", "1.030"),
        ("1060", "1.060"),
        ("1.005", "1.005"),  # already decimal: untouched
        ("1,025", "1,025"),
        ("70", "70"),        # a delivered volume, not a density: untouched
        ("999", "999"),
    ],
)
def test_relative_density_folds_only_the_integer_window(printed, expected):
    assert relative_density(printed) == expected


def test_urine_relative_density_and_its_interval_land_on_one_scale():
    """Stored as printed, the series read "1.025 -> 1005 -> 1.035"."""
    text = (
        "ФОРМА № 210/о\n"
        "Колір солом'яно-жовтий Солом'яно-жовтий\n"
        "Питома густина 1005 1005-1030\n"
        "pH 6,5 5,0-8,0\n"
    )
    found = {item.raw_name: item for item in parse_st_paraskeva(text, 1)}
    density = found["Питома густина"]  # the label as the form prints it
    assert density.value_numeric == pytest.approx(1.005)
    # The interval has to move with the value or the verdict compares a
    # thousandth of a number against a thousand times its threshold.
    assert (density.reference_low, density.reference_high) == (1.005, 1.030)


# --- a concept from a different specimen -----------------------------------


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Лейкоцити в мкл (WBC)", "Urine leukocytes"),
        ("Еритроцити в мкл (RBC)", "Urine erythrocytes"),
        # The bare code still resolves for the analytes it was meant for.
        ("Ліпопротеїди дуже низької щільності (VLDL)", "VLDL cholesterol"),
    ],
)
def test_a_urinalysis_row_is_not_resolved_by_its_blood_count_abbreviation(printed, expected):
    """107.6 leukocytes/µL of urine was published as a blood count of 107.6.

    ``concept_for_alias`` falls back to the parenthesised code, which is the
    right instinct for a CBC export and the wrong one for the urinalysis panel
    that prints the same "(WBC)" against a completely different specimen.
    """
    assert concept_for_alias(printed, "numeric")["name"] == expected


@pytest.mark.parametrize(
    "printed, expected",
    [
        # The parenthesised codes here are Cyrillic homoglyphs of MCH/MCHC:
        # identical on paper, unequal to every string comparison.  Synevo
        # prints this pair, and losing either alias files the row on a
        # nameless concept beside the series it belongs to.
        ("Середній вміст гемоглобіну в еритроциті (МСН)", "Mean corpuscular hemoglobin"),
        ("Середня концентрація гемоглобіну в еритроциті (МСНС)", "Mean corpuscular hemoglobin concentration"),
    ],
)
def test_cyrillic_homoglyph_codes_still_resolve_to_the_cbc_indices(printed, expected):
    assert concept_for_alias(printed, "numeric")["name"] == expected


@pytest.mark.parametrize(
    "printed, value_type, expected",
    [
        # Esculab's automated microscopy, numeric per µL: these minted learned
        # Ukrainian-only concepts beside the definitions, splitting one analyte
        # across two or three half-length trends -- including a 0.42 цл/мкл
        # hyaline-cast reading above the printed male limit of 0.4.
        ("Гіалінові циліндри в мкл (Hy.CAST)", "numeric", "Hyaline casts in urine"),
        ("Клітини ниркового епітелію (RTEC)", "numeric", "Renal epithelial cells in urine"),
        ("Клітини перехідного епітелію в мкл (Tran.EC)", "numeric", "Transitional epithelial cells in urine"),
        ("Клітини плоского епітелію в мкл (Squa.EC)", "numeric", "Squamous epithelial cells in urine"),
        ("Негіалінові циліндри в мкл (Path.CAST)", "numeric", "Non-hyaline casts in urine"),
        ("Циліндри (CAST)", "numeric", "Total casts in urine"),
        ("Кристали в мкл (X`TAL)", "numeric", "Crystals in urine"),
        ("Епітеліальні клітини в мкл (EC)", "numeric", "Epithelial cells in urine"),
        ("Клітини не плоского епітелію в мкл (Non SEC)", "numeric", "Non-squamous epithelial cells in urine"),
        # Expert's 17 µmol/L bilirubin -- exactly the lab's «+» tier -- landed
        # on a learned concept while the curated rule sat on urine-bilirubin.
        ("Білірубін в сечі", "numeric", "Urine bilirubin"),
        # Vendor spellings of manual-microscopy rows.
        ("Воскоподібні циліндри", "text", "Waxy casts in urine"),
        ("Еритроцитарні циліндри", "text", "Urine erythrocyte casts"),
        ("Лейкоцитарні циліндри", "text", "Urine leukocyte casts"),
        ("Клітини епітелію сечового міхура", "text", "Urine bladder epithelial cells"),
        ("Клітини ниркового епітелію", "text", "Renal epithelial cells in urine"),
        ("Клітини перехідного епітелію", "text", "Transitional epithelial cells in urine"),
        ("Колір сечі (C-COLOR)", "text", "Urine colour"),
    ],
)
def test_learned_urinalysis_spellings_resolve_to_their_definitions(printed, value_type, expected):
    assert concept_for_alias(printed, value_type)["name"] == expected


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Азитроміцин", "Azithromycin susceptibility"),
        ("Амоксицилін-клавуланова кислота", "Amoxicillin-clavulanate susceptibility"),
        ("Бензилпеніцилін", "Benzylpenicillin susceptibility"),
        ("Триметоприм-сульфаметоксазол", "Trimethoprim-sulfamethoxazole susceptibility"),
        ("Цефуроксим", "Cefuroxime susceptibility"),
        # The hyphenated combination must not fall onto its first component.
        ("Ампіцилін-сульбактам", "Ampicillin-sulbactam susceptibility"),
    ],
)
def test_antibiogram_verdicts_have_susceptibility_concepts(printed, expected):
    assert concept_for_alias(printed, "text")["name"] == expected


def _catalog_db():
    """The two catalogue tables, with the live UNIQUE(vendor_id, normalized_alias)."""
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE concepts(id TEXT PRIMARY KEY, canonical_name TEXT, category TEXT,
               value_type TEXT, preferred_unit TEXT, created_at TEXT);
           CREATE TABLE concept_aliases(id INTEGER PRIMARY KEY AUTOINCREMENT,
               concept_id TEXT NOT NULL, vendor_id TEXT, alias TEXT NOT NULL,
               normalized_alias TEXT NOT NULL, UNIQUE(vendor_id, normalized_alias));"""
    )
    return connection


def test_a_bare_count_files_by_the_specimen_the_report_title_names():
    """«Лейкоцити» is seeded for both a blood and a urine concept.

    The row itself carries no сеч- token, so only the report title says which
    specimen it counts: 25 leukocytes/µL on a urinalysis is pyuria, and filed
    under the blood concept it reads as leukocytosis instead.
    """
    from anamna.ingest.pipeline import ensure_concept

    connection = _catalog_db()
    urine, _ = ensure_concept(
        connection, "Лейкоцити", "vendor-1", value_type="numeric",
        context="Загальний аналіз сечі",
    )
    blood, _ = ensure_concept(
        connection, "Лейкоцити", "vendor-1", value_type="numeric",
        context="Розгорнутий клінічний аналіз крові",
    )
    assert urine == "urine-leukocytes"
    assert blood == "white-blood-cell-count"


def test_a_corrected_definition_heals_a_stale_learned_alias():
    """INSERT OR IGNORE could never overwrite the row from the WBC incident.

    The stale vendor alias «Лейкоцити в мкл (WBC)» → blood WBC survived the
    corrected definitions and sat first in the DB fallback's ORDER BY, waiting
    to re-file urine counts as blood ones if the definitions ever regressed.
    The definition path now upserts, so a corrected catalogue corrects the
    learned table.
    """
    from anamna.ingest.pipeline import ensure_concept
    from anamna.ingest.text import normalized_key

    connection = _catalog_db()
    stale = normalized_key("Лейкоцити в мкл (WBC)")
    connection.execute(
        """INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
           VALUES ('white-blood-cell-count', 'vendor-1', 'Лейкоцити в мкл (WBC)', ?)""",
        (stale,),
    )
    concept_id, _ = ensure_concept(
        connection, "Лейкоцити в мкл (WBC)", "vendor-1", value_type="numeric"
    )
    assert concept_id == "urine-leukocytes"
    healed = connection.execute(
        "SELECT concept_id FROM concept_aliases WHERE vendor_id='vendor-1' AND normalized_alias=?",
        (stale,),
    ).fetchone()
    assert healed["concept_id"] == "urine-leukocytes"


# --- an interval belonging to the other sex --------------------------------


def test_a_reference_that_wraps_after_the_first_sex_keeps_both_halves():
    """Esculab prints the female limit, then the male one two lines below."""
    text = (
        "Лейкоцити в мкл (WBC) 107.6 кл/мкл жінки < 28.0\n"
        "Приносний матеріал,\n"
        "чоловіки < 11.2\n"
        "сеча\n"
    )
    row = next(item for item in parse_unit_rows(text, 1) if "WBC" in item.raw_name)
    assert row.reference_text == "жінки < 28.0 чоловіки < 11.2"


def test_a_tail_is_only_taken_when_it_names_the_other_sex():
    """Distance is not the guard; the sexes are."""
    text = (
        "Лейкоцити в мкл (WBC) 107.6 кл/мкл жінки < 28.0\n"
        "жінки < 15\n"
    )
    row = next(item for item in parse_unit_rows(text, 1) if "WBC" in item.raw_name)
    assert row.reference_text == "жінки < 28.0"


@pytest.mark.parametrize(
    "reference, sex, expected",
    [
        ("жінки < 28.0 чоловіки < 11.2", "male", (None, 11.2)),
        ("жінки < 28.0 чоловіки < 11.2", "female", (None, 28.0)),
        ("чоловіки < 10 жінки < 15", "male", (None, 10.0)),
        ("жінки < 15 чоловіки < 10", "male", (None, 10.0)),
        # A sex-only qualifier with no colon used to be confirmed to apply and
        # then discarded anyway, leaving the reading with no bar at all.
        ("чоловіки < 10", "male", (None, 10.0)),
        # One sex named, and it is not this patient: still refused.
        ("жінки < 28.0", "male", (None, None)),
        # Unknown sex must never be handed one of two intervals at random.
        ("жінки < 28.0 чоловіки < 11.2", None, (None, None)),
        # An age window with no colon stays refused: stripping the qualifying
        # words would leave "20-65" as the first number pair.
        ("Чоловіки 20-65 років 3.89 - 26.8", "male", (None, None)),
        # Unchanged behaviour for the forms that already worked.
        ("Чоловіки: <41.0", "male", (None, 41.0)),
        ("Дорослі (20-65 років): 3.89 - 26.8", "male", (3.89, 26.8)),
        ("Діти: <1 року: 100.0-140.0", "male", (None, None)),
    ],
)
def test_the_half_of_a_per_sex_interval_that_describes_the_patient(reference, sex, expected):
    assert applicable_reference_bounds(reference, 34, sex) == expected


def test_a_two_sex_reference_is_a_table_not_a_restriction():
    """Both sexes named means "pick one", not "this excludes you"."""
    assert reference_applies("жінки < 28.0 чоловіки < 11.2", 34, "male") is True
    assert reference_applies("жінки < 28.0", 34, "male") is False


# --- an interval that was recorded and never used --------------------------


def test_the_laboratorys_own_interval_actually_judges_the_value():
    """It was displayed beside the value and never compared to it.

    A demographically-qualified range is refused by the parser and recovered
    at read time, so the interpretation computed at ingest is absent -- and
    `_vendor_verdict` returned "unjudged" while printing "<= 11.2" next to a
    reading of 107.6.
    """
    settings = settings_for_db()
    with connect(settings) as connection:
        judged = evaluate(
            connection, concept_id="urine-leukocytes", value_numeric=107.6,
            unit="cells/µL", age_years=34, sex="male", vendor_high=11.2,
        )
        within = evaluate(
            connection, concept_id="urine-leukocytes", value_numeric=4.1,
            unit="cells/µL", age_years=34, sex="male", vendor_high=11.2,
        )
        silent = evaluate(
            connection, concept_id="urine-leukocytes", value_numeric=107.6,
            unit="cells/µL", age_years=34, sex="male",
        )
    assert judged["interpretation"] == "high"
    assert judged["authority"] == "vendor"
    assert within["interpretation"] == "normal"
    # No printed interval must stay unjudged rather than defaulting to normal:
    # silence is recoverable, a green badge over an unmeasured value is not.
    assert silent["interpretation"] == "unjudged"


# --- the read path puts one concept on one axis ----------------------------


# --- rows the allowlist and the row patterns were dropping whole ------------


def test_a_caret_exponent_without_its_denominator_is_still_a_cell_count():
    """WBC, RBC and platelets were absent from two whole panels.

    The "/л" sits in a separate PDF text object and never reaches the line, so
    the unit allowlist rejected "10^9" and dropped the row -- while the
    percentage differentials beside it were kept, which is what made the panels
    look complete.
    """
    text = (
        "Лейкоцити (WBC) 6.41 10^9 Діти: <1 року: 6.5 - 12.5\n"
        "Еритроцити (RBC) 5.13 10^12 Діти: <1 року: 3.3 - 4.9\n"
        "Тромбоцити (PLT) 300 10^9 Діти: <1 року: 180.0 - 400.0\n"
        # An antibiotic disk potency wears the same clothes and must stay out.
        "Амікацин 30 мкг Чутливий\n"
    )
    rows = {item.raw_name: item for item in parse_unit_rows(text, 1)}
    assert rows["Лейкоцити (WBC)"].value_numeric == pytest.approx(6.41)
    assert rows["Еритроцити (RBC)"].value_numeric == pytest.approx(5.13)
    assert rows["Тромбоцити (PLT)"].value_numeric == pytest.approx(300)
    assert "Амікацин" not in rows


def test_a_bare_caret_exponent_folds_onto_the_per_litre_unit():
    """Unfolded it would give the analyte a second unit and split its trend."""
    assert canonical_unit("10^9") == canonical_unit("х 10*9/л") == "10^9/l"
    assert canonical_unit("10^12") == canonical_unit("10^12/L") == "10^12/l"


def test_a_reference_that_opens_with_its_band_name_still_matches():
    """The lipid panel's total cholesterol row matched nothing at all."""
    text = (
        "ПОКАЗНИК РЕЗУЛЬТАТ НОРМА\n"
        "Холестерин загальний, ммоль/л 8,1 високий рівень; >6,2 високий\n"
    )
    row = next(item for item in parse_expert_page(text, 1) if "Холестерин" in item.raw_name)
    assert row.value_numeric == pytest.approx(8.1)
    assert row.unit_raw == "ммоль/л"


def test_a_row_whose_reference_is_absent_is_still_a_result():
    """Ketones, urine bilirubin and urobilinogen were missing from a urinalysis."""
    text = (
        "ПОКАЗНИК РЕЗУЛЬТАТ НОРМА\n"
        "Кетони, ммоль/л 0.5\n"
        "Білірубін в сечі, мкмоль/л 17\n"
        "Уробіліноген, мкмоль/л 35 ранковій порції; +-=8,5; +=17;\n"
        "Лейкоцити в сечі, кл/мкл негативний\n"   # text value: not a numeric row
        "Результати досліджень не є клінічним діагнозом\n"
    )
    rows = {item.raw_name: item for item in parse_expert_page(text, 1)}
    assert rows["Кетони"].value_numeric == pytest.approx(0.5)
    assert rows["Кетони"].unit_raw == "ммоль/л"
    assert rows["Білірубін в сечі"].value_numeric == pytest.approx(17)
    assert rows["Уробіліноген"].value_numeric == pytest.approx(35)
    assert "Лейкоцити в сечі" not in rows


# --- intervals that would have been read backwards or from the wrong band ---


@pytest.mark.parametrize(
    "reference, expected",
    [
        # "> 6.2 is HIGH" is not "6.2 and above is normal".
        ("високий рівень; >6,2 високий", (None, None)),
        # The first number pair here is the *equivocal* band, not the range;
        # the band the scale itself names negative is (DOCC-34).
        ("Negative <1.0; equivocal 1.0–1.2; positive >1.2", (None, 1.0)),
        # Everything that already worked keeps working.
        ("<1.7 - низький рівень ризику", (None, 1.7)),
        ("<2.59 - оптимальний рівень", (None, 2.59)),
        ("<3.0 - для груп низького ризику", (None, 3.0)),
        ("від 1,04", (1.04, None)),
        ("від 0,26 до 1", (0.26, 1.0)),
        ("до 2,59", (None, 2.59)),
        ("> 8.0", (8.0, None)),
        ("3.8-5.0", (3.8, 5.0)),
    ],
)
def test_bounds_are_refused_rather_than_read_from_the_wrong_band(reference, expected):
    from anamna.ingest.parsers import reference_bounds

    assert reference_bounds(reference) == expected


def test_the_repair_pass_never_erases_an_interval_it_cannot_re_derive(tmp_path):
    """It re-reads the printed text with the *generic* bounds parser.

    Rows produced by a layout-specific parser carry bounds that prose does not
    spell out, and regenerating nothing from that prose used to store the
    nothing.
    """
    from anamna.db import utc_now
    from anamna.ingest.pipeline import ensure_concept, ensure_vendor, repair_observation_semantics

    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Synevo", None)
        concept_id, _ = ensure_concept(connection, "Total 25-hydroxyvitamin D", vendor_id)
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, unit_raw, unit_canonical, observed_at,
                   vendor_reference_text, vendor_reference_low, vendor_reference_high,
                   verification_status, extraction_method, confidence, evidence_text,
                   parser_version, created_at)
               VALUES ('vitd-1', ?, ?, 'doc-1', 1, ?, 'Total 25-hydroxyvitamin D', 'numeric',
                       32.1, 'ng/mL', 'ng/mL', '2025-08-27',
                       'deficiency risk below ten; sufficiency in prose only', 30.0, 50.0,
                       'extracted', 'native_pdf_text_parser', 0.99, 'evidence', 'test', ?)""",
            (user_id, f"patient-{user_id}", concept_id, utc_now()),
        )
        repair_observation_semantics(connection)
        row = connection.execute(
            "SELECT vendor_reference_low lo, vendor_reference_high hi FROM observations WHERE id='vitd-1'"
        ).fetchone()
    assert (row["lo"], row["hi"]) == (30.0, 50.0)


def test_the_catalog_states_every_reading_in_the_concepts_unit(tmp_path):
    """Two laboratories, two units, one trend line."""
    from anamna.db import utc_now
    from anamna.ingest.pipeline import ensure_concept, ensure_vendor
    from anamna.web import app as web

    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Synevo", None)
        concept_id, _ = ensure_concept(
            connection, "Mean corpuscular hemoglobin concentration", vendor_id
        )
        for index, (value, unit, day) in enumerate(
            [(36.0, "г/дл", "2025-03-01"), (340.0, "г/л", "2025-04-01")]
        ):
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, unit_raw, unit_canonical,
                       observed_at, verification_status, extraction_method, confidence,
                       evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-1', 1, ?, 'MCHC', 'numeric', ?, ?, ?, ?,
                           'extracted', 'test', 0.9, 'evidence', 'test', ?)""",
                (f"mchc-{index}", user_id, f"patient-{user_id}", concept_id, value,
                 unit, unit, day, utc_now()),
            )
    web.invalidate_catalog()
    with connect(settings) as connection:
        rows = web._deduped_observation_rows(connection, user_id, concept_id)
    by_day = {str(row["observed_at"]): row["value_numeric"] for row in rows}
    # 36 g/dL is restated as 360 g/L; the g/L reading is left alone.
    assert by_day["2025-03-01"] == pytest.approx(360.0)
    assert by_day["2025-04-01"] == pytest.approx(340.0)
