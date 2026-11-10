"""Documents that fit a medicine entry: the search behind the document box on the form."""

from __future__ import annotations

import os
import re
import sqlite3

from anamna import health
from anamna.ingest.text import search_key

LIMIT = 8
SNIPPET_CHARS = 160

_DOSAGE_FORMS = (
    "таблет", "капсул", "крапл", "розчин", "сироп", "суспенз", "мазь", "крем", "гель", "спрей", "порошок",
    "tablet", "capsule", "drops", "solution",
)
_DOCTOR_LABEL = re.compile(
    r"^\s*(?:лікар(?:[-\s][^\s:_]+){0,2}|doctor|physician|п\.і\.б\. лікаря|піб лікаря)\s*[:_]+(.*)$",
    re.IGNORECASE,
)
_INITIAL = re.compile(r"[^\W\d_]\.(?:[^\W\d_]\.)*")
_DIAGNOSIS_LABEL = re.compile(
    r"^\s*(?:заключний діагноз|клінічний діагноз|основний діагноз|діагноз|diagnosis)\s*:(.*)$",
    re.IGNORECASE,
)
_ELLIPSIS = "…"


def _is_stop_word(word: str) -> bool:
    """A word that ends the medicine's name: it has a digit or it names a dosage form."""
    return any(char.isdigit() for char in word) or word.casefold().startswith(_DOSAGE_FORMS)


def name_terms(name: str, substance: str = "") -> list[str]:
    """The words worth looking for in a document: the name's lead words, then the substance parts."""
    lead = []
    for word in name.split():
        if _is_stop_word(word):
            break
        lead.append(word.strip(",;:"))
    phrase = " ".join(lead)
    found = []
    if len(phrase) >= 3:
        found.append(phrase)
    if lead and len(lead[0]) >= 4 and lead[0] != phrase:
        found.append(lead[0])
    for part in substance.split(","):
        part = part.strip()
        if len(part) >= 4:
            found.append(part)
    distinct: list[str] = []
    for term in found:
        if term.casefold() not in {seen.casefold() for seen in distinct}:
            distinct.append(term)
    return distinct[:4]


def _doctor_name(rest: str) -> str:
    """Cut the text after a doctor label down to the name it prints."""
    rest = re.split(r" {2,}|\t|[(,\d]", rest, maxsplit=1)[0]
    rest = rest.strip(" _\t").rstrip(" _;:,-")
    # An initial keeps its dot ("О.П."); a surname with a dot after it does not.
    if re.search(r"[^\W\d_]{3,}\.$", rest):
        rest = rest[:-1]
    return rest.strip()


def doctor_in(text: str) -> str:
    """The doctor's name when the document prints it on a labelled line; "" otherwise."""
    for line in text.splitlines():
        match = _DOCTOR_LABEL.match(line)
        if not match:
            continue
        name = _doctor_name(match.group(1))
        words = name.split()
        if not (5 <= len(name) <= 60 and 2 <= len(words) <= 4):
            continue
        if all(word[0].isupper() or _INITIAL.fullmatch(word) for word in words):
            return name
    return ""


def diagnosis_in(text: str) -> str:
    """The diagnosis the document states on its first diagnosis line; "" when there is none."""
    for line in text.splitlines():
        match = _DIAGNOSIS_LABEL.match(line)
        if not match:
            continue
        value = " ".join(match.group(1).split())
        if len(value) > 200:
            value = value[:200]
            cut = value.rfind(" ")
            if cut > 0:
                value = value[:cut]
        value = value.rstrip(" .;,").strip()
        return value if len(value) >= 3 else ""
    return ""


