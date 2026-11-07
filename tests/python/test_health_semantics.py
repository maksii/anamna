import re
from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.health import (
    CATEGORY_TO_AREA,
    REFERENCE_FRAGMENTS_EN,
    _extract_clinical_assessment,
    applicable_band,
    applicable_reference_bounds,
    display_reference,
    display_unit,
    display_value,
    metric_area_ids,
    translate_reference_fragments,
)
from anamna.i18n import set_locale
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts
from anamna.ingest.parsers import reference_bounds
from anamna.reference import canonical_unit


def test_demographic_vendor_range_is_not_applied_as_universal():
    assert reference_bounds("Новонароджені діти (1 день життя): 2.22 - 3.33") == (None, None)
    assert reference_bounds("від 3,89 до 5,82") == (3.89, 5.82)


def test_blood_and_urine_glucose_are_distinct_concepts(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as connection:
        seed_concepts(connection)
        vendor_id = ensure_vendor(connection, "Test provider", None)
        blood_id, _ = ensure_concept(
            connection, "Глюкоза", vendor_id, value_type="numeric", unit_raw="ммоль/л"
        )
        urine_id, _ = ensure_concept(
            connection, "Глюкоза", vendor_id, value_type="text", clinical_type="laboratory"
        )
        blood = connection.execute("SELECT canonical_name FROM concepts WHERE id=?", (blood_id,)).fetchone()[0]
        urine = connection.execute("SELECT canonical_name FROM concepts WHERE id=?", (urine_id,)).fetchone()[0]

    assert blood_id != urine_id
    assert blood == "Blood glucose"
    assert urine == "Urine glucose"


def test_display_unit_renders_caret_exponents_as_unicode_superscript():
    # Presentation only: `evaluate()` still keys curated rules on the caret
    # form (see the guard in web/app.py's _lab_card), so canonical_unit()
    # must be completely unmoved by this - NFKC would otherwise collapse the
    # superscript back to a bare digit and silently drop the 10^9/L rules.
    set_locale("en")
    assert display_unit("10^9/L") == "10⁹/L"
    assert display_unit("10^12/L") == "10¹²/L"
    assert canonical_unit("10^9/L") == "10^9/l"
    assert canonical_unit("10^12/L") == "10^12/l"


def test_alternative_unit_spellings_fold_onto_one_canonical():
    """Every spelling of one quantity has to reach one comparison key.

    An unfolded spelling is not a cosmetic problem: it gives the analyte a
    second unit, so the trend splits into two series and every curated rule
    written in the canonical unit skips the value without saying so.
    """
    for group in (
        ("mmol/L", "ммоль/л"),
        ("µmol/L", "μmol/L", "umol/L", "мкмоль/л"),
        ("U/L", "од/л"),
        ("IU/L", "МО/л"),
        ("IU/mL", "мо/мл"),
        ("mIU/L", "ммо/л", "мМО/л", "мкМО/мл", "µIU/mL", "uIU/mL"),
        ("mg/L", "мг/л", "мкг/мл"),
        ("cells/µL", "cells/uL", "кл/мкл", "клітин/мкл"),
        ("mm/h", "mm/hr", "мм/год", "мм/год."),
        ("10^9/L", "х 10*9/л", "10^9", "тис/мкл"),
        ("mEq/L", "мекв/л"),
        ("g/L", "г/л"),
        ("µg/L", "ug/L", "мкг/л"),
        # «ГЄ/мл» and «ГЕ/мл» are the Е/Є homoglyph pair one PCR report prints
        # two lines apart; unfolded, Mycoplasma and Ureaplasma loads carried
        # two different units for one quantity.
        ("genome equivalents/mL", "гє/мл", "ге/мл"),
        ("per HPF", "в п/з"),
    ):
        assert len({canonical_unit(spelling) for spelling in group}) == 1, group

    # Folded only where the quantity is genuinely the same.  "mU/L" is milli-
    # units and «мкМО/л» reads as µIU/L, one thousandth of the «мкМО/мл» above
    # it; calling either one mIU/L would state a conversion nobody measured.
    assert canonical_unit("mU/L") != canonical_unit("mIU/L")
    assert canonical_unit("мкМО/л") != canonical_unit("мкМО/мл")


def test_a_second_spelling_never_becomes_the_displayed_unit():
    set_locale("uk")
    assert display_unit("µIU/mL") == "мМО/л"
    assert display_unit("cells/uL") == "кл/мкл"
    assert display_unit("umol/L") == "мкмоль/л"
    assert display_unit("IU/L") == "МО/л"
    set_locale("en")
    assert display_unit("МО/л") == "IU/L"
    assert display_unit("мекв/л") == "mEq/L"
    assert display_unit("клітин/мкл") == "cells/µL"


def test_microscopy_and_pcr_units_render_in_the_readers_locale():
    set_locale("uk")
    # Stored canonically as "per HPF" (unit_raw is empty), so the Ukrainian
    # page needs the reverse map to print what the report meant: «в полі зору».
    assert display_unit("per HPF") == "в п/з"
    set_locale("en")
    assert display_unit("в п/з") == "per HPF"
    # Both homoglyph spellings reach one English rendering.
    assert display_unit("ГЕ/мл") == "genome equivalents/mL"
    assert display_unit("ГЄ/мл") == "genome equivalents/mL"


def test_the_digestive_area_claims_the_stool_category():
    # The coprogram seeds category "stool"; the area sweeping the dead name
    # "gastrointestinal" instead is how 31 analytes vanished from navigation.
    assert metric_area_ids("Stool pH", "stool") == ["digestive"]
    assert "gastrointestinal" not in CATEGORY_TO_AREA
    assert "chemistry" not in CATEGORY_TO_AREA


def test_source_values_have_english_display_labels():
    assert display_value("не виявлено") == "Not detected"
    assert display_value("резистентний") == "Resistant"
    assert display_reference("до 2,59") == "≤ 2.59"
    newborns = "Новонароджені діти (1 день життя): 2.22 - 3.33"
    assert display_reference(newborns, age_years=0) == "Newborns (day 1 of life): 2.22-3.33"


def test_short_conclusions_and_doctor_assessments_keep_source_wording():
    assert _extract_clinical_assessment(
        "ЗАКЛЮЧЕННЯ: Ліпоми спини\nРекомендовано: спостереження"
    ) == "Ліпоми спини"
    assert _extract_clinical_assessment(
        "Попередній діагноз: Плантарний фасциїт. Артрит?\nРекомендовано обстеження"
    ) == "Плантарний фасциїт. Артрит?"
    assert _extract_clinical_assessment(
        "Kardia Advanced Determination:\nNormal Sinus Rhythm\n* Kardia Advanced Determination is done on Lead I."
    ) == "Normal Sinus Rhythm"


def test_related_laboratory_results_can_appear_in_body_system_views():
    assert metric_area_ids("Calcium, ionized", "electrolytes") == ["nutrition", "spine"]
    assert metric_area_ids("HLA-B27", "immunogenetics") == ["immunity", "joints", "spine"]
    assert metric_area_ids("Uric acid", "renal") == ["kidneys", "joints"]


def test_a_paediatric_range_is_never_shown_as_an_adults_own_range():
    children = "Діти: <1 року: 100.0 - 140.0"
    assert display_reference(children, age_years=34, sex="male") != children
    assert "100" not in display_reference(children, age_years=34, sex="male")
    assert applicable_reference_bounds(children, 34, "male") == (None, None)
    # A bare population label is a truncated extraction, not a range.
    assert display_reference("Дорослі (від 18 років):", age_years=34) == display_reference(None)


def test_an_applicable_adult_range_is_recovered_not_discarded():
    male, adult = "male", 34
    assert applicable_reference_bounds("Дорослі: 8.0 - 61.0", adult, male) == (8.0, 61.0)
    assert applicable_reference_bounds(
        "Чоловіки (20-60 років): 30.0 - 400.0", adult, male
    ) == (30.0, 400.0)
    assert applicable_reference_bounds(
        "Дорослі (20-65 років): 3.89 - 26.8", adult, male
    ) == (3.89, 26.8)
    # A woman's range is not this patient's range.
    assert applicable_reference_bounds("Жінки: 13.0 - 150.0", adult, male) == (None, None)
    # Unqualified text keeps working exactly as before.
    assert applicable_reference_bounds("від 3,89 до 5,82", adult, male) == (3.89, 5.82)


# The reference blocks EskuLab printed on order 10000331, verbatim after the
# column parser puts the two printed sub-columns back in reading order.  Every
# one of these was showing "not applicable to this age or sex" to a 34-year-old
# man who had the answer printed on the page in front of him.
ESKULAB_BLOCKS = {
    "ggt": (
        "Жінки: 5.0-36.0 Чоловіки: 8.0-61.0 Діти до 5 днів: <185.0 "
        "Діти 5 днів - 6 місяців: <204.0 Діти 6-12 місяців: <34.0 Діти 1-3 роки: <18.0 "
        "Діти 3-6 років: <23.0 Діти 6-12 років: <17.0 Діти жінки 12-17 років: <33.0 "
        "Діти чоловіки 12-17 років: <45.0"
    ),
    "alp": (
        "Дорослі жінки: 35-104 Діти (ж): Діти 0-14 днів: 83-248 Діти 15 днів-1 рік: 122-469 "
        "1-10 років: 142-335 Дорослі (ч): 40-129 Діти (ч): 0-14 днів: 83-248 "
        "15 днів-1 рік: 122-469 1-10 років: 142-335"
    ),
    "calcium": (
        "діти від 0-10 днів: 1,9-2,6 діти 10 днів- 2 роки: 2,25-2,75 2-12 років: 2,2-2,7 "
        "12-18 років: 2,1-2,55 дорослі 18-60 років: 2,15-2,5 60-90 років: 2,2-2,55 "
        "90 і старше: 2,05-2,4"
    ),
    "glucose": (
        "новонароджені (1 день): 2.22 - 3.33 новонароджені (> 1 дня): 2.78 - 4.44 "
        "діти: 3.33 - 5.55 Вагітні: < 5.1 Гестаційний діабет: 5.1 - 6.9 "
        "Маніфестний цукровий діабет, виявлений вперше: ≥ 7.0 Дорослі: 4.11 - 5.89 "
        "60-90 років: 4.56 - 6.38 > 90 років: 4.16 - 6.72"
    ),
    "esr": (
        "Діти до 17р: <10мм/год Чоловіки 17 - 50р: < 15мм/год Чоловіки старші 50р: <20мм/год "
        "Жінки 17-50р: <20мм/ год Жінки старші 50р. :. <30мм/год"
    ),
    "neutrophils": "До 1р.: 15-45 1-6р.: 25-60 6-12р.: 35-65 12-16р.: 40-65 Дорослі: 40-70",
    # ALT and AST exactly as the record stored them, with the two numbers the
    # extractor joined across the sub-column boundary still glued: «<24.0»
    # against «1-3 років», «<25.0» against «6-12 років».  The band each child
    # belongs in is unreachable in this form.
    "alt_glued": (
        "Жінки: <35.0 Чоловіки: <50.0 Жінки 12-17 років: <24.01-3 років: <33.0 "
        "Чоловіки 12-17 років: <27.0 Діти 0-5 днів: <49.0 5 днів - 6 місяців: <56.0 "
        "6-12 місяців: <54.0 3-6 років: <29.0 6-12 років: <39.0"
    ),
    "ast_glued": (
        "Жінки: <35.0 Чоловіки: <50.0 Чоловіки 12-17 років: <29.0 "
        "Жінки 12-17 років: <25.06-12 років: <47.0 Діти 0-5 днів: <97.0 "
        "5 днів - 6 місяців: <77.0 6-12 місяців: <82.0 1-3 років: <48.0 3-6 років: <36.0"
    ),
    # ... and as the same order prints them once `ESKULAB_GLUE` separates the
    # two, which is what re-parsing the source PDF now produces.
    "alt": (
        "Жінки: <35.0 Чоловіки: <50.0 Жінки 12-17 років: <24.0 Чоловіки 12-17 років: <27.0 "
        "Діти 0-5 днів: <49.0 5 днів - 6 місяців: <56.0 6-12 місяців: <54.0 1-3 років: <33.0 "
        "3-6 років: <29.0 6-12 років: <39.0"
    ),
    "ast": (
        "Жінки: <35.0 Чоловіки: <50.0 Чоловіки 12-17 років: <29.0 Жінки 12-17 років: <25.0 "
        "Діти 0-5 днів: <97.0 5 днів - 6 місяців: <77.0 6-12 місяців: <82.0 1-3 років: <48.0 "
        "3-6 років: <36.0 6-12 років: <47.0"
    ),
    # Uric acid names no child anywhere: two sex rows and two gout targets.
    "uric_acid": (
        "Жінки: 142.8-339.2 Чоловіки: 202.3-416.5 "
        "Терапевтичні цілі при подагрі (EULAR/ACR): <360.0 При тофусній/тяжкій подагрі: <300.0"
    ),
    # HDL is printed as a risk scale per sex, with no healthy interval at all.
    "hdl": (
        "Жінки: ризик відсутній: >1.68 Жінки: помірний ризик: 1.15-1.68 Жінки: високий ризик: <1.15 "
        "Чоловіки: ризик відсутній: >1.45 Чоловіки: помірний ризик: 0.90-1.45 "
        "Чоловіки: високий ризик: <0.90"
    ),
}


def test_the_adult_band_is_found_inside_a_block_written_for_every_age_at_once():
    """Judged whole, these blocks are unmistakably about children.

    So `reference_applies` refused all of them, and six analytes on one report
    told a 34-year-old man that no printed range applied to him -- with
    «Чоловіки: 8.0-61.0» sitting in the block being refused.
    """
    man, woman = (34, "male"), (34, "female")
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ggt"], *man) == (8.0, 61.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ggt"], *woman) == (5.0, 36.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["calcium"], *man) == (2.15, 2.5)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["glucose"], *man) == (4.11, 5.89)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["neutrophils"], *man) == (40.0, 70.0)


