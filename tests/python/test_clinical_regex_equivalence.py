"""Rewritten clinical regexes match exactly what the old ones did.

The Sonar cleanup rewrote patterns in health.py and immunizations.py to remove
super-linear backtracking and to stay inside the regex complexity budget.  A
parser regex that silently stops matching drops a clinical value with no error,
so each old pattern is inlined here as it stood and compared with its
replacement: on every short string over an alphabet of the tokens that matter
(blanks of every kind, the keywords, punctuation), on every line of the test
suite's own fixture text, and on long blank runs.  Every comparison also
asserts it found matches, so none of them can pass by comparing nothing.
"""

import itertools
import re
import time
from pathlib import Path

from anamna import health, immunizations
from anamna.i18n import activate_locale, reset_locale, t

_TESTS = Path(__file__).resolve().parent


def _strings(alphabet: list[str], longest: int):
    for length in range(longest + 1):
        for combo in itertools.product(alphabet, repeat=length):
            yield "".join(combo)


def _matches(pattern: re.Pattern[str], text: str) -> list[tuple]:
    return [(m.span(), m.groups()) for m in pattern.finditer(text)]


def _health_fixture_lines() -> list[str]:
    """Every line of the clinical test fixtures, and each file whole."""
    lines: list[str] = []
    for path in sorted(_TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        lines.extend(text.splitlines())
        lines.append(text)
    return lines


_FIXTURES = _health_fixture_lines()
_LONG_RUNS = [
    " " * 400 + "x",
    "x" + " " * 400 + "y",
    "\n" * 300 + "x",
    " \n" * 200 + "x",
    "\t \n" * 150,
]


# --- health.py --------------------------------------------------------------


def test_slash_spacing_regex_substitutes_identically():
    old = re.compile(r"\s*/\s*")
    alphabet = [" ", "\t", "\n", "\xa0", "/", "мм", "x"]
    changed = 0
    for text in [*_strings(alphabet, 6), *_FIXTURES, *_LONG_RUNS, " " * 300 + "/ x"]:
        expected = old.sub("/", text)
        assert health._SLASH_SPACING_RE.sub("/", text) == expected, repr(text)
        changed += expected != text
    assert changed > 10000, changed


def test_examination_label_regex_finds_identical_spans():
    old = re.compile(r"^\s*огляд\s*[:：]?\s*$", re.I | re.M)
    new = health._CONCLUSION_LABELS[4]
    alphabet = [" ", "\n", "\t", "огляд", "Огляд", ":", "：", "x"]
    found = 0
    for text in [*_strings(alphabet, 6), *_FIXTURES, *_LONG_RUNS, "огляд" + " " * 300 + "x"]:
        expected = _matches(old, text)
        assert _matches(new, text) == expected, repr(text)
        found += bool(expected)
    assert found > 10000, found


def _old_attention(summary):
    """`finding_attention` as it stood, with the single negation pattern."""
    negated = re.compile(
        r"не\s+(?:виявлен|визнача|візуаліз|спостеріга)|\bнемає\b|відсутн|\bбез\s+(?:ознак|видимих)|\bno\s+(?:evidence|sign)|\bnot\s+(?:seen|detected)",
        re.I,
    )
    families: list[str] = []
    for clause in re.split(r"[.;\n]|\s[-–—]\s", summary or ""):
        if not clause.strip() or negated.search(clause):
            continue
        for family, pattern in health._ATTENTION_TERMS:
            # The organ gate (a polyp of the endometrium is not the bowel's)
            # came later and is not part of what is compared here.
            if family == "colorectal_polyp" and health._NOT_BOWEL.search(clause):
                continue
            for match in pattern.finditer(clause):
                if not health._NEGATED_WORD.search(clause[: match.start()]) and family not in families:
                    families.append(family)
    return families


def test_negated_clause_patterns_judge_identically():
    old = re.compile(
        r"не\s+(?:виявлен|визнача|візуаліз|спостеріга)|\bнемає\b|відсутн|\bбез\s+(?:ознак|видимих)|\bno\s+(?:evidence|sign)|\bnot\s+(?:seen|detected)",
        re.I,
    )
    alphabet = [" ", "не", "виявлено", "немає", "відсутні", "без", "ознак", "no", "evidence", "not", "seen", "x"]
    negated = 0
    for text in [*_strings(alphabet, 4), *_FIXTURES]:
        expected = bool(old.search(text))
        assert any(pattern.search(text) for pattern in health._NEGATED_CLAUSES) == expected, repr(text)
        negated += expected
    assert negated > 1000, negated
    for text in [*_FIXTURES, "Ознак кісти Бейкера не виявлено. Стеатоз печінки", "No evidence of polyp; adenoma"]:
        assert health.finding_attention(text) == _old_attention(text), repr(text[:80])


def test_new_item_capital_class_matches_identically():
    old = re.compile(r"[A-ZА-ЯІЇЄҐ](?:[a-zа-яіїєґ'’]|\d)")
    new = re.compile(r"[A-ZА-ЯІЇЄҐ][a-zа-яіїєґ'’\d]")
    alphabet = ["A", "Ж", "Ї", "a", "ж", "ї", "'", "’", "1", "٣", " ", "-"]
    matched = 0
    for text in [*_strings(alphabet, 3), *_FIXTURES]:
        expected = old.match(text)
        got = new.match(text)
        assert (got and got.span()) == (expected and expected.span()), repr(text)
        matched += bool(expected)
    assert matched > 100, matched


_OLD_PHONE = r"(?:тел\.?\s*[:：]?\s*)?\+?\b(?:38)?0\d{9}\b"
_PHONE_ALPHABET = [" ", "\n", "тел", "Тел.", ":", ";", ",", "+", "380501234567", "0501234567", "x"]


def test_phone_regexes_substitute_identically():
    old_phone = re.compile(_OLD_PHONE, re.I)
    old_listed = re.compile(r"[;,]?\s*" + _OLD_PHONE, re.I)
    removed = 0
    for text in [*_strings(_PHONE_ALPHABET, 5), *_FIXTURES, *_LONG_RUNS, " " * 300 + "0501234567"]:
        expected = old_phone.sub("", text)
        assert health._PHONE_RE.sub("", text) == expected, repr(text)
        assert health._LISTED_PHONE_RE.sub("", text) == old_listed.sub("", text), repr(text)
        removed += expected != text
    assert removed > 10000, removed


def test_quantity_column_regex_substitutes_identically():
    old = re.compile(r"\s+\d+\s*$")
    alphabet = [" ", "\t", "\n", "1", "25", "x", "."]
    removed = 0
    for text in [*_strings(alphabet, 6), *_FIXTURES, *_LONG_RUNS, "x" + " " * 300 + "1"]:
        expected = old.sub("", text)
        assert health._QUANTITY_COLUMN_RE.sub("", text) == expected, repr(text)
        removed += expected != text
    assert removed > 10000, removed


def test_blank_revisit_regex_substitutes_identically():
    old = re.compile(r"[;,.]?\s*Повторний\s+візит\s*[:：]?\s*[;.]?\s*$", re.I)
    alphabet = [" ", "\n", "Повторний візит", "повторний\nвізит", ":", ";", ".", ",", "x"]
    removed = 0
    for text in [*_strings(alphabet, 5), *_FIXTURES, *_LONG_RUNS, "x" + " " * 300 + "Повторний візит:" + " " * 300]:
        expected = old.sub("", text)
        assert health._BLANK_REVISIT_RE.sub("", text) == expected, repr(text)
        removed += expected != text
    assert removed > 10000, removed


def test_identity_line_patterns_judge_identically():
    old = re.compile(
        r"прізвище|\bпіб\b|п\.і\.[бп]|\bпацієнт\w*\s*[:：]|\bpatient\s*[:：]|prepared\s+for|дата\s+народження|date\s+of\s+birth",
        re.I,
    )
    alphabet = [" ", "Прізвище", "ПІБ", "п.і.б", "пацієнта", "patient", ":", "prepared for", "дата народження", "x"]
    named = 0
    for text in [*_strings(alphabet, 4), *_FIXTURES]:
        expected = bool(old.search(text))
        assert any(pattern.search(text) for pattern in health._IDENTITY_LINES) == expected, repr(text)
        named += expected
    assert named > 1000, named


def test_clinical_diagnosis_split_is_identical():
    old = re.compile(r"[;.]?\s*клінічний\s+діагноз\s*[:：]\s*", re.I)
    alphabet = [" ", "\n", ";", ".", "клінічний діагноз", "Клінічний\nдіагноз", ":", "x"]
    split = 0
    for text in [*_strings(alphabet, 5), *_FIXTURES, *_LONG_RUNS, "x" + " " * 300 + "клінічний діагноз:"]:
        expected = old.split(text)
        assert health._CLINICAL_DIAGNOSIS_RE.split(text) == expected, repr(text)
        split += len(expected) > 1
    assert split > 1000, split


def _old_single_interval(clean):
    """The four whole-string reference forms `display_reference` used to try inline."""
    between = re.fullmatch(r"(?:від\s*)?(-?\d+(?:[.,]\d+)?)\s*(?:до|[-–—])\s*(-?\d+(?:[.,]\d+)?)", clean, re.I)
    if between:
        return f"{between.group(1).replace(',', '.')}-{between.group(2).replace(',', '.')}"
    upper = re.fullmatch(r"(?:до|<|≤)\s*(-?\d+(?:[.,]\d+)?)", clean, re.I)
    if upper:
        return f"≤ {upper.group(1).replace(',', '.')}"
    lower = re.fullmatch(r"(?:від|>|≥)\s*(-?\d+(?:[.,]\d+)?)", clean, re.I)
    if lower:
        return f"≥ {lower.group(1).replace(',', '.')}"
    newborn = re.fullmatch(
        r"Новонароджені\s+діти\s*\((\d+)\s+день\s+життя\)\s*:\s*(-?\d+(?:[.,]\d+)?)\s*[-–—]\s*(-?\d+(?:[.,]\d+)?)",
        clean,
        re.I,
    )
    if newborn:
        return t(
            "ref.newborns",
            day=newborn.group(1),
            low=newborn.group(2).replace(",", "."),
            high=newborn.group(3).replace(",", "."),
        )
    return None


def test_single_interval_reference_reads_identically():
    alphabet = ["від ", "до", "-", "–", "<", "≥", "1", "2,5", "-3", " ", "x"]
    prefixes = ["", "Новонароджені діти (3 день життя): ", "новонароджені  діти(12 день життя) :", "Новонароджені діти (3 день життя)"]
    cases = [prefix + body for prefix in prefixes for body in _strings(alphabet, 4)]
    cases += _FIXTURES + ["Новонароджені діти (3 день життя): 1,5 - 2,5", "Новонароджені діти (3 день життя):" + " " * 300 + "1-2"]
    for locale in ("en", "uk"):
        token = activate_locale(locale)
        try:
            read = newborns = 0
            for text in cases:
                expected = _old_single_interval(text)
                assert health._single_interval_text(text) == expected, repr(text)
                read += expected is not None
                newborns += expected is not None and text.casefold().startswith("новонароджені")
            assert read > 500 and newborns > 50, (read, newborns)
        finally:
            reset_locale(token)


def test_rewritten_health_regexes_stay_linear_on_long_blank_runs():
    """The point of the rewrite: a 20 000-character blank run is read at once."""
    run = " " * 20000
    started = time.perf_counter()
    health._SLASH_SPACING_RE.sub("/", "x" + run + "y")
    health._QUANTITY_COLUMN_RE.sub("", "x" + run + "y")
    health._LISTED_PHONE_RE.sub("", "x" + run + "y")
    health._BLANK_REVISIT_RE.sub("", "x" + run + "y")
    health._CLINICAL_DIAGNOSIS_RE.split("x" + run + "y")
    health._AREA_SENTENCE_SPLIT_RE.split("x" + run + "y")
    health._AREA_DASH_RE.split("x" + run + "y")
    list(health._CONCLUSION_LABELS[4].finditer("огляд" + run + "y"))
    assert time.perf_counter() - started < 2.0


# --- immunizations.py -------------------------------------------------------


def _immunization_fixture_lines() -> list[str]:
    lines: list[str] = []
    sources = [Path(immunizations.__file__)]
    sources += sorted(_TESTS.glob("test_*immuniz*.py"))
    sources += sorted(_TESTS.glob("test_web_vaccinations*.py"))
    for path in sources:
        text = path.read_text(encoding="utf-8")
        lines.extend(text.splitlines())
        lines.append(text)
    return lines


_OLD_FACILITY_END = re.compile(r"\s+(?:адреса|ФОРМА|МЕДИЧНА)\b|\)")


def test_facility_end_regex_splits_identically():
    alphabet = [" ", "\t", "\n", "адреса", "ФОРМА", "МЕДИЧНА", "МЕДИЧНАя", "x", ")"]
    cases = [*_strings(alphabet, 5), *_immunization_fixture_lines(), "КНП «Х»" + " " * 500 + "адресa", " " * 300 + "x"]
    splits = 0
    for text in cases:
        old = _OLD_FACILITY_END.split(text)
        assert old == immunizations._FACILITY_END_RE.split(text), repr(text)
        splits += len(old) > 1
    assert splits > 1000, splits


_OLD_QUANTITY = re.compile(r"\b(\d{1,2}[.,]\d)\s*(?:мл|ml|[mм][nлaпp]|™n)\b", re.IGNORECASE)


def test_quantity_regex_matches_identically():
    alphabet = ["0.5", "1,0", "мл", "МЛ", "мЛ", "Мл", "ml", "ML", "mn", "мп", "™n", " ", "x", "л"]
    matched = 0
    for text in [*_strings(alphabet, 4), *_immunization_fixture_lines()]:
        old = _matches(_OLD_QUANTITY, text)
        assert old == _matches(immunizations._QUANTITY_RE, text), repr(text)
        matched += bool(old)
    assert matched > 1000, matched


_OLD_NAME_LABEL = r"^\s*[Рр]?[Ееe]?\s*[Вв]акцина[а-яіїєґ]*\s*[:.-]?"


def test_name_label_regex_strips_identically():
    alphabet = [" ", "\n", "Р", "р", "Е", "е", "e", "Вакцина", "вакцина", "ція", ":", "x"]
    cases = [*_strings(alphabet, 5), *_immunization_fixture_lines(), " " * 400 + "x", "Р" + " " * 400 + "Вакцинація: x"]
    stripped = 0
    for text in cases:
        old = re.sub(_OLD_NAME_LABEL, "", text, count=1)
        assert old == immunizations._NAME_LABEL_RE.sub("", text, count=1), repr(text)
        stripped += old != text
    assert stripped > 1000, stripped


_OLD_VISIT_PROTOCOL = re.compile(r"^([1-9])\s+(.+?)\s+Міністерство Охорони\s+([1-9])\s+([1-9])\b", re.M)


def test_visit_protocol_regex_matches_identically():
    """Same spans and the same dose, stage and course groups.

    Group 2, the protocol's name, is never read; it is equal too, except on a
    row whose name is nothing but blanks, where the old pattern captured one
    blank and the new one captures nothing.
    """
    alphabet = ["1", "2", " ", "\t", "\n", "x", "Міністерство Охорони", " 2 3"]
    cases = [
        *_strings(alphabet, 6),
        *_immunization_fixture_lines(),
        "1 Протокол МОЗ Міністерство Охорони 1 3",
        "1\nПротокол\nМіністерство Охорони\n2\n2",
        "1   Міністерство Охорони 2 3",
        "1 \n \nМіністерство Охорони 2 3",
        "1" + " " * 300 + "x",
        "1 " + "x " * 300,
    ]
    matched = blank_names = 0
    for text in cases:
        old = list(_OLD_VISIT_PROTOCOL.finditer(text))
        new = list(immunizations._VISIT_PROTOCOL_RE.finditer(text))
        assert [m.span() for m in old] == [m.span() for m in new], repr(text)
        for a, b in zip(old, new):
            assert (a.group(1), a.group(3), a.group(4)) == (b.group(1), b.group(3), b.group(4)), repr(text)
            assert a.group(2) == b.group(2) or (b.group(2) is None and a.group(2).isspace()), repr(text)
            matched += 1
            blank_names += b.group(2) is None
    # Not vacuous: both branches of the new pattern were exercised.
    assert matched > 100 and blank_names > 10, (matched, blank_names)