def _window(line: str, start: int, length: int) -> str:
    """A SNIPPET_CHARS window of `line` that holds the match at `start`, cut on spaces."""
    if len(line) <= SNIPPET_CHARS:
        return line
    left = max(0, start - (SNIPPET_CHARS - length) // 2)
    end = min(len(line), left + SNIPPET_CHARS)
    left = max(0, end - SNIPPET_CHARS)
    if left > 0:
        space = line.find(" ", left, start)
        if space != -1:
            left = space + 1
    if end < len(line):
        space = line.rfind(" ", start + length, end)
        if space != -1:
            end = space
    piece = line[left:end].strip()
    return (_ELLIPSIS if left > 0 else "") + piece + (_ELLIPSIS if end < len(line) else "")


def snippet(text: str, terms: list[str]) -> str:
    """The line holding the first term found (terms in order), trimmed to a window; "" when none."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    for term in terms:
        if not term:
            continue
        for line in lines:
            start = line.lower().find(term.lower())
            if start >= 0:
                return _window(line, start, len(term))
    return ""


def _fold_cell(value) -> str:
    """Folds a column the way search terms are folded, so SQL LIKE sees the same text on both sides."""
    return search_key(value) if isinstance(value, str) else ""


def _like(folded: str) -> str:
    """A LIKE pattern that matches `folded` anywhere, with % _ and \\ taken literally."""
    escaped = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_CONTENT = "COALESCE(s.content_folded, s.content, '')"


def _mention_sql(folded_terms: list[str]) -> tuple[str, list[str]]:
    if not folded_terms:
        return "0", []
    clause = " OR ".join(f"{_CONTENT} LIKE ? ESCAPE '\\'" for _ in folded_terms)
    return f"({clause})", [_like(term) for term in folded_terms]


def _text_sql(folded_words: list[str]) -> tuple[str, list[str]]:
    clauses = []
    params: list[str] = []
    for word in folded_words:
        pattern = _like(word)
        clauses.append(
            f"({_CONTENT} LIKE ? ESCAPE '\\' OR anamna_fold(d.title) LIKE ? ESCAPE '\\'"
            " OR anamna_fold(v.canonical_name) LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])
    return " AND ".join(clauses), params


def _rows(
    connection: sqlite3.Connection,
    owner_id: str,
    mention: tuple[str, list[str]],
    extra: tuple[str, list[str]],
    limit: int,
) -> list[sqlite3.Row]:
    mention_sql, mention_params = mention
    extra_sql, extra_params = extra
    where = f" AND ({extra_sql})" if extra_sql else ""
    sql = f"""
        SELECT d.id, d.title, d.original_filename, d.clinical_type, d.report_date,
               COALESCE(d.report_date, substr(d.imported_at, 1, 10)) AS stamp,
               v.canonical_name AS clinic,
               {mention_sql} AS mentions
          FROM documents AS d
          LEFT JOIN vendors AS v ON v.id = d.vendor_id
          LEFT JOIN search_index AS s ON s.document_id = d.id AND s.owner_user_id = d.owner_user_id
         WHERE d.owner_user_id = ? AND d.duplicate_of_document_id IS NULL{where}
         ORDER BY mentions DESC, stamp DESC, d.rowid DESC
         LIMIT ?
    """
    return connection.execute(sql, [*mention_params, owner_id, *extra_params, limit]).fetchall()


def _full_text(connection: sqlite3.Connection, document_id: str) -> str:
    pages = connection.execute(
        "SELECT native_text, ocr_text FROM document_pages WHERE document_id = ? ORDER BY page_number",
        (document_id,),
    ).fetchall()
    return "\n".join(health._page_text(page) for page in pages)


def _detail(connection: sqlite3.Connection, row: sqlite3.Row, terms: list[str], words: list[str]) -> dict:
    full = _full_text(connection, row["id"])
    mentions = bool(row["mentions"])
    snip = ""
    if mentions:
        snip = snippet(full, terms)
    if not snip and words:
        snip = snippet(full, words)
    title = (row["title"] or "").strip() or os.path.splitext(row["original_filename"] or "")[0]
    return {
        "id": row["id"],
        "title": title,
        "clinical_type": row["clinical_type"] or "",
        "date": (row["stamp"] or "")[:10],
        "dated": bool(row["report_date"]),
        "clinic": row["clinic"] or "",
        "doctor": doctor_in(full),
        "diagnosis": diagnosis_in(full),
        "mentions": mentions,
        "snippet": snip,
    }


def _register(connection: sqlite3.Connection) -> None:
    # Title and clinic are plain text in the table; this folds them for the same
    # case-insensitive comparison the search terms get (SQLite LIKE is ASCII-only).
    connection.create_function("anamna_fold", 1, _fold_cell, deterministic=True)


def search(
    connection: sqlite3.Connection,
    owner_id: str,
    *,
    name: str = "",
    substance: str = "",
    text: str = "",
    limit: int = LIMIT,
) -> list[dict]:
    """The owner's documents that fit a medicine entry, best first, at most `limit`."""
    _register(connection)
    terms = name_terms(name, substance)
    words = [word for word in text.split() if len(word) >= 2][:6]
    folded_terms = [search_key(term) for term in terms]
    folded_words = [search_key(word) for word in words]
    mention = _mention_sql(folded_terms)
    if folded_words:
        rows = _rows(connection, owner_id, mention, _text_sql(folded_words), limit)
    else:
        # Documents that mention the medicine; when none do, the most recent ones.
        rows = _rows(connection, owner_id, mention, mention, limit) if folded_terms else []
        if not rows:
            rows = _rows(connection, owner_id, mention, ("", []), limit)
    return [_detail(connection, row, terms, words) for row in rows]


def one(
    connection: sqlite3.Connection,
    owner_id: str,
    document_id: str,
    *,
    name: str = "",
    substance: str = "",
) -> dict | None:
    """The same dict for one of the owner's documents, or None when it is not theirs or is a duplicate."""
    _register(connection)
    terms = name_terms(name, substance)
    folded_terms = [search_key(term) for term in terms]
    rows = _rows(
        connection, owner_id, _mention_sql(folded_terms), ("d.id = ?", [document_id]), 1,
    )
    if not rows:
        return None
    return _detail(connection, rows[0], terms, [])
