"""What the scan of documents found, as the person reviews it: grouped, accepted or dismissed.

The scan writes one candidate per mention in a document.  This module folds
the mentions of one medicine, procedure or illness into a single group, offers
the group to the person, and turns the chosen groups into entries of
``factors``.  Nothing here calls an AI.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from typing import Any

from anamna import factors
from anamna.health import _page_text

try:  # written by another agent; the list works without it
    from anamna import factor_documents
except ImportError:
    factor_documents = None

RECENT_DAYS = 90
DOCUMENTS_SHOWN = 5

_CANDIDATES = """
    SELECT c.*, d.title AS doc_title, d.original_filename AS doc_filename,
           COALESCE(d.report_date, substr(d.imported_at, 1, 10)) AS doc_date,
           v.canonical_name AS clinic
    FROM factor_candidates c
    JOIN documents d ON d.id = c.document_id
    LEFT JOIN vendors v ON v.id = d.vendor_id
    WHERE c.owner_user_id = ? AND c.state = 'new'
"""


def groups(connection: sqlite3.Connection, owner_id: str, *, today: date, locale: str) -> list[dict]:
    """The offered groups, not yet existing ones first."""
    return [group for group, _items in _build(connection, owner_id, today=today, locale=locale)]


def count(connection: sqlite3.Connection, owner_id: str) -> int:
    """How many groups are offered, leaving out the ones the record already has."""
    return sum(1 for group in groups(connection, owner_id, today=date.today(), locale="en") if not group["existing"])


def accept(
    connection: sqlite3.Connection,
    owner_id: str,
    patient_id: str,
    keys: list[str],
    statuses: dict[str, str],
    *,
    today: date,
) -> list[str]:
    """Make one entry per chosen group.  Does not commit."""
    wanted = {group["key"]: (group, items) for group, items in _build(connection, owner_id, today=today, locale="en")}
    created: list[str] = []
    for key in dict.fromkeys(keys):
        if key not in wanted or wanted[key][0]["existing"]:
            continue
        group, items = wanted[key]
        status = statuses.get(key)
        if status not in factors.STATUSES:
            status = group["suggested_status"]
        form = _form(connection, group, items, status)
        values, error = factors.clean(form, today=today)
        if error:
            # Retry once without the end date, in case the end date is the
            # part the form rejects.
            form["ended_on"] = ""
            values, error = factors.clean(form, today=today)
        if error:
            continue
        factor_id = factors.create(connection, owner_id, patient_id, values)
        connection.executemany(
            "UPDATE factor_candidates SET state='accepted', factor_id=? WHERE id=? AND owner_user_id=?",
            [(factor_id, item["id"], owner_id) for item in items],
        )
        created.append(factor_id)
    return created


def dismiss(connection: sqlite3.Connection, owner_id: str, keys: list[str]) -> int:
    """Mark the offered mentions of the named groups as not wanted.  Does not commit."""
    dismissed = 0
    for key in dict.fromkeys(keys):
        kind, _, name_key = key.partition(":")
        cursor = connection.execute(
            "UPDATE factor_candidates SET state='dismissed' "
            "WHERE owner_user_id=? AND state='new' AND kind=? AND name_key=?",
            (owner_id, kind, name_key),
        )
        if cursor.rowcount > 0:
            dismissed += 1
    return dismissed


def _fold(text: str | None) -> str:
    return " ".join(str(text or "").split()).casefold()


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _mention(row: sqlite3.Row) -> dict:
    data = dict(row)
    doc_day = (row["doc_date"] or "")[:10]
    data["doc_day"] = doc_day
    # The document's date stands only for an item it says is present now.
    # A past or planned item with no date of its own has no date.
    data["day"] = row["event_date"] or (doc_day if row["timing"] == "now" else "")
    data["own_day"] = bool(row["event_date"])
    data["title"] = row["doc_title"] or os.path.splitext(row["doc_filename"])[0]
    # The stored schedule, with every key filled in; None when there is none.
    data["plan"] = factors._regimen(row["schedule_json"])
    data["has_regimen"] = row["dose_amount"] is not None or data["plan"] is not None
    return data


def _regimen_view(mention: dict) -> dict:
    return {
        "kind": mention["kind"],
        "dose_amount": mention["dose_amount"],
        "dose_unit": mention["dose_unit"],
        "dose": "",
        "schedule": "",
        "regimen": mention["plan"],
    }


def _status(kind: str, latest: dict, first: str, today: date) -> tuple[str, str, str]:
    """The status, start and end the latest mention suggests, as (status, started_on, ended_on).

    ``first`` is the earliest dated mention of the group, "" when none has a date.
    """
    day = latest["day"]
    if kind in factors.POINT_KINDS:
        # One date: when it happened, or when it is scheduled.
        status = "prescribed" if latest["timing"] == "planned" else "past"
        return status, day, ""
    if latest["timing"] == "past":
        return "past", first, ""
    if latest["timing"] == "planned":
        return "prescribed", day, ""
    if latest["stopped"]:
        # The document says when it was stopped, not when it was started.
        started = first if first and first < day else ""
        return "past", started, day
    when = _day(day)
    if latest["duration_days"] > 0 and when is not None:
        ended = when + timedelta(days=latest["duration_days"])
        return ("past" if ended < today else "current"), first, ended.isoformat()
    if latest["long_term"]:
        return "current", first, ""
    if when is not None and (today - when).days <= RECENT_DAYS:
        return "current", first, ""
    return "past", first, ""


def _day_exact(items: list[dict], day: str) -> bool:
    """Whether a mention that gave this day states it in full.  True when there is no day."""
    if not day:
        return True
    # The document's own date (no event date) is exact; an event date is exact only when marked so.
    return any(item["day"] == day and (not item["own_day"] or bool(item["date_exact"])) for item in items)


def _group(kind: str, name_key: str, items: list[dict], *, today: date, locale: str) -> dict:
    """One group from its mentions, latest first."""
    latest = items[0]

    def first_known(field: str) -> str:
        return next((item[field] for item in items if item[field]), "")

    regimen = next((item for item in items if item["has_regimen"]), None)
    how_written = first_known("how_written")
    days = [item["day"] for item in items if item["day"]]
    first_date = min(days) if days else ""
    last_date = max(days) if days else ""
    first_exact = _day_exact(items, first_date)
    last_exact = _day_exact(items, last_date)
    status, started, ended = _status(kind, latest, first_date, today)
    # A stopped medicine has no regimen to show: its written sentence is the instruction to stop.
    if latest["stopped"]:
        how = ""
    else:
        how = factors.regimen_text(_regimen_view(regimen), locale) if regimen else how_written
    by_document: dict[str, dict] = {}
    for item in items:
        by_document.setdefault(item["document_id"], item)
    newest = sorted(by_document.values(), key=lambda item: (item["doc_day"], item["created_at"]), reverse=True)
    return {
        "key": f"{kind}:{name_key}",
        "kind": kind,
        "name": latest["name"],
        "substance": first_known("substance"),
        "strength": first_known("strength"),
        "how": how,
        "how_written": how_written,
        "first_date": first_date,
        "last_date": last_date,
        "first_exact": first_exact,
        "last_exact": last_exact,
        "reason": first_known("reason"),
        "quote": latest["quote"],
        "documents": [
            {"id": item["document_id"], "title": item["title"], "date": item["doc_day"]}
            for item in newest[:DOCUMENTS_SHOWN]
        ],
        "mentions": len(by_document),
        "suggested_status": status,
        "started_on": started,
        "ended_on": ended,
    }


def _existing(kind: str, name_key: str, substance: str, entries: list[tuple[str, str, str]]) -> bool:
    """True when the record already holds this medicine, by name or by substance."""
    substance_key = _fold(substance)
    for entry_kind, entry_name, entry_substance in entries:
        if entry_kind != kind:
            continue
        if (
            entry_name == name_key
            or entry_name.startswith(name_key + " ")
            or name_key.startswith(entry_name + " ")
        ):
            return True
        if substance_key and entry_substance == substance_key:
            return True
    return False


def _build(connection: sqlite3.Connection, owner_id: str, *, today: date, locale: str) -> list[tuple[dict, list[dict]]]:
    """Each group with its mentions, in the order the page shows them."""
    mentions = [_mention(row) for row in connection.execute(_CANDIDATES, (owner_id,))]
    # Latest first.  An empty day is the smallest string, so undated mentions sort last.
    mentions.sort(key=lambda item: (item["day"], item["created_at"]), reverse=True)
    by_group: dict[tuple[str, str], list[dict]] = {}
    for item in mentions:
        by_group.setdefault((item["kind"], item["name_key"]), []).append(item)
    entries = [
        (entry["kind"], _fold(entry["name"]), _fold(entry["substance"]))
        for entry in factors.listing(connection, owner_id, today=today)
    ]
    built = []
    for (kind, name_key), items in by_group.items():
        group = _group(kind, name_key, items, today=today, locale=locale)
        group["existing"] = _existing(kind, name_key, group["substance"], entries)
        built.append((group, items))
    # Stable sorts, applied last key first: name, then latest date descending,
    # then kind in the factors order, then not-existing first.
    built.sort(key=lambda pair: pair[0]["name"])
    built.sort(key=lambda pair: pair[0]["last_date"], reverse=True)
    built.sort(key=lambda pair: factors.KINDS.index(pair[0]["kind"]))
    built.sort(key=lambda pair: pair[0]["existing"])
    return built


def _doctor_name(connection: sqlite3.Connection, document_id: str) -> str:
    finder = getattr(factor_documents, "doctor_in", None)
    if finder is None:
        return ""
    pages = connection.execute(
        "SELECT native_text, ocr_text FROM document_pages WHERE document_id=? ORDER BY page_number",
        (document_id,),
    ).fetchall()
    text = "\n".join(_page_text(page) for page in pages)
    return str(finder(text) or "").strip()


def _prescriber(connection: sqlite3.Connection, mention: dict) -> str:
    doctor = _doctor_name(connection, mention["document_id"])
    clinic = (mention["clinic"] or "").strip()
    return ", ".join(part for part in (doctor, clinic) if part)


def _form(connection: sqlite3.Connection, group: dict, items: list[dict], status: str) -> dict[str, Any]:
    """The form ``factors.clean`` reads, filled from the group."""
    latest = items[0]
    point = group["kind"] in factors.POINT_KINDS
    earliest = min(items, key=lambda item: (item["day"] == "", item["day"], item["created_at"]))
    regimen = next((item for item in items if item["has_regimen"]), None)
    form: dict[str, Any] = {
        "kind": group["kind"],
        "name": group["name"],
        "substance": group["substance"],
        "strength": group["strength"],
        "status": status,
        "started_on": group["started_on"],
        "ended_on": group["ended_on"] if status == "past" else "",
        # Only a full date the document gave is exact; a month or a year, or
        # no date at all, is approximate.
        "dates_approximate": "0" if point and latest["date_exact"] == 1 and latest["own_day"] else "1",
        "reason": group["reason"],
        "prescriber": _prescriber(connection, earliest),
        "document_id": earliest["document_id"],
        # A stopped medicine's sentence is the instruction to stop, not a regimen.
        "schedule": "" if latest["stopped"] or regimen else group["how_written"],
    }
    if regimen:
        if regimen["dose_amount"] is not None:
            form["dose_amount"] = str(regimen["dose_amount"])
        form["dose_unit"] = regimen["dose_unit"]
        if regimen["plan"]:
            plan = regimen["plan"]
            form.update(
                repeat=plan["repeat"], every=str(plan["every"]), per_day=str(plan["per_day"]),
                day_part=plan["times"], meal=plan["meal"],
            )
    return form
