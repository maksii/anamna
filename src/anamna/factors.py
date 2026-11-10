"""Medicines and other factors that can move a measurable result.

A factor is something the person takes, has had done, has been ill with, eats or
does: a medicine, a supplement, an operation, an illness, a diet, a training
load.  Each one has a period, reference notes, and a list of effects on
concepts the charts draw.  An AI may suggest the notes and the effects; a
suggestion never overwrites what the person wrote unless they confirm it.

The functions take an open connection whose rows are ``sqlite3.Row`` and never
commit: the caller does.  They return keys and data; pages translate.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

from anamna.db import utc_now

KINDS = ("medicine", "supplement", "procedure", "illness", "diet", "activity", "other")
STATUSES = ("current", "prescribed", "past")
DIRECTIONS = ("raises", "lowers", "changes")
POINT_KINDS = ("procedure",)  # one date, not a period
REFERENCE_FIELDS = ("purpose", "usual_dose", "interactions", "monitoring", "cautions")
SUGGESTED_FIELDS = ("substance", *REFERENCE_FIELDS)
SHORT, LONG = 200, 4000
SHORT_TEXT = ("substance", "strength", "dose", "schedule", "reason", "prescriber")
LONG_TEXT = ("notes", *REFERENCE_FIELDS)
EFFECT_NOTE, EFFECT_EVIDENCE = 500, 500
FACT_MEDICINES = {
    "vka_therapy": (("B01AA",), ("warfarin", "варфарин", "acenocoumarol", "аценокумарол", "phenprocoumon", "фенпрокумон", "phenindione", "феніндіон")),
    "urate_lowering_therapy": (("M04AA", "M04AB", "M04AX"), ("allopurinol", "алопуринол", "аллопуринол", "febuxostat", "фебуксостат", "probenecid", "пробенецид", "benzbromarone", "бензбромарон", "pegloticase", "пеглотиказа")),
}

_STATUS_RANK = {"current": 0, "prescribed": 1, "past": 2}
_ATC = re.compile(r"[A-Z][0-9]{2}(?:[A-Z]{1,2}(?:[0-9]{2})?)?")
_REFERENCE_CODE = re.compile(r"[0-9]{1,12}")
_EFFECT_INDEX = re.compile(r"effect:([0-9]+)")
_TRUE_FLAGS = ("1", "on", "true")
_VALUE_COLUMNS = (
    "kind", "name", "substance", "atc_code", "strength", "dose", "schedule", "status",
    "started_on", "ended_on", "dates_approximate", "reason", "prescriber", "document_id",
    "notes", "purpose", "usual_dose", "interactions", "monitoring", "cautions",
    "reference_name", "reference_code",
)
_EFFECT_COLUMNS = "id, concept_id, label, direction, note, origin, evidence"


def _cut(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit].rstrip()


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    return date.fromisoformat(text)


def clean(form: Mapping[str, str], *, today: date) -> tuple[dict, str | None]:
    kind = str(form.get("kind") or "").strip()
    if kind not in KINDS:
        return {}, "kind"
    name = str(form.get("name") or "").strip()
    if not 1 <= len(name) <= SHORT:
        return {}, "name"
    try:
        started = _parse_date(str(form.get("started_on") or "").strip())
        ended = _parse_date(str(form.get("ended_on") or "").strip())
    except ValueError:
        return {}, "date_format"
    if started and ended and started > ended:
        return {}, "dates"

    if kind in POINT_KINDS:
        ended = None
        status = "prescribed" if started and started > today else "past"
    else:
        status = str(form.get("status") or "").strip()
        if status not in STATUSES:
            status = "current"
        if started and started > today:
            status = "prescribed"
        elif ended and ended < today:
            status = "past"
        # Otherwise the chosen status stands: a prescription dated in the past
        # that has not been started stays "prescribed".

    atc = re.sub(r"\s+", "", str(form.get("atc_code") or "")).upper()
    values: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "atc_code": atc if _ATC.fullmatch(atc) else "",
        "status": status,
        "started_on": started.isoformat() if started else None,
        "ended_on": ended.isoformat() if ended else None,
        "dates_approximate": 1 if str(form.get("dates_approximate") or "").strip() in _TRUE_FLAGS else 0,
        "document_id": str(form.get("document_id") or "").strip() or None,
    }
    for key in SHORT_TEXT:
        values[key] = _cut(form.get(key), SHORT)
    for key in LONG_TEXT:
        values[key] = _cut(form.get(key), LONG)

    reference_name = str(form.get("reference_name") or "").strip()
    name_ok = (
        1 <= len(reference_name) <= SHORT
        and not any(char in reference_name for char in "/\\?#%")
        and ".." not in reference_name
    )
    reference_code = str(form.get("reference_code") or "").strip()
    values["reference_name"] = reference_name if name_ok else ""
    values["reference_code"] = (
        reference_code if values["reference_name"] and _REFERENCE_CODE.fullmatch(reference_code) else ""
    )
    return values, None


def _document_for(connection: sqlite3.Connection, owner_id: str, document_id: str | None) -> str | None:
    if not document_id:
        return None
    found = connection.execute(
        "SELECT 1 FROM documents WHERE id=? AND owner_user_id=?", (document_id, owner_id)
    ).fetchone()
    return document_id if found else None


def _reference(values: Mapping[str, Any]) -> tuple[str, str]:
    name = values["reference_name"]
    if not name:
        return "", ""
    code = values["reference_code"]
    url = f"https://tabletki.ua/uk/{name}/" + (f"{code}/" if code else "")
    return "tabletki", url


def _names(text: str | None) -> tuple[str, ...]:
    return tuple(part for part in (text or "").split(",") if part)


def _with(names: tuple[str, ...], name: str) -> tuple[str, ...]:
    return names if name in names else (*names, name)


def _suggestion(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _suggested_text(suggestion: Mapping[str, Any], name: str) -> str:
    entry = (suggestion.get("fields") or {}).get(name)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("text") or "").strip()


def create(connection: sqlite3.Connection, owner_id: str, patient_id: str, values: Mapping[str, Any]) -> str:
    factor_id = str(uuid.uuid4())
    now = utc_now()
    row: dict[str, Any] = {key: values[key] for key in _VALUE_COLUMNS}
    row["document_id"] = _document_for(connection, owner_id, values["document_id"])
    row["reference_source"], row["reference_url"] = _reference(values)
    row.update(id=factor_id, owner_user_id=owner_id, patient_id=patient_id, created_at=now, updated_at=now)
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO factors ({columns}) VALUES ({marks})", tuple(row.values()))
    return factor_id


def update(connection: sqlite3.Connection, owner_id: str, factor_id: str, values: Mapping[str, Any]) -> bool:
    current = connection.execute(
        "SELECT * FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if current is None:
        return False
    changed = {name for name in SUGGESTED_FIELDS if current[name] != values[name]}
    names = tuple(name for name in _names(current["ai_fields"]) if name not in changed)
    row: dict[str, Any] = {key: values[key] for key in _VALUE_COLUMNS}
    row["document_id"] = _document_for(connection, owner_id, values["document_id"])
    row["reference_source"], row["reference_url"] = _reference(values)
    row["ai_fields"] = ",".join(names)
    row["updated_at"] = utc_now()
    assignments = ", ".join(f"{column}=?" for column in row)
    connection.execute(
        f"UPDATE factors SET {assignments} WHERE id=? AND owner_user_id=?",
        (*row.values(), factor_id, owner_id),
    )
    return True


def delete(connection: sqlite3.Connection, owner_id: str, factor_id: str) -> bool:
    cursor = connection.execute("DELETE FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id))
    return cursor.rowcount > 0


def stop(connection: sqlite3.Connection, owner_id: str, factor_id: str, on: date) -> bool:
    row = connection.execute(
        "SELECT kind, started_on FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if row is None or row["kind"] in POINT_KINDS:
        return False
    ended = on
    started = _parse_date(row["started_on"])
    if started and started > on:
        ended = started
    _write(connection, owner_id, factor_id, {"ended_on": ended.isoformat(), "status": "past"})
    return True


def effective_status(row: Mapping[str, Any], today: date) -> str:
    ended = _parse_date(row["ended_on"])
    if ended and ended < today:
        return "past"
    return row["status"]


def implied_facts(row: Mapping[str, Any]) -> tuple[str, ...]:
    if row["kind"] == "illness":
        return ("illness", "infection_or_inflammation")
    if row["kind"] != "medicine":
        return ()
    atc = row["atc_code"] or ""
    text = f"{row['substance']} {row['name']}".casefold()
    return tuple(
        fact
        for fact, (prefixes, words) in FACT_MEDICINES.items()
        if any(atc.startswith(prefix) for prefix in prefixes) or any(word in text for word in words)
    )


def _effect(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "concept_id": row["concept_id"],
        "label": row["label"],
        "direction": row["direction"],
        "note": row["note"],
        "origin": row["origin"],
        "evidence": row["evidence"],
    }


def _shape(row: sqlite3.Row, effects: list[dict], today: date) -> dict:
    data = dict(row)
    data["effective_status"] = effective_status(row, today)
    data["effects"] = effects
    data["suggestion"] = _suggestion(row["suggestion_json"])
    data["facts"] = implied_facts(row)
    data["ai_fields"] = _names(row["ai_fields"])
    data["is_point"] = row["kind"] in POINT_KINDS
    return data


def get(connection: sqlite3.Connection, owner_id: str, factor_id: str, *, today: date) -> dict | None:
    row = connection.execute(
        "SELECT * FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if row is None:
        return None
    effects = [
        _effect(effect)
        for effect in connection.execute(
            f"SELECT {_EFFECT_COLUMNS} FROM factor_effects WHERE factor_id=? AND owner_user_id=? "
            "ORDER BY created_at, id",
            (factor_id, owner_id),
        )
    ]
    return _shape(row, effects, today)


def _when(factor: Mapping[str, Any]) -> str | None:
    if factor["effective_status"] == "past":
        return factor["ended_on"] or factor["started_on"]
    return factor["started_on"]


def listing(connection: sqlite3.Connection, owner_id: str, *, today: date) -> list[dict]:
    rows = connection.execute("SELECT * FROM factors WHERE owner_user_id=?", (owner_id,)).fetchall()
    by_factor: dict[str, list[dict]] = {}
    for effect in connection.execute(
        f"SELECT factor_id, {_EFFECT_COLUMNS} FROM factor_effects WHERE owner_user_id=? ORDER BY created_at, id",
        (owner_id,),
    ):
        by_factor.setdefault(effect["factor_id"], []).append(_effect(effect))
    shaped = [_shape(row, by_factor.get(row["id"], []), today) for row in rows]
    # Stable sorts, applied last key first: status, then date descending with
    # the unknown dates last, then name.
    shaped.sort(key=lambda factor: factor["name"])
    shaped.sort(key=lambda factor: _when(factor) or "", reverse=True)
    shaped.sort(key=lambda factor: _STATUS_RANK[factor["effective_status"]])
    return shaped


def _write(connection: sqlite3.Connection, owner_id: str, factor_id: str, changes: Mapping[str, Any]) -> None:
    changes = {**changes, "updated_at": utc_now()}
    assignments = ", ".join(f"{column}=?" for column in changes)
    connection.execute(
        f"UPDATE factors SET {assignments} WHERE id=? AND owner_user_id=?",
        (*changes.values(), factor_id, owner_id),
    )


def add_effect(
    connection: sqlite3.Connection,
    owner_id: str,
    factor_id: str,
    *,
    concept_id: str | None,
    label: str,
    direction: str,
    note: str = "",
    origin: str = "person",
    evidence: str = "",
) -> str | None:
    if direction not in DIRECTIONS:
        return None
    owned = connection.execute(
        "SELECT 1 FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if owned is None:
        return None
    concept: str | None = None
    label = _cut(label, SHORT)
    if concept_id:
        found = connection.execute("SELECT canonical_name FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if found is not None:
            concept = concept_id
            label = label or _cut(found["canonical_name"], SHORT)
    if concept is None and not label:
        return None

    if concept is not None:
        existing = connection.execute(
            "SELECT id FROM factor_effects WHERE factor_id=? AND concept_id=?", (factor_id, concept)
        ).fetchone()
        if existing is not None:
            return existing["id"]
    else:
        wanted = label.casefold()
        for other in connection.execute("SELECT id, label FROM factor_effects WHERE factor_id=?", (factor_id,)):
            if other["label"].casefold() == wanted:
                return other["id"]

    effect_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO factor_effects(id, factor_id, owner_user_id, concept_id, label, direction,
               note, origin, evidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            effect_id, factor_id, owner_id, concept, label, direction,
            _cut(note, EFFECT_NOTE), origin, _cut(evidence, EFFECT_EVIDENCE), utc_now(),
        ),
    )
    return effect_id


def remove_effect(connection: sqlite3.Connection, owner_id: str, effect_id: str) -> bool:
    cursor = connection.execute("DELETE FROM factor_effects WHERE id=? AND owner_user_id=?", (effect_id, owner_id))
    return cursor.rowcount > 0


def periods(connection: sqlite3.Connection, owner_id: str, concept_ids, *, today: date) -> list[dict]:
    wanted = set(concept_ids)
    rows = connection.execute(
        "SELECT * FROM factors WHERE owner_user_id=? AND started_on IS NOT NULL AND status <> 'prescribed'",
        (owner_id,),
    ).fetchall()
    related: dict[str, sqlite3.Row] = {}
    for effect in connection.execute(
        "SELECT factor_id, concept_id, direction, note, origin FROM factor_effects "
        "WHERE owner_user_id=? AND concept_id IS NOT NULL ORDER BY created_at, id",
        (owner_id,),
    ):
        if effect["concept_id"] in wanted:
            related.setdefault(effect["factor_id"], effect)
    out = []
    for row in rows:
        match = related.get(row["id"])
        point = row["kind"] in POINT_KINDS or (
            effective_status(row, today) == "past" and row["ended_on"] is None
        )
        out.append({
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "start": row["started_on"],
            "end": row["ended_on"] or None,
            "point": point,
            "approximate": bool(row["dates_approximate"]),
            "related": match is not None,
            "direction": match["direction"] if match else "",
            "note": match["note"] if match else "",
            "origin": match["origin"] if match else "",
        })
    out.sort(key=lambda period: (period["start"], period["name"]))
    return out


def fact_periods(connection: sqlite3.Connection, owner_id: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    rows = connection.execute(
        "SELECT * FROM factors WHERE owner_user_id=? AND started_on IS NOT NULL AND status <> 'prescribed' "
        "ORDER BY started_on, id",
        (owner_id,),
    )
    for row in rows:
        if row["status"] == "past" and row["ended_on"] is None:
            continue
        for fact in implied_facts(row):
            out.append((fact, row["started_on"], row["ended_on"]))
    return out


def facts_on(periods: list[tuple[str, str, str | None]], day: str) -> set[str]:
    wanted = day[:10]
    return {
        fact
        for fact, start, end in periods
        if start[:10] <= wanted and (end is None or wanted <= end[:10])
    }


def store_suggestion(connection: sqlite3.Connection, owner_id: str, factor_id: str, suggestion: dict) -> bool:
    cursor = connection.execute(
        "UPDATE factors SET suggestion_json=?, suggestion_at=? WHERE id=? AND owner_user_id=?",
        (json.dumps(suggestion, ensure_ascii=False), utc_now(), factor_id, owner_id),
    )
    return cursor.rowcount > 0


def _usable_effect(effect: Any) -> bool:
    if not isinstance(effect, dict) or effect.get("direction") not in DIRECTIONS:
        return False
    return bool(effect.get("concept_id") or str(effect.get("label") or "").strip())


def _has_effect(existing: list[dict], effect: Mapping[str, Any]) -> bool:
    concept = effect.get("concept_id") or None
    if concept:
        return any(item.get("concept_id") == concept for item in existing)
    label = str(effect.get("label") or "").strip().casefold()
    return any(str(item.get("label") or "").strip().casefold() == label for item in existing)


def pending(factor: Mapping[str, Any]) -> dict:
    suggestion = factor.get("suggestion")
    if not suggestion:
        return {"fields": [], "effects": [], "empty": True}
    fields = []
    for name in SUGGESTED_FIELDS:
        text = _suggested_text(suggestion, name)
        current = factor.get(name) or ""
        if text and text != current.strip():
            entry = (suggestion.get("fields") or {}).get(name)
            quote = str(entry.get("quote") or "") if isinstance(entry, dict) else ""
            fields.append({"name": name, "text": text, "quote": quote, "current": current})
    existing = factor.get("effects") or []
    effects = [
        {**effect, "index": index}
        for index, effect in enumerate(suggestion.get("effects") or [])
        if _usable_effect(effect) and not _has_effect(existing, effect)
    ]
    return {"fields": fields, "effects": effects, "empty": not fields and not effects}


def apply_suggestion(connection: sqlite3.Connection, owner_id: str, factor_id: str, what: str, *, today: date) -> bool:
    row = connection.execute(
        "SELECT * FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if row is None:
        return False
    suggestion = _suggestion(row["suggestion_json"])
    if not suggestion:
        return False

    if what == "dismiss":
        _write(connection, owner_id, factor_id, {"suggestion_json": None, "suggestion_at": None})
        return True

    if what == "all":
        names = _names(row["ai_fields"])
        changes: dict[str, Any] = {}
        for name in SUGGESTED_FIELDS:
            text = _suggested_text(suggestion, name)
            if text and not (row[name] or "").strip():
                changes[name] = text
                names = _with(names, name)
        if changes:
            changes["ai_fields"] = ",".join(names)
        shaped = get(connection, owner_id, factor_id, today=today)
        for effect in pending(shaped)["effects"]:
            add_effect(
                connection, owner_id, factor_id,
                concept_id=effect.get("concept_id") or None,
                label=str(effect.get("label") or ""),
                direction=effect["direction"],
                note=str(effect.get("note") or ""),
                origin="ai",
                evidence=str(effect.get("quote") or ""),
            )
        _write(connection, owner_id, factor_id, changes)
        return True

    if what in SUGGESTED_FIELDS:
        text = _suggested_text(suggestion, what)
        if text:
            names = _with(_names(row["ai_fields"]), what)
            _write(connection, owner_id, factor_id, {what: text, "ai_fields": ",".join(names)})
        return True

    match = _EFFECT_INDEX.fullmatch(what)
    if match:
        effects = suggestion.get("effects") or []
        index = int(match.group(1))
        if index >= len(effects) or not _usable_effect(effects[index]):
            return False
        effect = effects[index]
        added = add_effect(
            connection, owner_id, factor_id,
            concept_id=effect.get("concept_id") or None,
            label=str(effect.get("label") or ""),
            direction=effect["direction"],
            note=str(effect.get("note") or ""),
            origin="ai",
            evidence=str(effect.get("quote") or ""),
        )
        if added is None:
            return False
        _write(connection, owner_id, factor_id, {})
        return True
    return False


def search_rows(connection: sqlite3.Connection, owner_id: str) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT id, name, substance, kind, status, reason FROM factors WHERE owner_user_id=? ORDER BY name, id",
            (owner_id,),
        )
    ]


def _line(factor: Mapping[str, Any], *, detail: bool) -> str:
    inside = [factor["kind"]]
    if factor["substance"]:
        inside.append(factor["substance"])
    if factor["atc_code"]:
        inside.append(f"ATC {factor['atc_code']}")
    head = f"- {factor['name']} [{'; '.join(inside)}]"
    dosing = "; ".join(
        part
        for part in (factor["strength"], ", ".join(value for value in (factor["dose"], factor["schedule"]) if value))
        if part
    )
    if dosing:
        head += f" {dosing}"
    parts = []
    if factor["started_on"]:
        parts.append(f"since {factor['started_on']}")
    if detail and factor["effective_status"] == "past" and factor["ended_on"]:
        parts.append(f"until {factor['ended_on']}")
    if detail and factor["dates_approximate"]:
        parts.append("(dates approximate)")
    if factor["effective_status"] == "prescribed":
        parts.append("prescribed, not started")
    if factor["reason"]:
        parts.append(f"for {factor['reason']}")
    if not detail and factor["effects"]:
        parts.append(
            "effects: " + ", ".join(f"{effect['direction']} {effect['label']}" for effect in factor["effects"][:6])
        )
    line = head + ("; " + "; ".join(parts) if parts else "")
    return f"{line} m:{factor['id']}"


def chat_lines(connection: sqlite3.Connection, owner_id: str, *, today: date) -> list[str]:
    factors = listing(connection, owner_id, today=today)
    if not factors:
        return [
            "## medicines and other factors",
            "none recorded. When it matters, ask what the person takes and does; they can add medicines, "
            "supplements, operations, illnesses, diet and training on the Medicines page.",
        ]
    counts = Counter(factor["effective_status"] for factor in factors)
    lines = [
        f"## medicines and other factors ({counts['current']} current, "
        f"{counts['prescribed']} prescribed but not started, {counts['past']} past; detail: get_medicines)"
    ]
    lines.extend(_line(factor, detail=False) for factor in factors if factor["effective_status"] != "past")
    return lines


_FIELD_LINES = (
    ("purpose", "what it is:"),
    ("usual_dose", "usual dosing:"),
    ("interactions", "interactions:"),
    ("monitoring", "to monitor:"),
    ("cautions", "cautions:"),
    ("prescriber", "prescribed by:"),
    ("notes", "notes:"),
)


def _block(factor: Mapping[str, Any]) -> str:
    lines = [_line(factor, detail=True)]
    for key, label in _FIELD_LINES:
        if factor[key]:
            lines.append(f"  {label} {factor[key]}")
    if factor["document_id"]:
        lines.append(f"  document: d:{factor['document_id']}")
    for effect in factor["effects"]:
        text = f"  effect: {effect['direction']} {effect['label']}"
        if effect["note"]:
            text += f" ({effect['note']})"
        if effect["origin"] == "ai":
            text += " [from an AI suggestion the person accepted]"
        lines.append(text)
    return "\n".join(lines)


def chat_detail(connection: sqlite3.Connection, owner_id: str, *, today: date, factor_id: str = "") -> str:
    wanted = factor_id.strip()
    if wanted.startswith("m:"):
        wanted = wanted[2:]
    if factor_id.strip():
        factor = get(connection, owner_id, wanted, today=today)
        return _block(factor) if factor else "No such medicine or factor."
    factors = listing(connection, owner_id, today=today)
    if not factors:
        return "No medicines or other factors are recorded."
    return "\n\n".join(_block(factor) for factor in factors)
