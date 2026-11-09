"""Round-2 value-by-value review (2026-11-07): printed references that gave no verdict.

The reference blocks are the shapes the laboratories print, with their published
intervals; no patient line, order number or barcode is copied.
"""

from __future__ import annotations

import pytest

from anamna.health import applicable_band, applicable_reference_bounds
from anamna.ingest.parsers import parse_document, reference_limits
from anamna.ingest.pipeline import interpretation
from anamna.reference import _vendor_verdict

from test_parser_esculab_review_1107 import CULTURES, page
from test_parser_lab_defects_1107 import ESCULAB_HEADER, layout

ALT = (
    "12-17 років (ж): до 24,0 6-12 років: до 39,0 3-6 років: до 29,0 1-3 років: до 33,0 "
    "6-12 місяців: до 54,0 5 днів-6 місяців: до 56,0 Діти 0-5 днів: до 49,0 жін.: до 33 чол.: до 41 "
    "12-17 років (ч): до 27,0"
)
BILIRUBIN = "Дорослі: до 21 Діти ≥ 1 міс.: до 17"
PROTEIN = "Дорослі 66,0-87,0 1 день - 4 тижні: 46,0-68,0 2-12 місяців: 48,0-76,0 старші 1 року: 60,0-80,0"
GLIADIN = "до 1 року: <30 1-6 років: <40 6-12 років: <35 старше 12 років: <25"
HE4 = "до 40 р.: <60,5 40-49 р: <76,2 50-59 р.: <74,3 60-69 р.: <82,9 старше ≥70 р.: <104,0"
ROMA = (
    "жінки репродуктивного віку ≥7.4% - високий ризик виявлення епітеліального РЯ "
    "жінки репродуктивного віку <7.4% - низький ризик виявлення епітеліального РЯ"
)
STOOL_PH = (
    "7. 0 - 7.5: в нормі нейтральна або слаболужна 5.5 – 6.75: кисла < 5.5: різко кисла "
    "8.0 – 8.5: лужна > 8.5: різко лужна"
)
ESR = (
    "Діти до 17р: <10мм/год Чоловіки 17 - 50р: < 15мм/год Чоловіки старші 50р: <20мм/год "
    "Жінки 17-50р: <20мм/год Жінки старші 50р. :. <30мм/год"
)


@pytest.mark.parametrize(
    ("reference", "age", "sex", "bounds"),
    [
        # 1. «жін.» / «чол.» and the worded upper bound «до N».
        (ALT, 30, "female", (None, 33.0)),
        (ALT, 30, "male", (None, 41.0)),
        (ALT, 14, "female", (None, 24.0)),
        # 2. «Дорослі: до 21», and the adults' row printed with no colon.
        (BILIRUBIN, 30, "female", (None, 21.0)),
        (PROTEIN, 30, "female", (66.0, 87.0)),
        # The open «older than one year» band is the children's tail, not the adults'.
        (PROTEIN, 5, "female", (60.0, 80.0)),
        # 3. «старше 12 років».
        (GLIADIN, 30, "female", (None, 25.0)),
        # 5. HE4's «до 40 р.» reads as «<40 р.» does.
        (HE4, 30, "female", (None, 60.5)),
        (HE4, 45, "female", (None, 76.2)),
        # 5. ROMA: the low-risk side of the printed cut-off; never a man's.
        (ROMA, 30, "female", (None, 7.4)),
        (ROMA, 30, "male", (None, None)),
        # 6. «7. 0» is 7.0: the scale's «в нормі» band, not «0 - 7.5».
        (STOOL_PH, 30, "female", (7.0, 7.5)),
        # The stray point after the colon no longer loses the band.
        (ESR, 60, "female", (None, 30.0)),
    ],
)
def test_printed_bands_that_gave_no_verdict_now_give_this_patients_bounds(reference, age, sex, bounds):
    assert applicable_reference_bounds(reference, age, sex) == bounds


def test_a_value_on_the_roma_cut_off_is_high_risk():
    from anamna.ingest.parsers import _demographic_limits

    limits = _demographic_limits(ROMA, 30, "female", 10.2)
    assert (limits.high, limits.high_inclusive) == (7.4, False)
    assert _vendor_verdict(10.2, "%", limits.low, limits.high, None)["interpretation"] == "high"


def test_acidic_stool_ph_is_below_the_normal_band():
    low, high = applicable_reference_bounds(STOOL_PH, 30, "female")
    assert _vendor_verdict(6.75, None, low, high, None)["interpretation"] == "low"


# --- 7. Equally specific bands that agree --------------------------------------------


def test_tied_bands_that_read_the_value_alike_give_their_verdict():
    # At fifty a woman is inside both «17-50р» and «старші 50р».
    assert applicable_band(ESR, 50, "female") is None
    low, high = applicable_reference_bounds(ESR, 50, "female", 6.0)
    assert high in {20.0, 30.0}
    assert _vendor_verdict(6.0, None, low, high, None)["interpretation"] == "normal"
    # Above both limits is high under either band.
    low, high = applicable_reference_bounds(ESR, 50, "female", 35.0)
    assert _vendor_verdict(35.0, None, low, high, None)["interpretation"] == "high"
    # Between them the bands disagree, and nothing is chosen.
    assert applicable_reference_bounds(ESR, 50, "female", 25.0) == (None, None)


