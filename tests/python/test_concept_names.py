from __future__ import annotations

import re

from anamna.health import concept_display_name
from anamna.i18n import set_locale
from anamna.ingest.concepts import CONCEPT_DEFINITIONS
from anamna.locales.concepts_en import CONCEPT_NAMES_EN
from anamna.locales.concepts_uk import CONCEPT_NAMES_UK


CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def test_keys_are_data_derived_allergen_names():
    """Every key is a Ukrainian name imported from the source report.

    seed_concepts() defines only English canonical names, so a key that
    collided with a seeded concept would mean the table is translating
    something it does not own.
    """
    seeded = {str(definition["name"]) for definition in CONCEPT_DEFINITIONS}
    for canonical in CONCEPT_NAMES_EN:
        assert CYRILLIC.search(canonical), canonical
        assert canonical not in seeded, canonical


def test_no_english_value_is_left_untranslated():
    for canonical, english in CONCEPT_NAMES_EN.items():
        assert not CYRILLIC.search(english), f"{canonical} -> {english}"


def test_allergen_codes_survive_translation():
    """The WHO/IUIS code is how a clinician recognises the allergen."""
    for canonical, code in [
        ("Насіння пажитника Tri fo", "Tri fo"),
        ("Ara h 15 Олеозин", "Ara h 15"),
        ("Європейський кліщ домашнього пилу Der p 1 Cysteine protease", "Der p 1"),
        ("Береза повисла Bet v 1 PR-10", "Bet v 1"),
        ("Баранина Ovi a_meat", "Ovi a_meat"),
    ]:
        assert code in CONCEPT_NAMES_EN[canonical]


def test_concept_display_name_switches_locale():
    samples = [
        # Allergen: Ukrainian canonical, so English is the translated side.
        ("Насіння пажитника Tri fo", "Fenugreek seed (Tri fo)", "Насіння пажитника Tri fo"),
        ("Ara h 15 Олеозин", "Ara h 15, Oleosin", "Ara h 15 Олеозин"),
        ("Ory c 2 Ліпофілін", "Ory c 2, Lipophilin", "Ory c 2 Ліпофілін"),
        # Non-allergen: English canonical, Ukrainian from CONCEPT_NAMES_UK.
        ("Creatinine", "Creatinine", CONCEPT_NAMES_UK["Creatinine"]),
        ("Hemoglobin", "Hemoglobin", CONCEPT_NAMES_UK["Hemoglobin"]),
    ]
    try:
        set_locale("en")
        for canonical, english, _ in samples:
            assert concept_display_name(canonical) == english
        set_locale("uk")
        for canonical, _, ukrainian in samples:
            assert concept_display_name(canonical) == ukrainian
    finally:
        set_locale("en")


def test_unknown_and_empty_names_pass_through():
    try:
        set_locale("en")
        assert concept_display_name("Total cholesterol") == "Total cholesterol"
        assert concept_display_name(None) == ""
        assert concept_display_name("") == ""
    finally:
        set_locale("en")
