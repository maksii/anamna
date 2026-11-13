"""Build ``data/icd10.json``, the bundled ICD-10 catalogue with Ukrainian and English titles.

Inputs, downloaded into ``work/icd10-src/`` (gitignored, never committed):

* ``--uk-leaf`` ``diagnosis.csv``: one line per leaf code, ``CODE|title|system``. A dump of the
  eHealth dictionary ``eHealth/ICD10_AM/condition_codes``, the national classifier НК 025:2021.
  Taken from https://github.com/olekoval/c16-/tree/main/data because
  https://api.ehealth.gov.ua/api/dictionaries?name=eHealth/ICD10_AM/condition_codes refuses
  ordinary clients.
* ``--uk-tree`` ``mkx10.xlsx``: the same classifier as a hierarchy (chapter, block, category, and
  the four- and five-character codes). Read with the standard library only.
* ``--en`` ``who_pairs.txt``: ``CODE<TAB>English title`` for WHO ICD-10 2019, from
  https://github.com/StefanoTrv/simple_icd_10 (``data/code-description pairs.txt``); the source
  is https://icd.who.int/browse10/2019/en.

The Ukrainian files carry no English. Each code takes the WHO title of the same code (``en_exact``
1), else the title in ``AM_ONLY_TITLES`` (also ``en_exact`` 1), else the title of its nearest
ancestor (``E11.21`` -> ``E11.2`` -> ``E11``, ``en_exact`` 0), else an empty English title.

Ukrainian titles in the inputs sometimes spell a word with Latin look-alike letters (``лiпiдемiї``);
``repair_uk`` turns those back into Cyrillic before the catalogue is written.

Run::

    uv run python scripts/build_icd10.py --uk-leaf work/icd10-src/diagnosis.csv \
        --uk-tree work/icd10-src/mkx10.xlsx --en work/icd10-src/who_pairs.txt --out data/icd10.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

SOURCES = [
    {
        "id": "moz-nk-025-2021",
        "region": "UA",
        "publisher": "Міністерство охорони здоров'я України / Національна служба здоров'я України",
        "name": "НК 025:2021 Класифікатор хвороб та споріднених проблем охорони здоров'я (МКХ-10-АМ), словник ЕСОЗ eHealth/ICD10_AM/condition_codes",
        "url": "https://docs.ehealth.gov.ua/general-mis/tag/public-medical-service-provider-integration-layer/GET/api/dictionaries",
        "identifier": "НК 025:2021",
    },
    {
        "id": "who-icd10-2019",
        "region": "INT",
        "publisher": "World Health Organization",
        "name": "International Statistical Classification of Diseases and Related Health Problems, 10th Revision (ICD-10), version 2019",
        "url": "https://icd.who.int/browse10/2019/en",
        "identifier": "ICD-10 2019",
    },
]

#: Cyrillic capitals that look like Latin ones (А В Е І К М Н О Р С Т Х), as Latin.
LOOKALIKES = str.maketrans(
    dict(zip("АВЕІКМНОРСТХ", "ABEIKMHOPCTX"))
)
#: Latin letters that look like Cyrillic ones, as Cyrillic. Used only inside a Ukrainian word that
#: already holds a Cyrillic letter, so ``Escherichia`` and ``IgE`` keep their Latin spelling.
LATIN_TO_CYRILLIC = str.maketrans("aceiopxyABCEHIKMOPTX", "асеіорхуАВСЕНІКМОРТХ")
#: A word for the repair: a maximal run of letters (digits, apostrophes and hyphens split words).
WORD = re.compile(r"[^\W\d_]+")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATIN = re.compile(r"[A-Za-z]")
#: ICD-10-AM category titles absent from WHO ICD-10 (the Australian modification Ukraine uses).
#: WHO's title wins wherever WHO has one; these only fill the gap, and they feed the ancestor fallback.
AM_ONLY_TITLES = {
    "B59": "Pneumocystosis",
    "E09": "Intermediate hyperglycaemia",
    "O09": "Duration of pregnancy",
    "T89": "Other specified complications of trauma",
}
#: Typing errors of the Ukrainian source dump, wrong -> right, each checked against the dump's own
#: wording: chapter IV is spelled Ендокринні in the dump's O99.2 line; G70.0 writes "gravis" in Latin
#: (WHO: "Myasthenia gravis"); WHO's E75.0 is "GM 2 gangliosidosis". Applied to whole words only, after
#: ``repair_uk``. The keys holding a Cyrillic look-alike (І, М) are escapes, so the homoglyph shows in the source.
UK_CORRECTIONS: dict[str, str] = {
    "Ендокрині хвороби": "Ендокринні хвороби",  # chapter IV: one н where the word has two
    "Міастеніяgrаvіs": "Міастенія gravis",  # G70: Latin gr, Cyrillic а, Latin v, Cyrillic і, Latin s
    "ІV": "IV",  # L89.3 stage IV: Cyrillic І, Latin V
    "GМ2": "GM2",  # E75.0: Cyrillic М in GM2
}
ROMAN = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
    (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]
CHAPTER_CELL = re.compile(r"Клас\s+([0-9]+)\s*,\s*(.+)")
BRACKETS = re.compile(r"\(([^()]*)\)\s*$")


def roman(number: int) -> str:
    """Upper-case roman numeral for a positive integer."""
    out = []
    for value, symbol in ROMAN:
        while number >= value:
            out.append(symbol)
            number -= value
    return "".join(out)


def clean(text: str) -> str:
    """Strip the ends and collapse every run of whitespace to one space."""
    return " ".join(text.split())


def sentence(text: str) -> str:
    """First letter upper case, the rest lower case (the source is all capitals)."""
    return text[:1].upper() + text[1:].lower()


def canonical_range(text: str) -> str:
    """A code range in Latin letters with plain hyphens, as WHO writes it.

    The source mixes Cyrillic look-alikes into codes ('Н00-Н59'), en dashes with spaces
    ('U78 – U88') and single codes ('B99'). Result: 'H00-H59', 'U78-U88', 'B99-B99'.
    """
    parts = []
    for part in clean(text).translate(LOOKALIKES).replace("–", "-").split(","):
        start, _, end = part.partition("-")
        start = start.strip()
        parts.append(f"{start}-{end.strip() or start}")
    return ", ".join(parts)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def repair_uk(title: str) -> str:
    """Latin look-alikes back to Cyrillic, but only in words that already hold a Cyrillic letter.

    'лiпiдемiї' -> 'ліпідемії'; 'Escherichia', 'IgE', 'E78' and digits-only words stay as they are.
    """

    def fix(match: re.Match) -> str:
        word = match.group()
        if CYRILLIC.search(word) and LATIN.search(word):
            return word.translate(LATIN_TO_CYRILLIC)
        return word

    return WORD.sub(fix, title)


def correct_uk(title: str) -> str:
    """Each ``UK_CORRECTIONS`` pair, matched and replaced as a whole word only."""
    for wrong, right in UK_CORRECTIONS.items():
        title = re.sub(rf"(?<![^\W\d_]){re.escape(wrong)}(?![^\W\d_])", lambda _match, right=right: right, title)
    return title


def map_titles(catalogue: dict, convert: Callable[[str], str]) -> int:
    """Apply ``convert`` to every Ukrainian title (chapters, blocks, codes) in place; return how many changed."""
    changed = 0
    for row in [*catalogue["chapters"], *catalogue["blocks"]]:
        fixed = convert(row["uk"])
        changed += fixed != row["uk"]
        row["uk"] = fixed
    for value in catalogue["codes"].values():
        fixed = convert(value[0])
        changed += fixed != value[0]
        value[0] = fixed
    return changed


def mixed_script_words(catalogue: dict) -> Counter:
    """Words that still hold both Cyrillic and Latin letters after the repair, with their counts."""
    titles = [row["uk"] for row in [*catalogue["chapters"], *catalogue["blocks"]]]
    titles += [value[0] for value in catalogue["codes"].values()]
    found: Counter = Counter()
    for title in titles:
        for match in WORD.finditer(title):
            word = match.group()
            if CYRILLIC.search(word) and LATIN.search(word):
                found[word] += 1
    return found


def read_leaf_csv(path: Path) -> dict[str, str]:
    """Titles by code from ``CODE|title|system``, split at the first and the last ``|``."""
    titles: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        first, last = line.find("|"), line.rfind("|")
        if first < 0 or last == first:
            warn(f"{path.name} line {number}: fewer than two '|' separators, skipped")
            continue
        code, title = clean(line[:first]), clean(line[first + 1 : last])
        if not code or not title:
            warn(f"{path.name} line {number}: empty code or title, skipped")
            continue
        if titles.get(code, title) != title:
            warn(f"{path.name} line {number}: code {code} repeated with another title")
        titles[code] = title
    return titles


def read_who(path: Path) -> dict[str, str]:
    """WHO titles by code, roman chapter numeral or block range from ``CODE<TAB>title``."""
    titles: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, title = line.partition("\t")
        key, title = key.strip(), clean(title)
        if separator and key and title:
            titles.setdefault(key, title)
    return titles


def read_workbook_rows(path: Path) -> list[dict[str, str]]:
    """Data rows of sheet 1 as ``{column letter: text}``; row 1 (the header) is dropped."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{NS}t")) for si in root.iter(f"{NS}si")]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[dict[str, str]] = []
    for row in sheet.iter(f"{NS}row"):
        cells: dict[str, str] = {}
        for cell in row.iter(f"{NS}c"):
            match = re.match(r"[A-Z]+", cell.get("r", ""))
            if match is None:
                continue
            kind = cell.get("t")
            if kind == "s":
                cells[match.group()] = shared[int(cell.findtext(f"{NS}v", "0"))]
            elif kind == "inlineStr":
                cells[match.group()] = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
            else:
                cells[match.group()] = cell.findtext(f"{NS}v", "")
        rows.append(cells)
    return [row for row in rows[1:] if any(row.values())]