def test_the_short_form_of_a_sex_is_read_as_that_sex():
    """«Дорослі (ч)» is EskuLab's men's row, printed beside «Дорослі жінки».

    Unrecognised, the two were indistinguishable and a man's alkaline
    phosphatase was measured against the women's 35-104 rather than 40-129.
    """
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alp"], 34, "male") == (40.0, 129.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alp"], 34, "female") == (35.0, 104.0)


def test_a_year_abbreviated_to_one_letter_is_still_an_age():
    """«Чоловіки 17 - 50р» and «Чоловіки старші 50р» both name men.

    Unless the «р» is read as a year, both describe a 34-year-old equally well
    and there is nothing to choose between 15 mm/h and 20.
    """
    assert applicable_reference_bounds(ESKULAB_BLOCKS["esr"], 34, "male") == (None, 15.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["esr"], 34, "female") == (None, 20.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["esr"], 60, "male") == (None, 20.0)


def test_a_band_named_after_a_condition_is_never_the_healthy_one():
    """Pregnancy and diabetes bands parse as cleanly as the adult one.

    «Вагітні: < 5.1» names no sex to the reader but matches the female token,
    and «Гестаційний діабет: 5.1 - 6.9» names nothing at all -- so a woman was
    handed a pregnancy threshold and a man a diagnostic one.
    """
    assert applicable_reference_bounds(ESKULAB_BLOCKS["glucose"], 34, "female") == (4.11, 5.89)
    assert applicable_reference_bounds(
        "Низький рівень ризику: < 75 Помірно підвищений рівень ризику: 75-125", 34, "male"
    ) == (None, None)


