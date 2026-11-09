"""The ingest regexes rewritten for linear matching answer exactly as before.

Each case pairs the pattern as it used to be written with what replaced it,
and checks both on printed lines in the shapes the parsers meet and on a
seeded random corpus built from the same pieces.  A regex in `ingest/` that
silently stops matching drops a clinical value with no error, so the check
is on behaviour, not on reading the patterns.

Three of the old patterns differed from their replacement only on input the
code never gives them: lines that are already `collapse_space`d (no newline,
no leading or trailing space).  Those are checked on that domain, and the
domain is what their callers guarantee.
"""
from __future__ import annotations

import random
import re

import pytest

from anamna.ingest import classifier, pipeline, positions
from anamna.ingest.text import collapse_space

PIECES = [
    " ", "  ", "\t", "\n", " \n", " ", "a", "Z", "Б", "сеч", "1", "42", "3.5", "0,5", ".", "...", "…",
    "(", ")", "( ", " )", ",", ", ", "/", "%", "-", "–", "—", "до", "ДО", "MRI", "MRI 12", "МРТ ",
    "A4001", "(A4001)", "(2 ДНІ)", "(12 ГОДИН)", "(24 год.)", "(B075)", "Київ", "Львів", " Одеса",
    "Індикатор зони підвищеної уваги", "од.", "мг", "г/л", "клітин", "Ділянка тіла:", "Ділянка обстеження:",
    "Локалізація патологічного процесу", "ультразвукове дослідження", "УЛЬТРАЗВУКОВОГО ОБСТЕЖЕННЯ",
    "дуплексного ", "протокол ", "1. F2005 ", "12. A1234", "(кал)", "(сеча) ",
]


def corpus(count: int = 4000, seed: int = 20261107) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice(PIECES) for _ in range(rng.randint(0, 9))) for _ in range(count)]


def lines(count: int = 4000) -> list[str]:
    """The domain of the line-level patterns: collapsed, non-empty lines."""
    return sorted({line for line in map(collapse_space, corpus(count)) if line})


PRINTED = [
    "ЗАЛІЗО (СИРОВАТКА КРОВІ) (A4001)",
    '"ЗАГАЛЬНИЙ АНАЛІЗ КРОВІ (B075)  (2 ДНІ)"',
    "ГЛЮКОЗА (12 ГОДИН)",
    "Біохімія Індикатор зони підвищеної уваги",
    "Індикатор зони підвищеної уваги  Пакет №1 (Ліпідограма)",
    "Біохімія Київ",
    "БіохіміяКиїв",
    "Аналіз крові розгорнутий (ЗАК) Львів",
    "Консультація невролога повторна, з урахуванням результа...",
    "Консультативний висновок…",
    "ОГК, рентгенографія в дві...",
    "ультразвукове дослідження органів черевної порожнини",
    "Протокол дуплексного ультразвукового обстеження вен нижніх кінцівок",
    "ультразвукове дослідження",
    "2. F2005 Пакет №6. Ліпідограма",
    "1. F5000 Коагулограма",
    "Локалізація патологічного процесу - м'які тканини стегна",
    "Локалізація патологічного процесу–ліва пахвова ділянка",
    "МРТ поперекового відділу хребта MRI 18187",
    "МРТ колінного суглоба MRI12 MRI 3",
    "Ділянка тіла: ОГК",
    "Ділянка обстеження: органи грудної клітки...",
    "Колір (кал)",
    "Нейтрофіли (GRAN) (%) ",
    "Питома вага, г/мл",
    "Нейтрофіли, сегментоядерні",
    "Тромбоцити, x10*9/л",
    "Час, сек",
    "Білок, мг ",
    "Еритроцити, кл. ",
    "3.5 - 5.5",
    "0,5 до 2",
    "< 5",
    "> 0.2",
    "-1 – -0.5",
    "до 5",
    "1-",
]


def _old_sub(pattern: str, repl: str, flags: int = 0):
    compiled = re.compile(pattern, flags)
    return lambda value: compiled.sub(repl, value)


EXACT = {
    # name: (old behaviour, new behaviour)
    "heading codes": (
        _old_sub(r"\s*\((?:[A-ZА-ЯІЇЄҐ]\d{3,5}|\d+\s*(?:дн[іяь]|днів|день|годин[аи]?|год)\.?)\)", "", re.I),
        lambda value: classifier._sub_with_space_before(classifier.HEADING_CODE_RE, "", value),
    ),
    "synevo indicator sub": (
        _old_sub(r"\s*Індикатор зони підвищеної уваги\s*", " "),
        lambda value: classifier._sub_with_space_before(classifier.SYNEVO_INDICATOR_RE, " ", value),
    ),
    "synevo indicator search": (
        lambda value: bool(re.search(r"\s*Індикатор зони підвищеної уваги\s*", value)),
        lambda value: bool(classifier.SYNEVO_INDICATOR_RE.search(value)),
    ),
    "space before closing bracket": (
        _old_sub(r"\s+\)", ")"),
        lambda value: classifier._sub_with_space_before(classifier.CLOSING_BRACKET_RE, ")", value),
    ),
    "mri study number": (
        _old_sub(r"\s*\bMRI\s*\d+\b", ""),
        lambda value: classifier._sub_with_space_before(classifier.MRI_STUDY_NUMBER_RE, "", value),
    ),
    "ultrasound heading": (
        lambda value: (m := re.match(
            r"^(?:протокол\s+)?(дуплексного\s+)?ультразвуков(?:ого|е)\s+(?:дослідження|обстеження)\b\s*(.*)$",
            value, re.I,
        )) and m.groups(),
        lambda value: (m := classifier.ULTRASOUND_HEADING_RE.match(value)) and m.groups(),
    ),
    "reference range": (
        lambda value: bool(re.search(r"-?\d+(?:[.,]\d+)?\s*(?:до|[-–—])\s*-?\d", value, re.I)),
        lambda value: bool(pipeline._RANGE_RE.search(value)),
    ),
    "unit tail": (
        _old_sub(r",\s*(?:[^,]*[/%][^,]*|од\.?|мм|сек|с|мг|г|кл|клітин)\s*$", "", re.I),
        pipeline._strip_unit_tail,
    ),
    "specimen qualifier words": (
        lambda value: re.sub(r"\s*\([^()]*\)\s*$", "", value).split(),
        lambda value: positions._QUALIFIER.sub("", value).split(),
    ),
}

