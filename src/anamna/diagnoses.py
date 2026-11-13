"""Diagnoses on the person's record: what it says they have, with status, dates and a source.

A diagnosis has an ICD-10 code from the catalogue, the words it was written under, or
both.  It is active, resolved or outdated, and either confirmed or provisional.

The functions take an open connection whose rows are ``sqlite3.Row`` and never
commit: the caller does.  They return keys and data; pages translate.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

from anamna import icd10
from anamna.db import utc_now

STATUSES = ("active", "resolved", "outdated")
CERTAINTIES = ("confirmed", "provisional")
NAME_LIMIT, CLINICIAN_LIMIT, NOTES_LIMIT = 200, 200, 2000
_TRUE_FLAGS = ("1", "on", "true")
_COLUMNS = (
    "code", "name", "status", "certainty", "diagnosed_on", "resolved_on",
    "dates_approximate", "clinician", "document_id", "notes",
)


def _text(form: Mapping[str, object], key: str, limit: int | None = None) -> str:
    """The posted value under ``key`` as stripped text, cut to ``limit`` when given."""
    text = str(form.get(key) or "").strip()
    return text[:limit].rstrip() if limit else text


def _fail(errors: list[str], key: str) -> None:
    if key not in errors:
        errors.append(key)


def _day(text: str, *, today: date, errors: list[str]) -> date | None:
    """The date written as ``text``; None when blank or not a usable date."""
    if not text:
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        _fail(errors, "date_invalid")
        return None
    if day > today:
        _fail(errors, "date_future")
    return day


def clean(form: Mapping[str, object], *, today: date) -> tuple[dict, list[str]]:
    """The values to store from a posted form, and the error keys the form must show."""
    errors: list[str] = []
    raw_code = _text(form, "code")
    code = icd10.normalize(raw_code) if raw_code else ""
    if raw_code and icd10.entry(code) is None:
        _fail(errors, "code_unknown")
        code = raw_code
    has_code = bool(code) and "code_unknown" not in errors

    name = _text(form, "name", NAME_LIMIT)
    if not name and not has_code:
        _fail(errors, "name_required")

    status = _text(form, "status")
    if status not in STATUSES:
        status = "active"
    certainty = _text(form, "certainty")
    if certainty not in CERTAINTIES:
        certainty = "confirmed"

    diagnosed = _day(_text(form, "diagnosed_on"), today=today, errors=errors)
    resolved = None
    if status != "active":
        resolved = _day(_text(form, "resolved_on"), today=today, errors=errors)
        if diagnosed and resolved and resolved < diagnosed:
            _fail(errors, "date_order")

    values = {
        "code": code,
        "name": name,
        "status": status,
        "certainty": certainty,
        "diagnosed_on": diagnosed.isoformat() if diagnosed else None,
        "resolved_on": resolved.isoformat() if resolved else None,
        "dates_approximate": 1 if _text(form, "dates_approximate") in _TRUE_FLAGS else 0,
        "clinician": _text(form, "clinician", CLINICIAN_LIMIT),
        "document_id": _text(form, "document_id") or None,
        "notes": _text(form, "notes", NOTES_LIMIT),
    }
    return values, errors


def create(
    connection: sqlite3.Connection, owner_id: str, patient_id: str, values: Mapping[str, Any], *,
    origin: str = "person",
) -> str:
    """Insert a diagnosis for the owner and return its id."""
    diagnosis_id = str(uuid.uuid4())
    now = utc_now()
    row: dict[str, Any] = {key: values[key] for key in _COLUMNS}
    row.update(
        id=diagnosis_id, owner_user_id=owner_id, patient_id=patient_id, origin=origin,
        created_at=now, updated_at=now,
    )
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO diagnoses ({columns}) VALUES ({marks})", tuple(row.values()))
    return diagnosis_id


def update(connection: sqlite3.Connection, owner_id: str, diagnosis_id: str, values: Mapping[str, Any]) -> bool:
    """Replace the cleaned columns of one of the owner's diagnoses; False when no row matched."""
    row: dict[str, Any] = {key: values[key] for key in _COLUMNS}
    row["updated_at"] = utc_now()
    assignments = ", ".join(f"{column}=?" for column in row)
    cursor = connection.execute(
        f"UPDATE diagnoses SET {assignments} WHERE id=? AND owner_user_id=?",
        (*row.values(), diagnosis_id, owner_id),
    )
    return cursor.rowcount > 0