def test_a_child_is_not_given_the_mens_row_of_an_adult_table():
    """A block that gives the boys rows of their own means «Чоловіки» = adult men."""
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ggt"], 7, "male") == (None, 17.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["neutrophils"], 7, "male") == (35.0, 65.0)


def test_a_bare_sex_row_reaches_no_child_even_when_no_child_is_named():
    """«Чоловіки: 202.3-416.5» is the adult men's uric acid, not a boy's.

    These reports print the children by age and the grown-ups by sex, so a row
    naming only a sex carries no age because none was needed.  Where the block
    also lists paediatric rows that was already caught; where it does not, a
    seven-year-old was handed the men's interval outright -- paediatric uric
    acid runs about a third lower, so a perfectly ordinary child's result would
    have read as low.  Nothing paediatric was printed, and saying so is the
    answer rather than borrowing the row that was.
    """
    assert applicable_band(ESKULAB_BLOCKS["uric_acid"], 7, "male") is None
    assert applicable_reference_bounds(ESKULAB_BLOCKS["uric_acid"], 7, "male") == (None, None)
    # And through the other door into the same row: `applicable_band` refuses,
    # `_sex_clause` used to re-admit it.
    two_sexes = "Чоловік: 0,04-0,54 Жінки: 0,04-0,36"
    assert applicable_reference_bounds(two_sexes, 7, "male") == (None, None)
    assert applicable_reference_bounds("Чоловіки: 8.0 - 61.0", 7, "male") == (None, None)
    assert applicable_reference_bounds("жінки < 15 чоловіки < 10", 7, "male") == (None, None)
    # A block that carries paediatric rows must not let the adult row through
    # either: judged whole it passes for a child, because one of the age
    # windows it finds is a child's.
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alt"], 17, "female") == (None, 24.0)
    # The adults are untouched.
    assert applicable_reference_bounds(ESKULAB_BLOCKS["uric_acid"], 34, "male") == (202.3, 416.5)
    assert applicable_reference_bounds(two_sexes, 34, "male") == (0.04, 0.54)
    assert applicable_reference_bounds("Чоловіки: 8.0 - 61.0", 34, "male") == (8.0, 61.0)


