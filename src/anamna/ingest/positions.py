"""Where on its page each observation was printed.

The review page lists extracted values beside the page they came from, and a
list that does not follow the page is one the reviewer cannot check: the
values used to arrive alphabetically within a page, so the first row printed
on an EskuLab report was the last card under it.  This finds each value's row
on the page once and stores it in ``observations.evidence_bbox_json``:

* ``{"v": 1, "box": [x0, y0, x1, y1]}`` -- fractions of the page width and
  height, read from the PDF's own text layer.  Exact enough to draw on.
* ``{"v": 1, "y": 0.42}`` -- the line's place in the stored page text (OCR,
  photographs, rotated pages).  Good for ordering; never drawn.
* ``{"v": 1}`` -- looked for and not found, so nobody looks again.

Bump ``LOCATOR_VERSION`` to have every document re-located the next time it
is opened.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

LOCATOR_VERSION = 1

# Cyrillic letters that print identically to Latin ones.  Synevo's «(МСН)» is
# Cyrillic and the parser's alias may be Latin, or the other way round; folding
# both sides to one alphabet makes them the same string.
_HOMOGLYPHS = str.maketrans("аеорсхуікмнтв", "aeopcxyikmhtb")
_NOT_ALNUM = re.compile(r"[\W_]+")


def fold(text: str | None) -> str:
    """Letters and digits only, case- and alphabet-insensitive."""
    return _NOT_ALNUM.sub("", str(text or "").casefold().translate(_HOMOGLYPHS))


def _reading_order(words: list[dict]) -> list[dict]:
    """Words in lines, top to bottom, each line left to right.

    Sorting by `top` alone puts a word whose baseline sits a fraction of a
    point higher ahead of the word printed before it on the same line.
    """
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda item: item["top"]):
        if lines and word["top"] - lines[-1][0]["top"] <= 2.5:
            lines[-1].append(word)
        else:
            lines.append([word])
    ordered = []
    for number, line in enumerate(lines):
        for word in sorted(line, key=lambda item: item["x0"]):
            ordered.append({**word, "line": number, "key": fold(word["text"])})
    return ordered


def _continuation(words: list[dict], at: int, index: int, column: float) -> int | None:
    """The word after word `at` in a name: word `index` on the same line, else
    the first word in the name's column just under it, else None."""
    last = words[at]
    if index < len(words) and words[index]["line"] == last["line"]:
        return index
    # The name goes on under itself, or not at all.
    height = max(1.0, last["bottom"] - last["top"])
    return next(
        (
            below for below in range(at + 1, len(words))
            if words[below]["key"] and words[below]["x0"] >= column
            and last["top"] + 0.5 * height < words[below]["top"] <= last["top"] + 1.9 * height
        ),
        None,
    )


def _match_at(words: list[dict], start: int, key: str) -> list[int] | None:
    """The words that print all of `key` starting at word `start`, if any.

    Consecutive on one line, or -- once the line stops spelling the name --
    continued by the first word in the name's column just under it.  That is
    how a wrapped label prints: EskuLab puts «Аспартатамінотрансфераза 27.8
    Од/л ...» on one line and «(АСТ)» under the name, and a value centred in a
    two-line cell sits between the halves.  Only that one word, and only
    within one line's height, so that Synevo's «...еритроцитів 36.6 фл» /
    «(RDW-SD)», printed directly above the same first line ending «(RDW-CV)»,
    is not read as the RDW-CV row.
    """
    first = words[start]["key"]
    if not first or not key.startswith(first):
        return None
    position, used, index = len(first), [start], start + 1
    column = words[start]["x0"] - 3
    while position < len(key):
        last = words[used[-1]]
        index = _continuation(words, used[-1], index, column)
        if index is None:
            return None
        word = words[index]
        piece, rest = word["key"], key[position:]
        if not piece:
            index += 1
            continue
        if rest.startswith(piece):
            position += len(piece)
        elif piece.startswith(rest):
            position = len(key)
        elif word["line"] == last["line"]:
            # The rest of this line is the value and its reference.
            index = len(words)
            continue
        else:
            return None
        used.append(index)
        index += 1
    return used


def _printed_above(words: list[dict], key: str, at: int, span: float) -> bool:
    """Whether a word spelling `key` starts at most `span` points above word
    `at`, or on its line."""
    top = words[at]["top"]
    return any(
        word["key"] == key and top - span <= word["top"] <= top + 1
        for word in words[: at + 1]
    )