def set_status(
    connection: sqlite3.Connection, owner_id: str, diagnosis_id: str, status: str, *, today: date,
) -> bool:
    """Change the status; a resolved or outdated diagnosis gets an end date, an active one loses it."""
    if status not in STATUSES:
        return False
    row = connection.execute(
        "SELECT diagnosed_on, resolved_on FROM diagnoses WHERE id=? AND owner_user_id=?",
        (diagnosis_id, owner_id),
    ).fetchone()
    if row is None:
        return False
    resolved = None
    if status != "active":
        resolved = row["resolved_on"] or today.isoformat()
        if row["diagnosed_on"] and resolved < row["diagnosed_on"]:
            resolved = row["diagnosed_on"]
    connection.execute(
        "UPDATE diagnoses SET status=?, resolved_on=?, updated_at=? WHERE id=? AND owner_user_id=?",
        (status, resolved, utc_now(), diagnosis_id, owner_id),
    )
    return True


def delete(connection: sqlite3.Connection, owner_id: str, diagnosis_id: str) -> bool:
    """Delete one of the owner's diagnoses; False when no row matched.  What the documents said about it goes to the hidden suggestions, where the person can offer it again."""
    if get(connection, owner_id, diagnosis_id) is None:
        return False
    connection.execute(
        "UPDATE diagnosis_candidates SET state='dismissed', diagnosis_id=NULL WHERE diagnosis_id=? AND owner_user_id=?",
        (diagnosis_id, owner_id),
    )
    cursor = connection.execute("DELETE FROM diagnoses WHERE id=? AND owner_user_id=?", (diagnosis_id, owner_id))
    return cursor.rowcount > 0


def get(connection: sqlite3.Connection, owner_id: str, diagnosis_id: str) -> dict | None:
    """One of the owner's diagnoses as a dict, or None."""
    row = connection.execute(
        "SELECT * FROM diagnoses WHERE id=? AND owner_user_id=?", (diagnosis_id, owner_id)
    ).fetchone()
    return dict(row) if row is not None else None


def listing(connection: sqlite3.Connection, owner_id: str) -> list[dict]:
    """All of the owner's diagnoses: active first, then newest diagnosed_on, undated last."""
    rows = connection.execute(
        "SELECT * FROM diagnoses WHERE owner_user_id=? "
        "ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, diagnosed_on IS NULL, "
        "diagnosed_on DESC, created_at DESC",
        (owner_id,),
    ).fetchall()
    return [dict(row) for row in rows]


_DETAIL_SEPARATORS = " ,.;:-–—"


def display_name(row: Mapping[str, Any], locale: str) -> str:
    """The catalogue title of the code in the reader's language.  Without a catalogued code, the
    name as written.  Without a name, the code."""
    code = str(row["code"] or "")
    title = icd10.name(code, locale) if code else ""
    return title or str(row["name"] or "").strip() or code


def written_detail(row: Mapping[str, Any], locale: str = "uk") -> str:
    """What the person or the document wrote beyond the title the reader sees; '' when the name
    only repeats a catalogue title.

    Only the reader's own title is cut off: under an English title, «еутиреоз» left over from
    «Нетоксичний одновузловий зоб, еутиреоз» read as though the document said just that."""
    name = str(row["name"] or "").strip()
    code = str(row["code"] or "")
    if not name or not code or icd10.entry(code) is None:
        return ""
    if any(title and name.casefold() == title.casefold() for title in (icd10.name(code, "uk"), icd10.name(code, "en"))):
        return ""
    title = icd10.name(code, locale)
    if title and name.casefold().startswith(title.casefold()):
        return name[len(title):].lstrip(_DETAIL_SEPARATORS)
    return name


def active_codes(connection: sqlite3.Connection, owner_id: str) -> set[str]:
    """The codes of the owner's active diagnoses, whether confirmed or provisional."""
    rows = connection.execute(
        "SELECT DISTINCT code FROM diagnoses WHERE owner_user_id=? AND status='active' AND code <> ''",
        (owner_id,),
    ).fetchall()
    return {row["code"] for row in rows}
