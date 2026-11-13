"""Diagnoses a person's documents name with an ICD-10 code, read without a model.

A consultation's diagnosis text (``summary_uk``) and the coded lines of its
text («Код МКХ Х: K11.2») print codes the document itself wrote.  The codes
are checked against the catalogue; a code in the diagnosis text must also
share a word stem with its catalogue title, so an ICPC-2 reason-for-encounter
code is not taken for a diagnosis.  Candidates wait for the person: accepting
one makes a diagnosis, dismissing one hides it.  Nothing here calls an AI.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date

from . import diagnoses, icd10
from .db import utc_now

# A code is a letter, two digits and an optional decimal part.  Cyrillic
# look-alikes are allowed; icd10.normalize folds them to Latin.
_CODE = r"[A-ZАВЕІКМНОРСТХ][0-9]{2}(?:[.,][0-9]{1,2})?"
_CODE_IN_TEXT = re.compile(rf"(?<![^\W_])({_CODE})(?![^\W_])", re.IGNORECASE)
_CODE_START = re.compile(rf"{_CODE}(?![^\W_])", re.IGNORECASE)
_RANGE = re.compile(rf"{_CODE}\s*[-–]\s*{_CODE}", re.IGNORECASE)
_LABEL = r"(?:Основний|Супутній|Клінічний діагноз)\s*:\s*"
_PIECE = re.compile(rf"^(?:{_LABEL})?({_CODE})(?![^\W_])(.*)$", re.IGNORECASE | re.DOTALL)
_CODED_LABEL = re.compile(r"(?:Код\s+)?МКХ(?:-10|\s?10|\s[ХX])?\s*:", re.IGNORECASE)
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_WORD = re.compile(r"[^\W\d_]+")


def _is_condition(code: str) -> bool:
    return icd10.entry(code) is not None and icd10.is_condition(code)


def _stems(text: str) -> set[str]:
    """The first five letters of each word of five letters or more, casefolded."""
    words = _WORD.findall(text.replace("'", "").replace("’", "").replace("ʼ", ""))
    return {word.casefold()[:5] for word in words if len(word) >= 5}


def _names_catalogue(name: str, code: str) -> bool:
    """Whether the written name shares a stem with the code's title or its category's."""
    entry = icd10.entry(code)
    titles = [entry["uk"]]
    category = icd10.entry(entry["category"])
    if category is not None:
        titles.append(category["uk"])
    return bool(_stems(name) & _stems(" ".join(titles)))


def _clean_name(rest: str) -> str:
    """The name after a code: the separator removed, the trailing question mark too."""
    return re.sub(r"^\s*[-–:,]?\s*", "", rest).strip().rstrip("?").strip()


def codes_in(text: str) -> set[str]:
    """The normalized catalogue-shaped codes that the text prints."""
    return {icd10.normalize(raw) for raw in _CODE_IN_TEXT.findall(text)} - {""}


def parse_summary(text: str) -> list[dict]:
    """Coded diagnoses in a consultation's diagnosis text.  [] when the text starts with «Скарги»
    (no diagnosis was written).  Split at ';' and line ends.  A piece that starts (after an
    optional «Основний:», «Супутній:», «Клінічний діагноз:» label) with an ICD-10 code followed
    by optional ' - ', ':' or a space and a name gives {code, name, certainty, quote}.
    code: icd10.normalize; kept only when icd10.entry(code) exists and icd10.is_condition(code).
    A range such as 'L20-L30' is skipped.
    Guard against ICPC-2 codes (they look the same: 'A44 вакцинація' is not bartonellosis): the
    written name must share a stem with the catalogue's Ukrainian title of the code or of its
    category.  Stem = the first 5 letters (casefold) of any word of 5 letters or more.
    certainty 'provisional' when the piece holds '?', else 'confirmed'.  name is cut to 200.
    quote is the piece as written, cut to 400."""
    if text.lstrip().startswith("Скарги"):
        return []
    items: list[dict] = []
    for raw_piece in re.split(r"[;\r\n]+", text):
        piece = raw_piece.strip()
        match = _PIECE.match(piece)
        if match is None:
            continue
        code = icd10.normalize(match.group(1))
        name = _clean_name(match.group(2))
        if not name or _CODE_START.match(name) or not _is_condition(code):
            continue
        if not _names_catalogue(name, code):
            continue
        items.append({
            "code": code,
            "name": name[:200],
            "certainty": "provisional" if "?" in piece else "confirmed",
            "quote": piece[:400],
        })
    return items


def parse_coded_line(text: str) -> list[dict]:
    """«Код МКХ Х: K11.2», «МКХ-10: E78.2» lines in a document's full text: the same dict, with
    name '' and the line as the quote.  Same catalogue checks."""
    items: list[dict] = []
    for line in text.splitlines():
        if "ICPC" in line.upper():
            continue
        label = _CODED_LABEL.search(line)
        if label is None:
            continue
        rest = line[label.end():]
        # A range (L20-L30) is not one diagnosis: the line gives none.
        if _RANGE.search(rest):
            continue
        certainty = "provisional" if "?" in line else "confirmed"
        quote = line.strip()[:400]
        for raw in _CODE_IN_TEXT.findall(rest):
            code = icd10.normalize(raw)
            if _is_condition(code):
                items.append({"code": code, "name": "", "certainty": certainty, "quote": quote})
    return items


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def key_of(code: str, name_key: str) -> str:
    """The group key: the code when there is one, else 'n:' and the name."""
    return code if code else "n:" + name_key


def _day(value: str | None) -> tuple[str | None, int]:
    """The document's date as (ISO day or None, date_exact)."""
    text = (value or "")[:10]
    if not _ISO_DAY.fullmatch(text):
        return None, 0
    try:
        date.fromisoformat(text)
    except ValueError:
        return None, 0
    return text, 1