#: A trailing «(кал)».  The spaces before it are left for `.split()` to drop.
_QUALIFIER = re.compile(r"\([^()]*\)\s*$")


def _box(words: list[dict], used: list[int], width: float, height: float, origin: tuple[float, float]) -> list[float]:
    """The printed row: the name's words plus the rest of its first line.

    Only to the right of where the name starts, so that in a two-column
    layout the left column's row does not swallow the right one's start.
    """
    first_line, start_x = words[used[0]]["line"], words[used[0]]["x0"]
    row = [words[index] for index in used] + [
        word for word in words if word["line"] == first_line and word["x0"] >= start_x - 1
    ]
    left, top = origin
    x0 = min(word["x0"] for word in row) - left
    x1 = max(word["x1"] for word in row) - left
    y0 = min(word["top"] for word in row) - top
    y1 = max(word["bottom"] for word in row) - top
    return [
        round(max(0.0, min(1.0, value)), 4)
        for value in (x0 / width, y0 / height, x1 / width, y1 / height)
    ]


def _text_lines(text: str) -> list[str]:
    return [fold(line) for line in str(text or "").splitlines() if line.strip()]


def _line_fraction(lines: list[str], key: str, ordinal: int) -> float | None:
    """The `ordinal`-th line carrying `key`, as a fraction down the page."""
    if not lines or len(key) < 3:
        return None
    hits = [
        index for index, line in enumerate(lines)
        if line and (key in line or (len(line) >= 6 and key.startswith(line)))
    ]
    if not hits:
        return None
    index = hits[min(ordinal, len(hits) - 1)]
    return round((index + 0.5) / len(lines), 4)


def locate_page(rows: list[dict], words: list[dict] | None, size: tuple[float, float, float, float] | None, text: str) -> list[dict]:
    """A position for each row of one page, in the order given.

    `rows` carry ``raw_name`` and ``evidence_text`` in insertion order;
    `words` are pdfplumber word dicts (``x0 x1 top bottom text``) or None when
    the page has no usable text layer; `size` is the page's bbox.  The n-th
    row with a given label takes the n-th place that label is printed, so a
    page that prints «Колір» for urine and again for stool keeps both apart.
    """
    ordered = _reading_order(words) if words and size else []
    lines = _text_lines(text)
    names = [fold(row.get("raw_name")) for row in rows]
    # The parser qualifies some labels with the specimen («Колір (кал)») that
    # the page prints only once, in the section heading.
    bare_words = [_QUALIFIER.sub("", str(row.get("raw_name") or "")).split() for row in rows]
    bare = [fold(" ".join(words)) for words in bare_words]
    # A grouped row prints its group once and each member under it: EskuLab's
    # stool table has «Крохмаль» in the first column and «позаклітинний» in
    # the next, which the parser joins into one label.  The member alone is
    # what can be found, the shortest tail that still says something.
    # Only where the group's own first word is printed a little above it, so
    # «загальний» from an unprinted «Білірубін загальний» does not land on
    # «Білок загальний».
    tails = [
        [
            (key, fold(words[0]))
            for key in (fold(" ".join(words[cut:])) for cut in range(1, len(words)))
            if len(key) >= 5
        ]
        for words in bare_words
    ]
    evidence = [fold(row.get("evidence_text")) for row in rows]
    # Every complete printing of each label, longest first, and a word that
    # starts one label cannot start another: «Білірубін загальний» claims its
    # row before a bare «Білірубін» can.
    label_keys = set(names) | set(bare) | {key for keys in tails for key, _ in keys}
    printed = _printings(ordered, label_keys, evidence)
    # How far above its member a group label may sit: an eighth of the page.
    group_reach = (size[3] - size[1]) * 0.12 if size else 0.0
    taken: set[int] = set()
    shared: dict[tuple[str, str], int] = {}
    counted: dict[object, int] = {}
    positions = []
    for row, name, stripped, endings, line in zip(rows, names, bare, tails, evidence, strict=True):
        candidates = [(name, None), (stripped, None)] + list(endings)
        used = _label_printing(candidates, printed, ordered, _printed_value(row), taken, group_reach)
        if used is None:
            used = _line_printing(printed, line, name, shared)
        if used is not None:
            left, top, right, bottom = size
            positions.append({
                "v": LOCATOR_VERSION,
                "box": _box(ordered, used, right - left, bottom - top, (left, top)),
            })
            continue
        positions.append(_text_position(lines, counted, name, stripped, line))
    return positions


