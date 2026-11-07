"""Units folded per concept, and only where the two spellings are one quantity."""

from __future__ import annotations

import pytest

from anamna.health import CONCEPT_UNIT_ALIASES, display_unit, display_value
from anamna.i18n import set_locale
from anamna.ingest.pipeline import stored_unit
from anamna.reference import canonical_unit, convert_value


@pytest.mark.parametrize(
    "concept_id, printed, preferred, expected",
    [
        # Expert Hospital heads the column wrong; the value is the % / ratio.
        ("plateletcrit", "х 10*9/л", "%", "%"),
        ("inr", "%", "ratio", "ratio"),
        # Synevo's «Од» on the atherogenic ratio is the same dimensionless number.
        ("atherogenic-coefficient", "Од", "ratio", "ratio"),
        # Specific gravity has no unit; «г/мл» is the lab's label, not a quantity.
        ("urine-specific-gravity", "г/мл", None, None),
        # A real unit stays exactly as printed.
        ("platelet-count", "х 10*9/л", "10^9/L", "х 10*9/л"),
        ("creatinine", "мкмоль/л", "µmol/L", "мкмоль/л"),
    ],
)
def test_the_stored_unit_folds_only_per_concept(concept_id, printed, preferred, expected):
    assert stored_unit(printed, preferred, concept_id) == expected


def test_od_is_not_folded_into_ratio_outside_the_atherogenic_coefficient():
    """Bare «Од» is "units" on seromucoids -- a real quantity."""
    assert stored_unit("Од", "units", "seromucoids") == "Од"
    assert canonical_unit("Од") == "units"


def test_per_field_and_specific_gravity_fold_as_the_lab_sync_writes_them():
    """OPS-37: the lab sync adopted «г/мл» and «в п/з» from the lab's record."""
    assert canonical_unit("в п/з") == canonical_unit("per HPF")
    assert canonical_unit("г/мл") == ""
    assert stored_unit("в п/з", "per HPF", "urine-changed-erythrocytes") == "в п/з"


def test_urobilinogen_is_converted_not_relabelled():
    """µmol/L and mg/dL differ by the molar mass; a relabel would be a 17× error."""
    assert not any(concept == "urine-urobilinogen" for concept, _ in CONCEPT_UNIT_ALIASES)
    assert convert_value(17.0, "мкмоль/л", "mg/dL", "urine-urobilinogen") == pytest.approx(1.0, rel=0.01)


def test_every_concept_alias_converts_at_factor_one():
    for (concept, printed), stored in CONCEPT_UNIT_ALIASES.items():
        assert convert_value(0.3, printed, stored, concept) == 0.3


@pytest.mark.parametrize(
    "printed, ukrainian, english",
    [
        ("мм", "мм", "mm"),
        ("см/с", "см/с", "cm/s"),
        ("г/м2", "г/м²", "g/m²"),
        ("сm3", "мл", "mL"),  # a cubic centimetre is a millilitre: one unit, the library's
        ("мл/хв/1,73м2", "мл/хв/1,73 м²", "mL/min/1.73m²"),
    ],
)
def test_imaging_and_egfr_units_are_translated(printed, ukrainian, english):
    try:
        set_locale("uk")
        assert display_unit(printed) == ukrainian
        set_locale("en")
        assert display_unit(printed) == english
    finally:
        set_locale("en")


@pytest.mark.parametrize("printed", ["А (II)", "А(ІІ)", "A(II)", "а (ii)"])
def test_blood_group_spellings_display_as_one_value(printed):
    """EskuLab «А (II)» (Latin numerals) and Expert «А(ІІ)» (Cyrillic І)."""
    try:
        set_locale("uk")
        assert display_value(printed) == "А (II)"
        set_locale("en")
        assert display_value(printed) == "A (II)"
    finally:
        set_locale("en")


def test_group_zero_and_ab_render_per_language():
    try:
        set_locale("uk")
        assert display_value("O(I)") == "0 (I)"
        assert display_value("AB (IV)") == "АВ (IV)"
        set_locale("en")
        assert display_value("0 (І)") == "O (I)"
        assert display_value("АВ(ІV)") == "AB (IV)"
    finally:
        set_locale("en")
