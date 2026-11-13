"""The bundled ICD-10 catalogue (``data/icd10.json``): code titles, chapters and blocks.

Built by ``scripts/build_icd10.py`` from the Ukrainian classifier НК 025:2021 (МКХ-10-АМ) and the
WHO ICD-10 2019 titles. Read once, on first use.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import resource_path

_CODE = re.compile(r"[A-Z][0-9]{2}(?:\.[0-9]{1,2})?")
_PREFIX = re.compile(r"[A-Z][0-9]{1,2}(?:\.[0-9]{0,2})?")
_LOOKALIKES = str.maketrans("АВЕІКМНОРСТХ", "ABEIKMHOPCTX")
_TO_CYRILLIC = str.maketrans("aceiopxyABCEHIKMOPTX", "асеіорхуАВСЕНІКМОРТХ")
_CYRILLIC_LETTER = re.compile(r"[Ѐ-ӿ]")


def _fold(raw: str) -> str:
    """Upper case, no spaces, comma as dot, Cyrillic look-alikes as Latin letters."""
    return "".join(raw.split()).upper().replace(",", ".").translate(_LOOKALIKES)


def _in_titles(word: str, titles: str) -> bool:
    """True when the casefolded word occurs in the casefolded titles.  A word with a Cyrillic letter
    is compared with Latin look-alikes read as Cyrillic on both sides, so a stray Latin 'p' in
    'ліpідемії' still finds the title; an English word is compared as typed."""
    if _CYRILLIC_LETTER.search(word):
        return word.translate(_TO_CYRILLIC) in titles.translate(_TO_CYRILLIC)
    return word in titles


def _covers(range_text: str, category: str) -> bool:
    """True when a three-character category falls in a range such as ``U00-U49, U78-U88``."""
    for part in range_text.split(","):
        start, _, end = part.strip().partition("-")
        start = start.strip()
        if start <= category <= (end.strip() or start):
            return True
    return False


@lru_cache(maxsize=1)
def _load() -> dict:
    """The catalogue, with chapter and block looked up for every code."""
    data = json.loads(resource_path("icd10.json").read_text(encoding="utf-8"))
    codes = data["codes"]
    chapter_of: dict[str, dict | None] = {}
    block_of: dict[str, dict | None] = {}
    by_category: dict[str, tuple[dict | None, dict | None]] = {}
    for code in codes:
        category = code[:3]
        if category not in by_category:
            chapter = next((c for c in data["chapters"] if _covers(c["range"], category)), None)
            block = next((b for b in data["blocks"] if _covers(b["range"], category)), None)
            by_category[category] = (chapter, block)
        chapter_of[code], block_of[code] = by_category[category]
    return {"codes": codes, "chapter": chapter_of, "block": block_of}


def normalize(raw: str) -> str:
    """'к11,2 ' -> 'K11.2'.  Upper case, comma to dot, spaces removed, Cyrillic look-alikes
    (А В Е І К М Н О Р С Т Х) to Latin (A B E I K M H O P C T X).  '' unless the result
    fully matches [A-Z][0-9]{2}(\\.[0-9]{1,2})?"""
    text = _fold(raw)
    return text if _CODE.fullmatch(text) else ""


def entry(code: str) -> dict | None:
    """The catalogue row of a code, or None when the normalized code is not in the catalogue."""
    key = normalize(code)
    tables = _load()
    row = tables["codes"].get(key)
    if row is None:
        return None
    uk, en, exact = row
    return {
        "code": key,
        "uk": uk,
        "en": en,
        "en_exact": bool(exact),
        "chapter": tables["chapter"][key],
        "block": tables["block"][key],
        "category": key[:3],
    }


def name(code: str, locale: str) -> str:
    """The title in the locale ('uk' or 'en').  English falls back to the Ukrainian title when
    there is no English one.  '' for an unknown code."""
    row = _load()["codes"].get(normalize(code))
    if row is None:
        return ""
    uk, en, _ = row
    return (en or uk) if locale == "en" else uk


def is_condition(code: str) -> bool:
    """False for external causes (V, W, X, Y), for U codes and for Z00-Z79 (reasons for an
    encounter, immunisation needs).  True for every other catalogue code."""
    key = normalize(code)
    if not key or key not in _load()["codes"]:
        return False
    if key[0] in "UVWXY":
        return False
    return not (key[0] == "Z" and key[1:3] <= "79")


def search(query: str, locale: str, limit: int = 20) -> list[dict]:
    """Entries as {"code", "name"} (name in the locale).  A query that normalizes to a code prefix
    ('e78', 'E78.') lists the codes starting with it, in code order.  Otherwise every word of at
    least 2 characters must occur (casefold) in the Ukrainian or the English title, a word with a
    Cyrillic letter matching with Latin look-alikes read as Cyrillic; three-character
    categories first, then shorter titles first.  Only is_condition codes.  [] for a blank query."""
    codes = _load()["codes"]
    folded = _fold(query)
    if _PREFIX.fullmatch(folded):
        matches = [code for code in sorted(codes) if code.startswith(folded)]
    else:
        words = re.findall(r"\w{2,}", query.casefold())
        if not words:
            return []
        matches = [
            code
            for code, (uk, en, _) in codes.items()
            if all(_in_titles(word, f"{uk} {en}".casefold()) for word in words)
        ]
        matches.sort(key=lambda code: (len(code) != 3, len(name(code, locale)), code))
    results: list[dict] = []
    for code in matches:
        if len(results) >= limit:
            break
        if is_condition(code):
            results.append({"code": code, "name": name(code, locale)})
    return results