ON_LINES = {
    "synevo city": (
        _old_sub(r"\s+(?:Київ|Львів|Харків|Одеса|Дніпро)$", ""),
        classifier._strip_synevo_city,
    ),
    "truncated tail": (
        _old_sub(r"\s*\S*(?:\.{3}|…)$", ""),
        classifier._strip_truncated_tail,
    ),
    "esculab heading": (
        lambda value: (m := re.match(r"^\d+\.\s+[A-Z]\d{4}\s+(.+)$", value)) and m.group(1),
        lambda value: (m := classifier.ESCULAB_HEADING_RE.match(value)) and m.group(1),
    ),
    "ultrasound site": (
        lambda value: (m := re.match(r"^Локалізація патологічного процесу\s*[–-]\s*(.+)$", value)) and m.group(1),
        lambda value: (m := classifier.ULTRASOUND_SITE_RE.match(value)) and m.group(1),
    ),
    "body region": (
        lambda value: (m := re.match(r"^Ділянка (?:обстеження|тіла):\s*(.+)$", value)) and m.group(1),
        lambda value: (m := classifier.BODY_REGION_RE.match(value)) and m.group(1),
    ),
}


@pytest.mark.parametrize("name", sorted(EXACT))
def test_rewritten_pattern_answers_as_before_on_any_text(name):
    old, new = EXACT[name]
    for value in PRINTED + corpus():
        assert new(value) == old(value), (name, value)


@pytest.mark.parametrize("name", sorted(ON_LINES))
def test_rewritten_pattern_answers_as_before_on_collapsed_lines(name):
    old, new = ON_LINES[name]
    for value in [collapse_space(line) for line in PRINTED] + lines():
        assert new(value) == old(value), (name, value)


def _fired(result, value: str) -> bool:
    if isinstance(result, str):
        return result != value
    if isinstance(result, list):
        return result != value.split()
    return bool(result)


def test_the_corpus_exercises_both_answers():
    """A check that never sees a match proves nothing about matching."""
    for cases, values in (
        (EXACT, PRINTED + corpus()),
        (ON_LINES, [collapse_space(line) for line in PRINTED] + lines()),
    ):
        for name, (old, _) in cases.items():
            assert {_fired(old(value), value) for value in values} == {True, False}, name


def test_unit_tail_strip_answers_as_the_single_alternation_did():
    """The two tail shapes, now two patterns, cut what one alternation cut --
    including where both fit, or one fits at an earlier comma."""
    old = re.compile(r",(?:[^,/%]*[/%][^,]*|\s*(?:од\.?|мм|сек|с|мг|г|кл|клітин)\s*)$", re.I)
    pieces = [",", ", ", " ", "\n", "г/л", "%", "/", "мг", "МГ", "од.", "од", "сек", "с", "кл", "клітин", "x", "Б"]
    rng = random.Random(7)
    values = PRINTED + ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 8))) for _ in range(20000)]
    values += ["a" + ", мг" * 200, "a" + " " * 300 + ", г/л" + " " * 300]
    cut = 0
    for value in values:
        expected = old.sub("", value)
        assert pipeline._strip_unit_tail(value) == expected, value
        cut += expected != value
    assert cut > 2000, cut


def test_expert_unpadding_answers_as_before():
    from anamna.labsync import expert

    old = re.compile(r"(?<![\d.,])(\d+)[.,](\d+)(?!\d)")
    pieces = ["0", "00", "5", "38", ".", ",", " ", "Від ", "до", "x", "\n", "-", "1.50", "2,000", "7.0"]
    rng = random.Random(11)
    values = ["5.380000", "Від 0.000000 до 2.590000", "5.38", "12,500", "1.2.3000", "a5.10"]
    values += ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 10))) for _ in range(20000)]
    values += ["1" * 400 + "x", "1" * 400 + ".", "1." * 300, "x" + "0" * 400 + ".000"]
    trimmed = 0
    for value in values:
        expected = old.sub(expert._unpad, value)
        assert expert._trim(value) == expected, value
        trimmed += expected != value
    assert trimmed > 1000, trimmed


def test_known_lines_keep_their_reading():
    assert classifier.normalise_heading('"ЗАГАЛЬНИЙ АНАЛІЗ КРОВІ (B075)  (2 ДНІ)"') == "ЗАГАЛЬНИЙ АНАЛІЗ КРОВІ"
    assert classifier._strip_synevo_city("Біохімія Київ") == "Біохімія"
    assert classifier._strip_synevo_city("БіохіміяКиїв") == "БіохіміяКиїв"
    assert classifier._strip_truncated_tail("ОГК, рентгенографія в дві...") == "ОГК, рентгенографія в"
    assert pipeline.reference_inclusivity("3.5 - 5.5", 3.5, 5.5) == (1, 1)
    assert pipeline.reference_inclusivity("< 5", None, 5) == (1, 0)
    assert pipeline._label_key("Питома вага, г/мл") == pipeline._label_key("Питома вага")
    assert pipeline._label_key("Нейтрофіли, сегментоядерні") != pipeline._label_key("Нейтрофіли")
