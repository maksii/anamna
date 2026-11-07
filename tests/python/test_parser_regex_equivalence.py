"""The regexes rewritten to stop super-linear backtracking match exactly as before.

Each rewritten pattern is run beside its previous spelling on three kinds of
input, and every outcome -- whether it matched, the span, every group -- must
agree:

* every string literal in the parser tests, whole and line by line: the shapes
  the parsers are actually given;
* seeded mutations of a matching example (characters inserted, dropped and
  repeated, separators swapped), which reach the near-misses where a rewrite
  would differ;
* long runs of spaces and digits, which is where backtracking bites.

A rewrite that silently stops matching drops a clinical value with no error,
so the comparison covers every way the code calls the pattern (``match``,
``search``, ``finditer``, ``split``, ``sub``).  The previous spellings are
kept here as literals on purpose: they are the specification.
"""

from __future__ import annotations

import ast
import random
import re
from pathlib import Path

import pytest

from anamna.ingest import concepts, parsers

TESTS = Path(__file__).parent
FIXTURE_MODULES = (
    "test_parsers.py",
    "test_parsers_expert_synevo_layouts.py",
    "test_synevo_parsing.py",
    "test_ultrasound_measurements.py",
    "test_visit_measurements.py",
    "test_panels.py",
    "test_reference.py",
    "test_extraction_defects.py",
    "test_concepts_repair.py",
    "test_units_concept_aliases.py",
)


def _fixture_strings() -> list[str]:
    found: set[str] = set()
    for name in FIXTURE_MODULES:
        path = TESTS / name
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
                found.update(node.value.splitlines())
    return sorted(found)


FIXTURES = _fixture_strings()

#: Characters every mutation may insert: the whitespace classes a regex can
#: confuse, digits, the decimal and range punctuation, comparators.
NOISE = " \t\n  \x1c" + "0123456789" + ".,-–—<>≤≥:;%+*^/()" + "ax"