def _printings(ordered: list[dict], label_keys: set[str], evidence: list[str]) -> dict[str, list[list[int]]]:
    printed: dict[str, list[list[int]]] = {}
    claimed: set[int] = set()
    for key in sorted({k for k in label_keys | set(evidence) if len(k) >= 2}, key=len, reverse=True):
        found = [
            used for start in range(len(ordered))
            if start not in claimed and (used := _match_at(ordered, start, key))
        ]
        printed[key] = found
        if key in label_keys:
            claimed.update(used[0] for used in found)
    return printed


def _label_printing(
    candidates: list[tuple[str, str | None]],
    printed: dict[str, list[list[int]]],
    ordered: list[dict],
    value: str | None,
    taken: set[int],
    group_reach: float,
) -> list[int] | None:
    for key, head in candidates:
        # The first printing of the label nobody has taken, preferring one
        # whose row carries this row's value: a hospital form lists the
        # tests it ran in its header, «Глюкоза, Ліпаза», above the rows
        # that report them, and the n-th row with a label («Колір» for
        # urine, then for stool) takes the n-th printing.
        matches = [
            found for found in printed.get(key) or []
            if found[0] not in taken and (not head or _printed_above(ordered, head, found[0], group_reach))
        ]
        carrying = [found for found in matches if value and _row_carries(ordered, found, value)]
        if carrying or matches:
            used = (carrying or matches)[0]
            taken.add(used[0])
            return used
    return None


def _line_printing(
    printed: dict[str, list[list[int]]], line: str, name: str, shared: dict[tuple[str, str], int]
) -> list[int] | None:
    if not printed.get(line):
        return None
    # A label the parser named itself (Garmin's "Systolic blood
    # pressure") is not on the page; the line it was read from is, and
    # one printed line yields several values, so they share it.
    matches = printed[line]
    ordinal = shared.get((line, name), 0)
    shared[(line, name)] = ordinal + 1
    return matches[min(ordinal, len(matches) - 1)]


def _text_position(lines: list[str], counted: dict[object, int], name: str, stripped: str, line: str) -> dict:
    """A place by the stored page text alone, when the text layer has none."""
    ordinal = counted.get(name, 0)
    counted[name] = ordinal + 1
    y = _line_fraction(lines, name, ordinal)
    if y is None:
        y = _line_fraction(lines, stripped, ordinal)
    if y is None:
        ordinal = counted.get((name, line), 0)
        counted[(name, line)] = ordinal + 1
        y = _line_fraction(lines, line[:40], ordinal)
    return {"v": LOCATOR_VERSION, "y": y} if y is not None else {"v": LOCATOR_VERSION}


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _printed_value(row: dict) -> str | None:
    """The first number printed after the label on the evidence line."""
    evidence, name = str(row.get("evidence_text") or ""), str(row.get("raw_name") or "")
    rest = evidence[len(name):] if evidence.startswith(name) else evidence
    found = _NUMBER.search(rest)
    return found.group(0) if found else None


def _row_carries(words: list[dict], used: list[int], value: str) -> bool:
    """Whether `value` is printed as a number of its own on this printing's row.

    As a whole number: «1,0» is not the start of the «10*9/л» printed on the
    line that merely mentions eosinophils.
    """
    first, last = words[used[0]], words[used[-1]]
    height = max(1.0, first["bottom"] - first["top"])
    low, high = first["top"] - 0.6 * height, last["top"] + 1.2 * height
    number = re.compile(rf"^[<>≤≥]?{re.escape(value)}(?![\d.,])")
    return any(
        number.match(word["text"]) and low <= word["top"] <= high and word["x0"] >= first["x0"]
        for word in words
    )


def position_key(stored: str | None) -> tuple[float, float]:
    """(y, x) to sort by; rows nobody could place go after those placed.

    y is quantised to half a percent of the page (about four points), so two
    values printed on one line tie on y and are ordered left to right rather
    than by a fraction of a point of baseline jitter.
    """
    data = _stored(stored)
    box = page_box(stored)
    if box:
        return round(box[1] / 0.005), box[0]
    if isinstance(data.get("y"), (int, float)):
        return round(float(data["y"]) / 0.005), 0.0
    return 1_000, 0.0


def page_box(stored: str | None) -> list[float] | None:
    """The exact box, when there is one -- the only kind worth drawing."""
    box = _stored(stored).get("box")
    if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
        return [float(value) for value in box]
    return None