def dismissed_keys(connection: sqlite3.Connection, owner_id: str) -> set[str]:
    """The keys the owner has dismissed."""
    rows = connection.execute(
        "SELECT DISTINCT code, name_key FROM diagnosis_candidates WHERE owner_user_id = ? AND state = 'dismissed'",
        (owner_id,),
    ).fetchall()
    return {key_of(row[0], row[1]) for row in rows}


def collect(connection: sqlite3.Connection, owner_id: str) -> int:
    """Read the coded diagnoses of the owner's consultations and clinical reports into candidates.

    Returns the number of candidates inserted.  Does not commit.
    """
    dismissed = dismissed_keys(connection, owner_id)
    rows = connection.execute(
        """SELECT f.document_id, f.summary_uk, f.summary_en, f.original_text, d.report_date
             FROM clinical_findings f
             JOIN documents d ON d.id = f.document_id
            WHERE f.owner_user_id = ?
              AND d.clinical_type IN ('consultation', 'clinical_report')
              AND d.duplicate_of_document_id IS NULL""",
        (owner_id,),
    ).fetchall()
    now = utc_now()
    inserted = 0
    for row in rows:
        event_date, date_exact = _day(row["report_date"])
        found = parse_summary(row["summary_uk"] or row["summary_en"]) + parse_coded_line(row["original_text"])
        for item in found:
            name_key = _fold(item["name"])
            state = "dismissed" if key_of(item["code"], name_key) in dismissed else "new"
            cursor = connection.execute(
                """INSERT OR IGNORE INTO diagnosis_candidates (
                       id, owner_user_id, document_id, method, code, code_printed, name, name_key,
                       certainty, timing, event_date, date_exact, quote, state, diagnosis_id, created_at)
                   VALUES (?, ?, ?, 'code', ?, 1, ?, ?, ?, 'now', ?, ?, ?, ?, NULL, ?)""",
                (
                    str(uuid.uuid4()), owner_id, row["document_id"], item["code"], item["name"], name_key,
                    item["certainty"], event_date, date_exact, item["quote"], state, now,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def _diagnosis_index(connection: sqlite3.Connection, owner_id: str) -> list[tuple[str, str, str]]:
    """(id, code, folded name) of the owner's diagnoses, the active ones first."""
    return [
        (row["id"], row["code"], _fold(row["name"]))
        for row in connection.execute(
            "SELECT id, code, name FROM diagnoses WHERE owner_user_id = ? "
            "ORDER BY (status = 'active') DESC, created_at",
            (owner_id,),
        )
    ]


def _existing_id(index: list[tuple[str, str, str]], code: str, name_key: str) -> str | None:
    for diagnosis_id, diagnosis_code, diagnosis_name in index:
        if code and diagnosis_code == code:
            return diagnosis_id
        if not code and diagnosis_name == name_key:
            return diagnosis_id
    return None


def _group(key: str, members: list[dict], index: list[tuple[str, str, str]], locale: str) -> dict:
    """One group from its mentions, latest first."""
    latest = members[0]
    code = next((member["code"] for member in members if member["code"]), "")
    written = next((member["name"] for member in members if member["name"]), "")
    title = icd10.name(code, locale)
    days = [member["event_date"] for member in members if member["event_date"]]
    dated: dict[str, str] = {}
    for member in members:
        day = member["event_date"] or ""
        dated[member["document_id"]] = max(dated.get(member["document_id"], ""), day)
    documents = sorted(dated.items(), key=lambda pair: pair[1], reverse=True)
    return {
        "key": key,
        "code": code,
        "name": written or title,
        "title": title,
        "certainty": latest["certainty"],
        "mentions": len(dated),
        "first_date": min(days) if days else "",
        "last_date": max(days) if days else "",
        "quote": latest["quote"],
        "methods": sorted({member["method"] for member in members}),
        "code_printed": any(bool(member["code_printed"]) for member in members),
        "documents": [{"id": document_id, "date": day} for document_id, day in documents],
        "existing_id": _existing_id(index, code, latest["name_key"]),
    }


def _offered(connection: sqlite3.Connection, owner_id: str, state: str, *, locale: str) -> list[tuple[dict, list[dict]]]:
    """The groups in ``state`` ('new' or 'dismissed') with their mentions, newest group first.

    A key with a new and a dismissed mention is neither offered nor dismissed.
    """
    rows = [
        dict(row) for row in connection.execute(
            "SELECT * FROM diagnosis_candidates WHERE owner_user_id = ? AND state IN ('new', 'dismissed')",
            (owner_id,),
        )
    ]
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        by_key.setdefault(key_of(row["code"], row["name_key"]), []).append(row)
    other = "dismissed" if state == "new" else "new"
    index = _diagnosis_index(connection, owner_id)
    built: list[tuple[dict, list[dict]]] = []
    for key, found in by_key.items():
        states = {row["state"] for row in found}
        if state not in states or other in states:
            continue
        members = [row for row in found if row["state"] == state]
        # Latest first; an undated mention sorts last.
        members.sort(key=lambda row: (row["event_date"] or "", row["created_at"]), reverse=True)
        built.append((_group(key, members, index, locale), members))
    built.sort(key=lambda pair: pair[0]["name"].casefold())
    built.sort(key=lambda pair: pair[0]["last_date"], reverse=True)
    return built


def groups(connection: sqlite3.Connection, owner_id: str, *, locale: str) -> list[dict]:
    """The 'new' candidates, one group per key, newest last_date first."""
    return [group for group, _members in _offered(connection, owner_id, "new", locale=locale)]


def dismissed(connection: sqlite3.Connection, owner_id: str, *, locale: str) -> list[dict]:
    """The dismissed groups, in the same shape as ``groups``."""
    return [group for group, _members in _offered(connection, owner_id, "dismissed", locale=locale)]


def accept(connection: sqlite3.Connection, owner_id: str, patient_id: str, keys: list[str]) -> list[str]:
    """Link each chosen group to its existing diagnosis, or create one from the document.

    Returns the diagnosis ids touched, each once.  Does not commit.
    """
    offered = {group["key"]: (group, members) for group, members in _offered(connection, owner_id, "new", locale="en")}
    touched: list[str] = []
    for key in dict.fromkeys(keys):
        if key not in offered:
            continue
        group, members = offered[key]
        if group["existing_id"]:
            diagnosis_id = group["existing_id"]
        else:
            latest = members[0]
            diagnosis_id = diagnoses.create(
                connection, owner_id, patient_id,
                {
                    "code": group["code"],
                    "name": next((member["name"] for member in members if member["name"]), ""),
                    "status": "active",
                    "certainty": latest["certainty"],
                    "diagnosed_on": group["first_date"] or None,
                    "resolved_on": None,
                    "dates_approximate": 1,
                    "clinician": "",
                    "document_id": latest["document_id"],
                    "notes": "",
                },
                origin="document",
            )
        connection.executemany(
            "UPDATE diagnosis_candidates SET state='accepted', diagnosis_id=? WHERE id=? AND owner_user_id=?",
            [(diagnosis_id, member["id"], owner_id) for member in members],
        )
        if diagnosis_id not in touched:
            touched.append(diagnosis_id)
    return touched


def _key_match(key: str) -> tuple[str, tuple[str, ...]]:
    """The SQL condition that selects the candidates of one group key."""
    if key.startswith("n:"):
        return "code = '' AND name_key = ?", (key[2:],)
    return "code = ?", (key,)


def _set_state(connection: sqlite3.Connection, owner_id: str, keys: list[str], current: str, target: str) -> int:
    changed = 0
    for key in dict.fromkeys(keys):
        condition, params = _key_match(key)
        cursor = connection.execute(
            f"UPDATE diagnosis_candidates SET state = ? WHERE owner_user_id = ? AND state = ? AND {condition}",
            (target, owner_id, current, *params),
        )
        if cursor.rowcount > 0:
            changed += 1
    return changed


def dismiss(connection: sqlite3.Connection, owner_id: str, keys: list[str]) -> int:
    """Mark the offered candidates of the named groups as not wanted.  Does not commit."""
    return _set_state(connection, owner_id, keys, "new", "dismissed")


def restore(connection: sqlite3.Connection, owner_id: str, keys: list[str]) -> int:
    """Offer the dismissed candidates of the named groups again.  Does not commit."""
    return _set_state(connection, owner_id, keys, "dismissed", "new")


def mentions(connection: sqlite3.Connection, owner_id: str, diagnosis_id: str) -> list[dict]:
    """The accepted candidates of one diagnosis, oldest first."""
    rows = connection.execute(
        "SELECT document_id, event_date, quote, name, certainty, method, created_at "
        "FROM diagnosis_candidates WHERE owner_user_id = ? AND diagnosis_id = ? AND state = 'accepted'",
        (owner_id, diagnosis_id),
    ).fetchall()
    rows = sorted(rows, key=lambda row: (row["event_date"] is None, row["event_date"] or "", row["created_at"]))
    return [
        {
            "document_id": row["document_id"],
            "date": row["event_date"] or "",
            "quote": row["quote"],
            "name": row["name"],
            "certainty": row["certainty"],
            "method": row["method"],
        }
        for row in rows
    ]