def test_an_age_window_written_in_days_or_months_is_not_a_window_of_years():
    """«Діти 0-5 днів» is five DAYS, and was being read as five years.

    Nothing in the age machinery spelled a day or a month, so the window never
    matched; with no window, no from and no to, the band fell through to the
    generic «Діти» rule -- which is every patient under eighteen.  The two
    glued blocks below are how the record stored ALT and AST before the column
    parser learned to separate «<24.01-3»: the year band a child belonged in is
    unreachable there, so the newborn row was all that was left, and a
    seven-year-old's AST was judged against <97 U/L and a two-year-old's ALT
    against <49.0.
    """
    assert applicable_band(ESKULAB_BLOCKS["ast_glued"], 7, "male") is None
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ast_glued"], 7, "male") == (None, None)
    assert applicable_band(ESKULAB_BLOCKS["alt_glued"], 2, "male") is None
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alt_glued"], 2, "male") == (None, None)
    # A band finer than a year reaches nobody whose age is a whole number of
    # years: a patient recorded as 0 is anything from a day old to eleven
    # months, and «Діти 0-5 днів: <97.0» is not a statement about the rest of
    # them -- it is nearly three times the limit printed for their own row.
    assert applicable_band(ESKULAB_BLOCKS["ast"], 0, "male") is None
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ast"], 0, "male") == (None, None)
    assert applicable_band(ESKULAB_BLOCKS["alt"], 0, "male") is None
    assert applicable_band(ESKULAB_BLOCKS["ggt"], 0, "male") is None
    # Once the glue is separated the right year band is there and is taken.
    assert applicable_band(ESKULAB_BLOCKS["ast"], 7, "male") == "6-12 років: <47.0"
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ast"], 7, "male") == (None, 47.0)
    assert applicable_band(ESKULAB_BLOCKS["alt"], 2, "male") == "1-3 років: <33.0"
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alt"], 2, "male") == (None, 33.0)
    # Years still work, in every spelling these reports use for them.
    assert applicable_reference_bounds(ESKULAB_BLOCKS["alt"], 14, "male") == (None, 27.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["ast"], 17, "female") == (None, 25.0)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["calcium"], 34, "male") == (2.15, 2.5)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["esr"], 60, "male") == (None, 20.0)
    # ... and the newborn guard is unmoved.
    assert applicable_reference_bounds(ESKULAB_BLOCKS["glucose"], 5, "male") == (3.33, 5.55)