def split_code(cell: str) -> tuple[str, str] | None:
    """``CODE, title`` to ``(code, title)``; the title is '' when the cell has none.

    None for an empty cell or the ``-`` placeholder.
    """
    text = clean(cell)
    if text in ("", "-"):
        return None
    code, _, title = text.partition(",")
    return code.strip(), title.strip()


def english_title(code: str, who: dict[str, str]) -> tuple[str, int]:
    """WHO title of the code (exact 1), else of its nearest ancestor (0), else ('', 0)."""
    if code in who:
        return who[code], 1
    current = code
    while current:
        current = current[:-1].rstrip(".")
        if current in who:
            return who[current], 0
    return "", 0


def build(uk_leaf: Path, uk_tree: Path, en: Path, version: str) -> dict:
    """Assemble the catalogue dictionary described in ``work/diagnoses-spec.md``."""
    who = {**AM_ONLY_TITLES, **read_who(en)}
    rows = read_workbook_rows(uk_tree)

    chapters: dict[tuple[str, str], dict] = {}
    blocks: dict[str, dict] = {}
    spreadsheet_titles: dict[str, str] = {}
    untitled: set[str] = set()
    for row in rows:
        chapter_text = clean(row.get("A", ""))
        if chapter_text:
            match = CHAPTER_CELL.fullmatch(chapter_text)
            if match is None:
                raise SystemExit(f"unrecognised chapter cell: {chapter_text!r}")
            number = roman(int(match.group(1)))
            body = match.group(2)
            bracket = BRACKETS.search(body)
            chapter_range = canonical_range(bracket.group(1)) if bracket else ""
            title = body[: bracket.start()] if bracket else body
            if not chapter_range:
                warn(f"chapter {number} has no range in brackets")
            chapters.setdefault(
                (number, chapter_range),
                {"number": number, "range": chapter_range, "uk": sentence(clean(title)), "en": who.get(number, "")},
            )
        block_text = clean(row.get("B", ""))
        if block_text:
            raw_range, separator, block_title = block_text.partition(", ")
            block_range = canonical_range(raw_range)
            if not separator:
                warn(f"block cell without 'RANGE, title': {block_text!r}")
            else:
                blocks.setdefault(
                    block_range,
                    {"range": block_range, "uk": clean(block_title), "en": who.get(block_range, "")},
                )
        for column in ("C", "D", "E"):
            pair = split_code(row.get(column, ""))
            if pair is None:
                continue
            code, title = pair
            if title:
                spreadsheet_titles.setdefault(code, title)
            else:
                untitled.add(code)

    leaf_titles = read_leaf_csv(uk_leaf)
    uk_titles = {**spreadsheet_titles, **leaf_titles}
    left_out = sorted(untitled - uk_titles.keys())
    if left_out:
        warn(f"{len(left_out)} codes have no Ukrainian title in either source and are left out: {', '.join(left_out)}")

    codes: dict[str, list] = {}
    for code in sorted(uk_titles):
        english, exact = english_title(code, who)
        codes[code] = [uk_titles[code], english, exact]

    return {
        "version": version,
        "sources": SOURCES,
        "chapters": list(chapters.values()),
        "blocks": list(blocks.values()),
        "codes": codes,
    }


