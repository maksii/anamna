from __future__ import annotations

import hashlib
import math
import re
import unicodedata


SPACE_RE = re.compile(r"\s+")


def collapse_space(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


#: A Roman numeral typed partly or wholly in Cyrillic («ІІ», «ІV», «ХІІ»):
#: the lab's record writes «тип ІІ» where the OCR of its print reads «тип II».
#: Two letters at least, so the conjunction «і» stays a word.
_CYRILLIC_ROMAN_RE = re.compile(r"(?<!\w)(?=[ivx]*+[іх])[ivxіх]{2,}+(?!\w)")
_ROMAN_TO_LATIN = str.maketrans("іх", "ix")


def normalized_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    # Every apostrophe look-alike is one: ' ’ ʼ ` and the «"» a lab's record
    # types for it (the punctuation becomes a space below).
    value = value.translate(_APOSTROPHES)
    value = re.sub(r"[^\w%#+/.-]+", " ", value, flags=re.UNICODE)
    value = _CYRILLIC_ROMAN_RE.sub(lambda match: match.group(0).translate(_ROMAN_TO_LATIN), value)
    return collapse_space(value)


_APOSTROPHES = str.maketrans({"’": "'", "`": "'", "ʼ": "'", "ʹ": "'", "‘": "'"})


def text_sha256(value: str) -> str:
    return hashlib.sha256(collapse_space(value).encode("utf-8")).hexdigest()


#: Ukrainian Cyrillic to Latin, per the national transliteration table
#: (Resolution of the Cabinet of Ministers of Ukraine No. 55 of 27.01.2010, the
#: scheme used on Ukrainian passports).  Russian-only letters are appended
#: because a Ukrainian clinic's older reports are sometimes printed in Russian.
#: Position-dependent rules in the official table -- «зг» as "zgh", «є/ї/й/ю/я»
#: spelled differently word-initially -- are deliberately not implemented: this
#: is a search key, where "iе" and "ye" both reaching the same row matters more
#: than which one is orthographically correct.
_TRANSLITERATION = {
    "а": "a", "б": "b", "в": "v", "г": "h", "д": "d", "е": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia",
    "ы": "y", "э": "e", "ъ": "", "ё": "e",
    # The official scheme renders «г» as "h" and reserves "g" for «ґ», but
    # almost nobody writing a Latin abbreviation follows it: «ЕКГ» is typed
    # "EKG", not "EKH".  Both letters collapse to one here so the two spellings
    # reach the same rows.  Safe in a key nobody reads -- it can only merge
    # words that differ by g/h alone -- and it is why «ґ» maps to "h" too.
    "ґ": "h", "g": "h",
}
_TRANSLITERATE = str.maketrans(_TRANSLITERATION)


def search_key(text: str) -> str:
    """The form a search term and the searched text are both reduced to.

    Three spellings of one query returned three different answers: «мрт» found
    nothing, «МРТ» found eight documents, Latin "MRT" found one.  Two separate
    causes, and both make the record unfindable to somebody who knows it is
    there.

    Case: SQLite's `LIKE` folds it for ASCII only -- and `lower()` no better --
    so every Cyrillic term was silently case-sensitive, and whether you found
    your own MRI reports depended on having held shift.  `casefold()` knows
    about Cyrillic.

    Script: the record is bilingual and so is the person searching it, who does
    not always switch keyboard layout to look for a Ukrainian word.  Latin
    "MRT" could never match «МРТ» by folding lookalike glyphs -- Cyrillic «Р»
    is the glyph twin of Latin "P", while the letter it *sounds* like is "R" --
    so this transliterates instead, and both sides of the comparison end up as
    lowercase Latin.
    """
    return text.casefold().translate(_TRANSLITERATE)


def combined_page_text(page: dict[str, object]) -> str:
    """Combine native and OCR evidence for parsing without conflating their storage."""
    return "\n".join(
        value
        for value in (
            str(page.get("native_text") or ""),
            str(page.get("ocr_text") or ""),
        )
        if value.strip()
    )


def parse_decimal(value: str) -> float | None:
    # The typographic minus («−2,3», U+2212) is the sign, not a character float() rejects.
    clean = value.strip().replace(" ", "").replace(",", ".").replace("−", "-")
    clean = clean.rstrip("%")
    clean = re.sub(r"^[<>≤≥=~]+", "", clean)
    try:
        number = float(clean)
        return number if math.isfinite(number) else None
    except ValueError:
        return None
