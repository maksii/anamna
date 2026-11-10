"""Audit defects in the unit-row parser: each test pins the fix and its neighbours."""

from __future__ import annotations

import pytest

from anamna.ingest.classifier import extract_date
from anamna.ingest.parsers import parse_unit_rows, reference_bounds
from anamna.ingest.pipeline import stored_unit
from anamna.ingest.text import parse_decimal
from anamna.reference import canonical_unit


def rows(text: str):
    return [
        (o.raw_name, o.value_numeric, o.unit_raw, o.reference_low, o.reference_high)
        for o in parse_unit_rows(text, 1)
    ]


def test_thousands_separator_joins_only_when_the_interval_proves_it():
    # 250 000 fits 150 000 - 400 000 (within a factor of ten); 250 alone fits nothing.
    assert rows("Тромбоцити 250 000 кл/мкл 150000 - 400000") == [
        ("Тромбоцити", 250000.0, "кл/мкл", 150000.0, 400000.0)
    ]
    assert rows("Тромбоцити 250 000 кл/мкл 150 000 - 400 000") == [
        ("Тромбоцити", 250000.0, "кл/мкл", 150000.0, 400000.0)
    ]
    assert rows("Лейкоцити 1 250 000 кл/мкл 150000 - 400000") == [
        ("Лейкоцити", 1250000.0, "кл/мкл", 150000.0, 400000.0)
    ]
    # The number stays in the name when the joined value breaks the interval, or
    # the group alone already fits it: a name that takes a number keeps it.
    assert rows("Інтерлейкін 6 150 пг/мл 0 - 7") == [("Інтерлейкін 6", 150.0, "пг/мл", 0.0, 7.0)]
    assert rows("CA 125 350 Од/мл 0 - 35") == [("CA 125", 350.0, "Од/мл", 0.0, 35.0)]
    assert rows("Креатинін 1 234 мкмоль/л 62 - 106") == [
        ("Креатинін 1", 234.0, "мкмоль/л", 62.0, 106.0)
    ]
    assert rows("Вітамін B 12 350 пг/мл 191 - 663") == [
        ("Вітамін B 12", 350.0, "пг/мл", 191.0, 663.0)
    ]
    # No printed interval proves anything, so nothing is joined.
    assert rows("Інтерлейкін 6 150 пг/мл") == [("Інтерлейкін 6", 150.0, "пг/мл", None, None)]
    assert rows("Креатинін 1 234 мкмоль/л") == [("Креатинін 1", 234.0, "мкмоль/л", None, None)]
    assert rows("Вітамін B 12 350 пг/мл") == [("Вітамін B 12", 350.0, "пг/мл", None, None)]
    assert rows("Імуноглобулін G 4 350 мг/дл") == [("Імуноглобулін G 4", 350.0, "мг/дл", None, None)]


def test_a_group_starting_with_zero_is_always_thousands():
    # «000» and «050» are never a value printed on its own: the group before
    # them is its thousands, with or without a printed interval.
    assert rows("Тромбоцити 250 000 кл/мкл") == [("Тромбоцити", 250000.0, "кл/мкл", None, None)]
    assert rows("Лейкоцити 4 050 кл/мкл") == [("Лейкоцити", 4050.0, "кл/мкл", None, None)]
    assert rows("Інтерлейкін 6 150 пг/мл") == [("Інтерлейкін 6", 150.0, "пг/мл", None, None)]
    assert rows("Креатинін 1 234 мкмоль/л") == [("Креатинін 1", 234.0, "мкмоль/л", None, None)]


@pytest.mark.parametrize(
    "reference, expected",
    [
        ("1 000 - 2 000", (1000.0, 2000.0)),
        ("3,5 - 5,1", (3.5, 5.1)),
        ("0 - 5", (0.0, 5.0)),
        ("150000 - 400000", (150000.0, 400000.0)),
        ("10 20", (None, None)),
    ],
)
def test_thousands_spaced_reference_bounds(reference, expected):
    assert reference_bounds(reference) == expected


def test_minus_sign_is_kept_for_base_excess_only():
    assert rows("BE - 2,3 ммоль/л -2 - 3") == [("BE", -2.3, "ммоль/л", -2.0, 3.0)]
    assert rows("BE -2,3 ммоль/л") == [("BE", -2.3, "ммоль/л", None, None)]
    assert rows("BE −2,3 ммоль/л") == [("BE", -2.3, "ммоль/л", None, None)]
    assert reference_bounds("-2 - 3") == (-2.0, 3.0)
    assert parse_decimal("−2,3") == -2.3
    # A dash is a separator for every other analyte, and a glued sign on one is dropped.
    assert rows("Глюкоза - 5,2 ммоль/л") == [("Глюкоза", 5.2, "ммоль/л", None, None)]
    assert rows("Глюкоза -5,2 ммоль/л") == []


def test_range_printed_before_the_unit_is_not_a_result():
    assert rows("Норма: 3,9 - 5,5 ммоль/л") == []
    assert rows("Глюкоза 7,0 - 7,5 ммоль/л") == []
    assert rows("Reference range 3,0 ммоль/л") == []
    # A label wrapped inside an open bracket ends in «25-», not in a range.
    wrapped = rows("Вітамін Д (25-гідроксивітамін D, 25- 31.0 нг/мл")
    assert [(value, unit) for _, value, unit, _, _ in wrapped] == [(31.0, "нг/мл")]


def test_birth_date_is_never_the_report_date():
    # Expert Hospital: the birth date precedes «р.н.», the order date follows it.
    header = "Пацієнт: Іваненко Іван Іванович, 01.01.1990 р.н. 02.03.2025"
    assert extract_date(header, "x.pdf") == "2025-03-02"
    # A bare birth date after «р.н.» is never the report date.
    text = "Пацієнт: ІВАНОВ І.І. р.н. 12.03.1980\nДата друку: 03.08.2026"
    assert extract_date(text, "x.pdf") in (None, "2026-08-03")


def test_susceptibility_r_is_not_a_unit_but_mumps_indices_are():
    assert rows("Амікацин 16 R") == []
    assert rows("Мумпс IgG 16 AI") == [("Мумпс IgG", 16.0, "AI", None, None)]
    mumps = rows("Вірус паротиту, антитіла IgM 0.36 R R < 0.8 Негативний")
    assert [(name, value, unit) for name, value, unit, _, _ in mumps] == [
        ("Вірус паротиту, антитіла IgM", 0.36, "R")
    ]


def test_unspaced_x10_unit_folds_like_the_spaced_one():
    assert canonical_unit("х10*9/л") == canonical_unit("х 10*9/л") == "10^9/l"
    assert canonical_unit("х10*12/л") == canonical_unit("х 10*12/л") == "10^12/l"


def test_grams_per_millilitre_folds_only_for_specific_gravity():
    assert canonical_unit("г/мл") == "г/мл"
    assert stored_unit("г/мл", None, "urine-specific-gravity") == ""
    assert stored_unit("г/мл", None, "creatinine") == "г/мл"