def test_a_risk_tier_is_not_a_reference_interval_on_either_path_into_it():
    """HDL prints three risk tiers per sex and no healthy interval at all.

    `applicable_band` refuses the block -- every band is named after a risk --
    and returned None, and `applicable_reference_bounds` then re-admitted it
    through `_sex_clause`, which throws the tier's own label away before
    `reference_bounds` ever sees it.  «Чоловіки: ризик відсутній: >1.45» became
    a lower bound of 1.45, so an acceptable male HDL of 1.11 mmol/L read as
    below range and the curated verdict was downgraded to a conflict with a
    laboratory that had made no such claim.
    """
    assert applicable_band(ESKULAB_BLOCKS["hdl"], 34, "male") is None
    assert applicable_reference_bounds(ESKULAB_BLOCKS["hdl"], 34, "male") == (None, None)
    assert applicable_reference_bounds(ESKULAB_BLOCKS["hdl"], 34, "female") == (None, None)
    # Per-sex tables that name no tier are unaffected -- these are the ones on
    # the same report.
    assert applicable_reference_bounds("Чоловіки: 62.0-106 Жінки: 44.0-80.0", 34, "male") == (
        62.0,
        106.0,
    )
    assert applicable_reference_bounds("Жінки: 1,18-3,74 Чоловіки: 1,32-3,57", 34, "male") == (
        1.32,
        3.57,
    )