def _stored(stored: str | None) -> dict:
    try:
        data = json.loads(stored) if stored else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _pdf_words(source: Path, page_numbers: set[int]) -> dict[int, tuple[list[dict], tuple]]:
    import pdfplumber

    found: dict[int, tuple[list[dict], tuple]] = {}
    with pdfplumber.open(source) as pdf:
        for number in sorted(page_numbers):
            if not 1 <= number <= len(pdf.pages):
                continue
            page = pdf.pages[number - 1]
            # A rotated page's text coordinates are not the rendered image's,
            # and a box drawn in the wrong place is worse than none.
            if int(getattr(page, "rotation", 0) or 0) % 360:
                continue
            words = page.extract_words(x_tolerance=2, y_tolerance=2)
            if words:
                found[number] = (words, tuple(float(value) for value in page.bbox))
    return found


def needs_positions(connection: sqlite3.Connection, document_id: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM observations WHERE document_id=?
           AND (evidence_bbox_json IS NULL
                OR json_valid(evidence_bbox_json)=0
                OR json_extract(evidence_bbox_json, '$.v') IS NOT ?)
           LIMIT 1""",
        (document_id, LOCATOR_VERSION),
    ).fetchone() is not None


def _source_words(source: Path | None, numbers: set[int], document_id: str) -> dict[int, tuple[list[dict], tuple]]:
    if source is not None and source.suffix.casefold() == ".pdf" and source.is_file():
        try:
            return _pdf_words(source, numbers)
        except Exception:  # a damaged file still gets text-order positions
            logger.warning("positions: could not read words from %s", document_id, exc_info=True)
    return {}


def _page_updates(on_page: list[dict], page, page_words: list[dict] | None, size: tuple | None) -> list[tuple[str, str]]:
    updates = []
    # The text layer describes native-text rows only; a value read by OCR
    # from an embedded image is placed by the OCR text it came from.
    native = [row for row in on_page if "ocr" not in str(row["extraction_method"] or "")]
    other = [row for row in on_page if row not in native]
    for group, text, group_words in (
        (native, page["native_text"] if page else "", page_words),
        (other, (page["ocr_text"] or page["native_text"]) if page else "", None),
    ):
        if not group:
            continue
        for row, position in zip(group, locate_page(group, group_words, size, text or ""), strict=True):
            updates.append((json.dumps(position, separators=(",", ":")), row["id"]))
    return updates


def store_positions(connection: sqlite3.Connection, document_id: str, source: Path | None) -> int:
    """Locate every observation of one document and store the result.

    Every row is recomputed, not only the missing ones, because the n-th
    printing of a label goes to the n-th row with that label and a row added
    by hand changes the count.  One pdfplumber pass over the pages involved.
    Returns the number of rows written.
    """
    rows = [dict(row) for row in connection.execute(
        """SELECT id, page_number, raw_name, evidence_text, extraction_method
           FROM observations WHERE document_id=? ORDER BY page_number, rowid""",
        (document_id,),
    )]
    if not rows:
        return 0
    pages = {
        int(row["page_number"]): row
        for row in connection.execute(
            "SELECT page_number, native_text, ocr_text FROM document_pages WHERE document_id=?",
            (document_id,),
        )
    }
    numbers = {int(row["page_number"] or 0) for row in rows}
    words = _source_words(source, numbers, document_id)
    updates = []
    for number in sorted(numbers):
        on_page = [row for row in rows if int(row["page_number"] or 0) == number]
        page_words, size = words.get(number, (None, None))
        updates.extend(_page_updates(on_page, pages.get(number), page_words, size))
    connection.executemany("UPDATE observations SET evidence_bbox_json=? WHERE id=?", updates)
    return len(updates)


def backfill_positions(connection: sqlite3.Connection, document_id: str, source: Path | None) -> None:
    """Place a document's values the first time it is opened after this existed.

    Documents imported before positions were stored have none, and nobody
    should have to re-read a file to get them.  Done once per document --
    `needs_positions` is false afterwards -- and committed at once, so the
    write lock is not held while the rest of the page renders.  Never fails
    the page: a lock held by a long import, or a file that will not open,
    leaves the rows unplaced and the list in its fallback order for now.
    """
    try:
        if not needs_positions(connection, document_id):
            return
    except sqlite3.Error:
        return
    connection.execute("PRAGMA busy_timeout = 250")
    try:
        store_positions(connection, document_id, source)
        connection.commit()
    except Exception:
        connection.rollback()
        logger.warning("positions: backfill of %s skipped", document_id, exc_info=True)
    finally:
        connection.execute("PRAGMA busy_timeout = 5000")
