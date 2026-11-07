"""Rewritten web regexes match exactly what the old ones did.

The Sonar cleanup replaced the printed-decimal and printed-number searches in
web/app.py with a plain run of number characters plus a check in Python, and
dropped redundant groups from the filename-title pattern.  Each old pattern is
inlined here as it stood and compared with its replacement on every short
string over an alphabet of the characters that matter (digits of two scripts,
point, comma, "№", both blanks, a letter), and each comparison asserts it saw
real matches so none can pass by comparing nothing.
"""

import itertools
import re

import pytest

from anamna.web import app

_OLD_PRINTED_DECIMAL = re.compile(r"(?<![\d.,№])(\d++)\.(\d++)(?![\d.])")
_OLD_PRINTED_NUMBER = re.compile("(?<![\\d  ,.])[  ,.]*\\d(?:[  ,.]*\\d)*")
_OLD_FILENAME_TITLE = re.compile(r"(?:^\d{4}-\d{2}-\d{2}__)|_{2}|(?:\.(pdf|png|jpe?g|tiff?)$)", re.I)


def _strings(alphabet: str, longest: int):
    for length in range(longest + 1):
        for combo in itertools.product(alphabet, repeat=length):
            yield "".join(combo)


def _fake_format(value: float, places: int) -> str:
    return f"<{value!r}|{places}>"


def test_printed_decimal_rewrite_matches_old_pattern(monkeypatch):
    monkeypatch.setattr(app, "format_number_localized", _fake_format)
    changed = 0
    for text in _strings("12.,№ a٣", 6):
        old = _OLD_PRINTED_DECIMAL.sub(
            lambda match: _fake_format(float(match.group(0)), len(match.group(2))), text
        )
        new = app._NUMERIC_RUN.sub(app._localize_printed_decimal, text)
        assert new == old, text
        changed += new != text
    assert changed > 1000


def test_printed_number_rewrite_matches_old_pattern():
    found = 0
    for text in _strings("12.,  a٣", 6):
        old = _OLD_PRINTED_NUMBER.search(text)
        assert app._first_printed_number(text) == (old.group(0) if old else ""), text
        found += old is not None
    assert found > 1000


@pytest.mark.parametrize(
    "title",
    ["2024-01-02__scan", "a__b", "report.PDF", "x.jpeg", "x.tif", "x.tiff", "plain title",
     "2024-01-02_scan", "pdf", "x.pdf.txt", "_a_", "2024-1-02__", "photo.png "],
)
def test_filename_title_rewrite_matches_old_pattern(title):
    assert app._looks_like_filename(title) == bool(_OLD_FILENAME_TITLE.search(title))