def test_the_band_keeps_the_unit_the_laboratory_printed_beside_it():
    """«Чоловіки 17 - 50р: < 15мм/год» was surfaced as a bare "< 15".

    The interval pattern captures digits only, so the unit -- printed hard
    against the last digit -- was left behind with the next band's label, and
    the reader was shown a number with nothing saying millimetres per hour.
    """
    set_locale("uk")
    assert display_reference(ESKULAB_BLOCKS["esr"], 34, "male") == "Чоловіки 17 - 50р: < 15мм/год"
    set_locale("en")
    assert display_reference(ESKULAB_BLOCKS["esr"], 34, "male") == "men 17 - 50y: < 15mm/h"
    assert display_reference(ESKULAB_BLOCKS["esr"], 60, "male") == "men over 50y: <20mm/h"
    # The unit rides along without disturbing the numbers read off the band.
    assert applicable_reference_bounds(ESKULAB_BLOCKS["esr"], 34, "male") == (None, 15.0)


def test_the_english_page_never_shows_a_ukrainian_decimal_comma():
    """Separators are localized too, and a labelled band skips every whole-string
    form that already converted them: «adults 18-60 years: 2,15-2,5» reached the
    English page verbatim once the band selector started surfacing lab labels."""
    set_locale("en")
    assert display_reference(ESKULAB_BLOCKS["calcium"], 34, "male") == "adults 18-60 years: 2.15-2.5"
    assert display_reference("0,5 mg/dl") == "0.5 mg/dl"
    set_locale("uk")
    # Ukrainian keeps the comma it was printed with.
    assert display_reference(ESKULAB_BLOCKS["calcium"], 34, "male") == "дорослі 18-60 років: 2,15-2,5"


def test_a_year_abbreviation_is_not_the_first_letter_of_a_birth_date():
    """«14.03.1990 р.н.» -- "року народження" -- was rendered "14.03.1990 y.н.".

    The single-letter «р» is EskuLab's year, and the shared word boundaries let
    it through here because what follows is a full stop rather than a letter.
    A year abbreviation is never followed by another word; this one always is.
    """
    assert translate_reference_fragments("14.03.1990 р.н.") == "14.03.1990 р.н."
    # The year itself still translates, in each form the reports write it.
    assert translate_reference_fragments("Чоловіки 17 - 50р") == "men 17 - 50y"
    assert translate_reference_fragments("1-12р.") == "1-12y"
    assert translate_reference_fragments("До 1 р.: 2-12") == "up to 1 y: 2-12"