def report(catalogue: dict, repaired: int, corrected: int) -> None:
    """Print the counts, the English gaps and the mixed-script guard of the built catalogue."""
    codes = catalogue["codes"]
    exact = sum(1 for _, _, flag in codes.values() if flag == 1)
    ancestor = sum(1 for _, english, flag in codes.values() if flag == 0 and english)
    missing = [code for code, (_, english, _) in codes.items() if not english]
    categories = [code for code in missing if len(code) == 3]
    print(f"chapters: {len(catalogue['chapters'])}")
    print(f"blocks: {len(catalogue['blocks'])}")
    print(f"codes: {len(codes)}")
    print(f"Ukrainian titles repaired (Latin letters inside Cyrillic words): {repaired}")
    print(f"Ukrainian titles changed by UK_CORRECTIONS (typing errors of the source): {corrected}")
    print(f"codes with en_exact 1: {exact}")
    print(f"codes with an ancestor English title (en_exact 0): {ancestor}")
    print(f"codes with no English title: {len(missing)}")
    print(f"three-character categories with no English title ({len(categories)}): {', '.join(categories)}")
    mixed = mixed_script_words(catalogue)
    print(f"words still mixing Cyrillic and Latin letters: {sum(mixed.values())} occurrences, {len(mixed)} distinct")
    print("  first 15 by frequency: " + ", ".join(word for word, _ in mixed.most_common(15)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build data/icd10.json from the ICD-10 source files.")
    parser.add_argument("--uk-leaf", type=Path, required=True, help="diagnosis.csv (CODE|title|system)")
    parser.add_argument("--uk-tree", type=Path, required=True, help="mkx10.xlsx (chapter, block, codes)")
    parser.add_argument("--en", type=Path, required=True, help="who_pairs.txt (CODE<TAB>English title)")
    parser.add_argument("--out", type=Path, default=Path("data/icd10.json"), help="output JSON file")
    parser.add_argument("--version", default="2026-11-13", help="ISO date stamped into the catalogue")
    args = parser.parse_args(argv)

    catalogue = build(args.uk_leaf, args.uk_tree, args.en, args.version)
    repaired = map_titles(catalogue, repair_uk)
    corrected = map_titles(catalogue, correct_uk)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n"
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    report(catalogue, repaired, corrected)
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