def _mutations(seeds: list[str], extra: str, count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    alphabet = NOISE + extra
    out: list[str] = []
    for _ in range(count):
        text = list(rng.choice(seeds))
        for _ in range(rng.randint(1, 4)):
            op = rng.random()
            position = rng.randint(0, len(text))
            if op < 0.35:
                text.insert(position, rng.choice(alphabet))
            elif op < 0.55 and text:
                del text[min(position, len(text) - 1)]
            elif op < 0.75 and text:
                index = min(position, len(text) - 1)
                text[index:index] = [text[index]] * rng.randint(1, 6)
            elif op < 0.9 and text:
                text[min(position, len(text) - 1)] = rng.choice(alphabet)
            else:
                text = text[:position]
        out.append("".join(text))
    return out


def _long_runs(seeds: list[str], length: int = 400) -> list[str]:
    # Long enough to show a quadratic pattern, short enough that the previous
    # spelling -- cubic on some of these -- still finishes in a test run.
    runs = []
    for filler in (" " * length, "1" * length, "\n" * (length // 4), " 1" * (length // 2), "1." * (length // 2)):
        runs.append(filler)
        runs.append(filler + "x")
        for example in seeds[:3]:
            half = len(example) // 2
            runs.append(example[:half] + filler + example[half:])
            runs.append(example + filler)
            runs.append(filler + example)
    return runs


def _outcome(found: re.Match | None):
    if found is None:
        return None
    return found.span(), found.groups(), found.groupdict()


def _calls(pattern: re.Pattern, methods: tuple[str, ...], text: str) -> list:
    results = []
    for method in methods:
        if method in {"match", "search", "fullmatch"}:
            results.append(_outcome(getattr(pattern, method)(text)))
        elif method == "finditer":
            results.append([_outcome(found) for found in pattern.finditer(text)])
        elif method == "split":
            results.append(pattern.split(text, maxsplit=1))
        elif method == "sub":
            results.append(pattern.sub(" ", text))
    return results


class _MatchFunction:
    """Stands in for a pattern whose ``match`` became two patterns tried in turn."""

    def __init__(self, function, flags: int = 0):
        self.match = function
        self.flags = re.compile("", flags).flags


#: (name, previous pattern, flags, current pattern, how the code calls it,
#: matching examples, characters worth mutating with).
CASES = [
    (
        "SWALLOWED_VALUE",
        r"(?<![\w^-])\d+[.,]\d+(?![\w])", 0, parsers.SWALLOWED_VALUE, ("search", "finditer"),
        ["Холестерин загальний, ммоль/л 7,35", "B12 10^9 25-гідроксивітамін 7.35"], "B",
    ),
    (
        "_BETWEEN_LIMITS",
        r"(?:від\s*)?(-?\d+(?:\.\d+)?)\s*(?:до|[-–—])\s*(?P<strict>[<])?\s*(-?\d+(?:\.\d+)?)", re.I,
        parsers._BETWEEN_LIMITS, ("search", "finditer"),
        ["від 3.5 до 5.0", "0.9 - <1.0", "Negative <1.0; equivocal 1.0-1.2; positive >1.2", "ВІД -1 ДО 2"],
        "відВІДдоДО",
    ),
    (
        "_EXPERT_MICROSCOPY",
        r"^(?P<name>.+?,\s*в\s*п/з)\s+(?P<value>\d+(?:-\d+){1,2}|\+{1,4})(?:\s+(?P<ref>.+))?$", 0,
        _MatchFunction(parsers._expert_microscopy_match), ("match",),
        [
            "Лейкоцити (WBC), в п/з 0-1 0-5", "Слиз, в п/з + (не виявлено)", "Еритроцити змінені, в п/з 0-1-2",
            # Blank-ended rows, where the reference is the last blank, and
            # line breaks inside the gap, where it is not found at all.
            "Слиз, в п/з +  ", "Слиз, в п/з + \t\n", "Слиз, в п/з 0-1 \n", "Слиз, в п/з 0-1 \n\n",
            "Слиз, в п/з 0-1 \n норма", "Слиз, в п/з 0-1 \n норма\n", "A, в п/з 1-2x B, в п/з 3-4  ",
        ],
        "вп/з",
    ),
    (
        "SEX_REFERENCE_CONTINUATION",
        r"^(?P<sex>чоловіки|жінки|men|women|male|female)\b\s*[<>≤≥]?\s*\d", re.I,
        parsers.SEX_REFERENCE_CONTINUATION, ("match",),
        ["чоловіки < 11.2", "Жінки 28.0", "male ≥ 5", "women<1"], "чоловікижінкиmen",
    ),
    (
        "_HBA1C_VALUE",
        r"(\d+[.,]\d+)\s*%\s*(.*)$", 0, parsers._HBA1C_VALUE, ("match",),
        ["5.6 % 4.0 - 5.7", "5,26%", "6.1 %  ", "5.6%\n", "5.6 % \n 4.0", "5.6 %\t\n", "5.6 % \n\n"], "",
    ),
    (
        "_HLA_B27",
        r"HLA\s*B\s*[-–]?\s*27", re.I, parsers._HLA_B27, ("search",),
        ["Виявлення носійства гену HLA B-27", "hla b – 27", "HLAB27"], "HLAB",
    ),
    (
        "_COLONY_POWER_ROW",
        r"^(?P<name>.+?)\s+10\^(?P<power>\d+)\s+(?P<unit>КУО/(?:г|мл))$", re.I, parsers._COLONY_POWER_ROW,
        ("match",),
        [
            "Staphylococcus aureus 10^5 КУО/г", "Escherichia coli  10^7  куо/Г", "  10^5 КУО/г", " 10^5 КУО/г",
            "\t 10^5 КУО/г", "\n 10^5 КУО/г", "a \n 10^5 КУО/г", "x 10^5 КУО/г 10^6 КУО/г",
            "Gardnerella vaginalis 10^5 КУО/мл", "a 10^5 КУО/мл 10^6 КУО/г",
        ],
        "КУО/г",
    ),
    (
        "_AUTOIMMUNE_PAGE",
        r"антигени\s+.*діапазон|ауто[їі]мунн.*стандартна", re.I | re.S, parsers._AUTOIMMUNE_PAGE, ("search",),
        ["Антигени   Клас  діапазон", "Аутоімунна стандартна-Х панель", "антигени\n\nдіапазон"], "",
    ),
    (
        "_AUTOIMMUNE_TAIL",
        r"^(?:(?P<cls>[0-4])\s+)?(?P<comparator>[<«‹>])?\s*(?P<value>\d+(?:[.,]\d+|\s\d{2})?)$", 0,
        parsers._AUTOIMMUNE_TAIL, ("match",),
        ["0 <0.15", "0 <0 15", "3 12.5", "<0.15", "1   <  0.3"], "«‹",
    ),
    (
        "GARMIN_READING",
        r"^(\d{2}:\d{2})\s+(\d{2,3})\s+Сис\.\s*/\s*(\d{2,3})\s+Діас\.\s+(\d{2,3})\s+bpm(?:\s+(.*))?$", re.I,
        parsers.GARMIN_READING, ("match",),
        [
            "08:15 128 Сис. / 82 Діас. 64 bpm Нормальний", "21:03 141 Сис./ 92 Діас. 70 bpm", "07:00 120 сис. / 80 ДІАС. 60 BPM  ",
            "07:00 120 Сис. / 80 Діас. 60 bpm \n", "07:00 120 Сис. / 80 Діас. 60 bpm \n Норма", "07:00 120 Сис. / 80 Діас. 60 bpm\t\n\n",
        ],
        "Сис.Діас.bpm",
    ),
    (
        "KARDIA_DETERMINATION",
        r"Kardia Advanced Determination:\s*\n?\s*([^\n*]+)", 0, parsers.KARDIA_DETERMINATION, ("search",),
        ["Kardia Advanced Determination:\nNormal Sinus Rhythm", "Kardia Advanced Determination:  *", "Kardia Advanced Determination: \n \n Unclassified*"],
        "*",
    ),
    (
        "KARDIA_DURATION",
        r"Duration:\s*\n?\s*(\d+(?:[.,]\d+)?)\s*s\b", 0, parsers.KARDIA_DURATION, ("search",),
        ["Duration: 30s", "Duration:\n 30.5 s", "Duration: \n\n 30 sec"], "s",
    ),
    (
        "_VISIT_FEVER",
        r"(?<!\w)(?:Суб)?[Фф]ебрильн\w*\s+Т\s*\(\s*(?P<value>\d{2}[.,]\d)\s*[­\-‐]?\s*на\s+прийомі\s*\)", 0,
        parsers._VISIT_FEVER, ("finditer",),
        ["Субфебрильна Т (37.2 ­на прийомі)", "фебрильна Т (38,1 - на прийомі )", "Субфебрильна Т(37.2на прийомі)"],
        "­‐",
    ),
    (
        "_US_LVMI_BAND",
        r"(\d+)\s*-\s*(\d+)\s*г/м2", 0, parsers._US_LVMI_BAND, ("finditer", "sub"),
        ["43-95 г/м2 (жінки) 49-115 г/м2 (чоловіки)", "Індекс маси міокарда ЛШ 88 43 - 95г/м2", "г/м249-115 г/м2"],
        "г/м",
    ),
    (
        "_US_LESION_SITE",
        r"Локалізація патологічного процесу\s*[-–]\s*(?P<site>.+)$", 0, parsers._US_LESION_SITE, ("match",),
        [
            "Локалізація патологічного процесу - ліве плече", "Локалізація патологічного процесу –   ", "Локалізація патологічного процесу-x\n",
            "Локалізація патологічного процесу - \n", "Локалізація патологічного процесу -\n", "Локалізація патологічного процесу - \n плече",
            "Локалізація патологічного процесу - \t\n\n", "Локалізація патологічного процесу -",
        ],
        "",
    ),
    (
        "concepts._WRAPPED_MULTIPLIER",
        r"\s+\d+(?:[.,]\d+)?\s*[xх×]\s*$", re.IGNORECASE, concepts._WRAPPED_MULTIPLIER, ("search", "sub"),
        ["Staphylococcus aureus 1.0 x", "Escherichia coli   2,5 Х  ", "  1 x\n"], "xхХ×",
    ),
    (
        "_CATEGORICAL_HEADER",
        r"Показник\s+Результат(?:\s+Од\.)?(?:\s+Одиниці)?(?:\s+Референтн\w*)?|ПОКАЗНИК\s+РЕЗУЛЬТАТ\s+НОРМА", re.I,
        parsers._CATEGORICAL_HEADER, ("search", "split"),
        ["Показник Результат Од. Одиниці Референтні\nрядок", "ПОКАЗНИК РЕЗУЛЬТАТ НОРМА\nрядок", "показник  результат"],
        "",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_rewritten_pattern_matches_as_before(case):
    name, previous, flags, current, methods, examples, extra = case
    old = re.compile(previous, flags)
    assert current.flags == old.flags, name
    inputs = FIXTURES + examples + _mutations(examples, extra, 3000, seed=len(name)) + _long_runs(examples)
    for text in inputs:
        assert _calls(current, methods, text) == _calls(old, methods, text), (name, text[:200])


def test_range_split_matches_the_split_it_replaced():
    previous = re.compile(r"\s*[-–]\s*")
    examples = ["1005-1030", "1,005 - 1,030", "5.0 – 7.0", " 1 - - 2 ", "1-  -2"]
    inputs = FIXTURES + examples + _mutations(examples, "", 3000, seed=7) + _long_runs(examples)
    for text in inputs:
        assert parsers._split_range(text) == previous.split(text), text[:200]


def test_unit_column_strip_matches_the_substitution_it_replaced():
    previous = re.compile(r"\s*:?\s*(?:мм/год|г/\s*л|%|10\*\d+\s*клітин/л|фл|пг|IU/ml|mg/l)?\s*$", re.I)
    examples = [
        "Гемоглобін (HGB) : г/л ", "Середня концентрація HGB в г/ л", "Еритроцити (RBC): 10*12 клітин/л",
        "ШОЕ (ESR) мм/год", "Ревматоїдний фактор IU/ML", "Гематокрит (HCT): %", "Лімфоцити (LYM) - % : %",
    ]
    inputs = FIXTURES + examples + _mutations(examples, "гл/фпIUmlMGклітин", 3000, seed=11) + _long_runs(examples, 120)
    for text in inputs:
        assert parsers._without_unit_column(text) == previous.sub("", text), text[:200]


def test_beta_streptococcus_pattern_lost_only_a_redundant_group():
    previous = re.compile(r"(?P<name>(?:(?:бета|beta|6eta)[-–]haemolyticum\s+Streptococcus))\s+(?:не|He)\s+виявлено", re.I)
    current = re.compile(r"(?P<name>(?:бета|beta|6eta)[-–]haemolyticum\s+Streptococcus)\s+(?:не|He)\s+виявлено", re.I)
    examples = ["beta-haemolyticum Streptococcus не виявлено", "6eta–haemolyticum  Streptococcus He виявлено"]
    for text in FIXTURES + examples + _mutations(examples, "", 2000, seed=5):
        assert _calls(current, ("search",), text) == _calls(previous, ("search",), text), text[:200]


@pytest.mark.parametrize(
    ("current", "previous", "flags"),
    [
        # Built from named pieces, or moved to module level: the same pattern text.
        (
            parsers._US_EJECTION_FRACTION,
            r"Фракція викиду\s+(?P<over>Понад\s*)?(?P<v>\d+(?:[.,]\d+)?)\s*%\s*(?P<ref>Понад\s*(?P<low>\d+(?:[.,]\d+)?)\s*%)?",
            0,
        ),
        (parsers._BAND_BREAK, r"[;\n\d<>≤≥]", 0),
        (parsers._COMPARATOR, r"[<>≤≥]", 0),
        (parsers._HYPHEN_BREAK, r"(?<=\w)- (?=\w)", 0),
        (parsers._HBA1C_LABEL, r"Глікований гемоглобін\s*\(HbA1c\)", re.I),
        (parsers._EXPERT_TABLE_END, r"Результати досліджень\b|Лікар\b|Сайт лікарні", 0),
        (parsers._EXPERT_HEADER, r"ПОКАЗНИК\s+РЕЗУЛЬТАТ\s+(?:НОРМА|РЕФЕРЕНТНІ\s+ЗНАЧЕННЯ)", re.I),
        (parsers._BLOOD_GROUP_ROW, r"^(Група крові)\s+([ABАВOОIІVХ]+\s*\([^)]*\))$", re.I),
        (parsers.GARMIN_WEEK_VALUES, r"^(\d{2,3})\s*-\s*(\d{2,3})\s+(\d{2,3})\s*-\s*(\d{2,3})\s+(\d+)$", 0),
    ],
)
def test_hoisted_pattern_is_unchanged(current, previous, flags):
    assert current.pattern == previous
    assert current.flags == re.compile(previous, flags).flags