def test_one_unit_has_one_english_spelling():
    """«ГЄ/мл» and «ГЕ/мл» are the same unit, spelled with the two Cyrillic
    homoglyphs.  A duplicate key gave them two different English strings, and
    the later one won: one Ureaplasma report said "genome equivalents/mL" and
    the next said "GE/mL"."""
    assert REFERENCE_FRAGMENTS_EN["ге/мл"] == REFERENCE_FRAGMENTS_EN["гє/мл"]
    assert translate_reference_fragments("Клінічно значуща кількість >10 ГЕ/мл") == (
        "clinically significant quantity >10 genome equivalents/mL"
    )


def test_every_population_and_age_word_a_surfaced_band_can_carry_is_translated():
    """`reference_display` answers Cyrillic-under-English with "not supplied".

    So a band whose label the catalogue does not cover is not merely untidy: the
    English reader is told no range was printed, while
    `applicable_reference_bounds` is at that moment judging the value against
    it.  «Чоловік» -- EskuLab's singular row heading on the absolute eosinophil
    count -- did exactly that.
    """
    set_locale("en")
    cyrillic = re.compile(r"[Ѐ-ӿ]")
    for key, block in ESKULAB_BLOCKS.items():
        for age, sex in ((34, "male"), (34, "female"), (60, "male"), (14, "male"), (7, "male")):
            band = applicable_band(block, age, sex)
            if band is not None:
                assert not cyrillic.search(display_reference(block, age, sex)), (key, age, sex)
    assert translate_reference_fragments("Чоловік: 0,04-0,54") == "men: 0,04-0,54"
    assert translate_reference_fragments("6-12 місяців") == "6-12 months"
    assert translate_reference_fragments("До 2тиж.") == "up to 2wk"
    assert translate_reference_fragments("Діти 0-5 днів") == "children 0-5 days"


def test_a_treatment_target_scale_is_not_a_reference_interval():
    """Non-HDL cholesterol prints four ESC/EAS targets, one per risk group.

    Nothing on the report says which group the patient is in, so whichever
    target the print order put first was being shown as his limit.
    """
    non_hdl = (
        "Цільовий рівень ХС не- ЛПВЩ для груп пацієнтів по SCORE2, ESC/EAS 2019: "
        "< 2,2 дуже високого ризику < 2,6 високого ризику < 3,4 помірного ризику "
        "< 3.8 низького ризику"
    )
    assert reference_bounds(non_hdl) == (None, None)
    assert applicable_reference_bounds(non_hdl, 34, "male") == (None, None)
    # A negative/positive scale still yields its negative band.
    assert reference_bounds("негативний: < 1.0 позитивний: ≥ 1.0") == (None, 1.0)


def test_one_interval_labelled_for_both_sexes_is_not_a_per_sex_table():
    """«Чоловіки/Жінки: 28-100» is one range, not a row each.

    `_sex_clause` exists to hand a patient his half of a two-row table, and it
    splits at the second sex named.  Here there is nothing to split: the male
    half is the bare word «Чоловіки/» and the only numbers on the line are
    stranded in the other half, so amylase 63.8 U/L was shown with no interval
    while 28-100 was printed beside it on the report.
    """
    both = "Чоловіки/Жінки: 28-100"
    assert applicable_reference_bounds(both, 34, "male") == (28.0, 100.0)
    assert applicable_reference_bounds(both, 34, "female") == (28.0, 100.0)
    # A genuine per-sex table still gives each patient their own row.
    per_sex = "Чоловік: 0,04-0,54 Жінки: 0,04-0,36"
    assert applicable_reference_bounds(per_sex, 34, "male") == (0.04, 0.54)
    assert applicable_reference_bounds(per_sex, 34, "female") == (0.04, 0.36)