def test_age_windows_are_never_read_as_agreeing_intervals():
    """«Жінки: 18-25 р.: ...» offered its age windows as intervals; a low value
    "agreed" with all of them and was judged against 18-25."""
    block = (
        "Діти (ж) ≤ 60 д.: 0.01 - 3.39 Жінки: 18-25 р.: 0.96-13.34 Жінки: 26-30 р.: 0.17-7.37 "
        "Жінки: 31-35 р.: 0.07-7.35 Жінки: ≥46 р.: <1.15 Чоловіки >18 р.: 0.73-16.05"
    )
    # The heading's colon no longer hides the age band: each woman gets her own.
    assert applicable_band(block, 33, "female") == "Жінки 31-35 р.: 0.07-7.35"
    assert applicable_reference_bounds(block, 50, "female", 0.5) == (None, 1.15)
    assert applicable_reference_bounds(block, 34, "male", 2.0) == (0.73, 16.05)
    # No woman's band covers 40: nothing, however the value reads.
    assert applicable_reference_bounds(block, 40, "female", 2.0) == (None, None)
    # The same label offering several intervals is a misread block, not a tie.
    misread = "Жінки: 18-25 Жінки: 26-30 Жінки: 31-35"
    assert applicable_band(misread, 33, "female", 2.0) is None


# --- 4. Colony counts in powers of ten -----------------------------------------------


@pytest.mark.parametrize(
    ("reference", "limits"),
    [
        ("не більше 1.0 x 10^4 КУО", (None, 1e4, True, True)),
        ("Не менше 1.0*10^6 КУО/г", (1e6, None, True, True)),
        ("в нормі < 10^4 КУО/г", (None, 1e4, True, False)),
        ("в нормі - 10^7 КУО/г - 10^9 КУО/г", (1e7, 1e9, True, True)),
        ("в нормі 10^4 - 10^9", (1e4, 1e9, True, True)),
        ("в нормі >10^6 КУО", (1e6, None, False, True)),
        # A PCR threshold names no count norm and stays refused.
        (">10^4 ГЄ/мл", (None, None, True, True)),
    ],
)
def test_a_colony_count_norm_is_read_with_its_powers_written_out(reference, limits):
    assert tuple(reference_limits(reference)) == limits


def test_culture_counts_are_judged_against_their_norms():
    rows = {
        (item.specimen, item.raw_name): item
        for item in parse_document("Esculab", "microbiology", [page(CULTURES)])
    }
    assert interpretation(rows[("кал", "Staphylococcus epidermidis")]) == "high"
    assert interpretation(rows[("кал", "Lactobacillus spp.")]) == "low"
    assert interpretation(rows[("кал", "Escherichia coli з нормальними властивостями")]) == "within_vendor_range"


# --- 8. A unit wrapped at its solidus --------------------------------------------------


def test_a_unit_wrapped_onto_the_next_line_rejoins_without_a_blank():
    lines = [
        ESCULAB_HEADER,
        (220.0, "ШОЕ@28.3 за@54 Вестергреном@67 6@254 мм/год@322 Жінки@378 17-50р:@404 <20мм/@433"),
        (230.0, "год@378"),
    ]
    (esr,) = [row for row in parse_document("Esculab", "laboratory", [layout(lines)]) if row.raw_name.startswith("ШОЕ")]
    assert esr.reference_text == "Жінки 17-50р: <20мм/год"


# --- Both locales show the band the verdict used ---------------------------------------


@pytest.mark.parametrize(
    ("locale", "reference", "age", "sex", "value", "shown"),
    [
        ("en", ALT, 30, "female", None, "women: up to 33"),
        ("uk", ALT, 30, "male", None, "чол.: до 41"),
        ("en", HE4, 30, "female", None, "up to 40 y: <60.5"),
        ("en", STOOL_PH, 30, "female", None,
         "7.0 - 7.5: normal, neutral or slightly alkaline 5.5 – 6.75: acidic < 5.5: strongly acidic "
         "8.0 – 8.5: alkaline > 8.5: strongly alkaline"),
        ("uk", STOOL_PH, 30, "female", None,
         "7,0 - 7,5: в нормі нейтральна або слаболужна 5,5 – 6,75: кисла < 5,5: різко кисла "
         "8,0 – 8,5: лужна > 8,5: різко лужна"),
        ("en", ROMA, 30, "female", None,
         "women of reproductive age ≥7.4% - high risk of epithelial ovarian cancer "
         "women of reproductive age <7.4% - low risk of epithelial ovarian cancer"),
        ("en", "не більше 1.0 x 10^4 КУО", 30, "female", None, "no more than 1.0 x 10^4 CFU"),
        ("en", ESR, 50, "female", 6.0, "women over 50y: <30mm/h"),
    ],
)
def test_the_reference_shown_is_the_one_judged_in_both_locales(locale, reference, age, sex, value, shown):
    from anamna.i18n import activate_locale, reset_locale
    from anamna.web.app import reference_display

    token = activate_locale(locale)
    try:
        assert reference_display(reference, age, sex, value) == shown
    finally:
        reset_locale(token)
