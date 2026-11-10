"""Medicines and other factors that can move a measurable result.

A factor is something the person takes, has had done, has been ill with, eats or
does: a medicine, a supplement, an operation, an illness, a diet, a training
load.  Each one has a period, a dose and a schedule, reference notes, and a list
of effects on concepts the charts draw.  An AI may suggest the notes and the
effects; the person reviews them on the form before anything is saved.

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
from anamna.i18n import (
    activate_locale,
    format_number_localized,
    get_locale,
    plural_form,
    reset_locale,
    t,
    t_plural,
)

KINDS = ("medicine", "supplement", "procedure", "illness", "diet", "activity", "other")
STATUSES = ("current", "prescribed", "past")
DIRECTIONS = ("raises", "lowers", "changes")
POINT_KINDS = ("procedure",)  # one date, not a period
REFERENCE_FIELDS = ("purpose", "usual_dose", "interactions", "monitoring", "cautions")
SUGGESTED_FIELDS = ("substance", *REFERENCE_FIELDS)
SHORT, LONG = 200, 4000
SHORT_TEXT = ("substance", "strength", "dose", "schedule", "reason", "prescriber")
LONG_TEXT = ("notes", *REFERENCE_FIELDS)
EFFECT_NOTE, EFFECT_EVIDENCE, EFFECT_QUOTE = 500, 500, 400
AI_EFFECT_LIMIT = 20
FACT_MEDICINES = {
    "vka_therapy": (("B01AA",), ("warfarin", "варфарин", "acenocoumarol", "аценокумарол", "phenprocoumon", "фенпрокумон", "phenindione", "феніндіон")),
    "urate_lowering_therapy": (("M04AA", "M04AB", "M04AX"), ("allopurinol", "алопуринол", "аллопуринол", "febuxostat", "фебуксостат", "probenecid", "пробенецид", "benzbromarone", "бензбромарон", "pegloticase", "пеглотиказа")),
}
DOSE_UNITS = ("tablet", "capsule", "drop", "ml", "mg", "g", "mcg", "iu", "puff", "sachet",
              "suppository", "application", "patch", "injection", "piece")
REPEATS = ("daily", "days", "weekly", "monthly", "as_needed")
DAY_PARTS = ("morning", "midday", "evening", "night")
MEALS = ("before", "with", "after", "empty")
REGIMEN_KINDS = ("medicine", "supplement")            # a dose, times a day, food
REPEAT_KINDS = ("medicine", "supplement", "activity")  # how often

_STATUS_RANK = {"current": 0, "prescribed": 1, "past": 2}
_ATC = re.compile(r"[A-Z][0-9]{2}(?:[A-Z]{1,2}(?:[0-9]{2})?)?")
_REFERENCE_CODE = re.compile(r"[0-9]{1,12}")
_CLOCK = re.compile(r"[0-2][0-9]:[0-5][0-9]")
_TRUE_FLAGS = ("1", "on", "true")
_VALUE_COLUMNS = (
    "kind", "name", "substance", "atc_code", "strength", "dose", "schedule", "status",
    "started_on", "ended_on", "dates_approximate", "reason", "prescriber", "document_id",
    "notes", "purpose", "usual_dose", "interactions", "monitoring", "cautions",
    "reference_name", "reference_code", "dose_amount", "dose_unit", "schedule_json",
)
_EFFECT_COLUMNS = "id, concept_id, label, direction, note, origin, evidence"


def _cut(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit].rstrip()


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    return date.fromisoformat(text)


def _many(form: Any, name: str) -> list[str]:
    """Every non-empty value posted under ``name``; a plain dict may hold a single value or a list."""
    if hasattr(form, "getlist"):
        values = form.getlist(name)
    else:
        value = form.get(name)
        values = value if isinstance(value, (list, tuple)) else [value]
    return [str(item).strip() for item in values if item is not None and str(item).strip()]


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _count(value: Any, high: int) -> int:
    """A whole number from 1 to ``high``; 1 when the value does not parse."""
    number = _to_int(value)
    return 1 if number is None else min(max(number, 1), high)


def _valid_clock(text: str) -> bool:
    return _CLOCK.fullmatch(text) is not None and int(text[:2]) <= 23


def _dose_amount(form: Mapping[str, Any]) -> float | None:
    text = str(form.get("dose_amount") or "").strip().replace(",", ".")
    try:
        amount = round(float(text), 3)
    except ValueError:
        return None
    return amount if 0 < amount <= 100000 else None


def _schedule(form: Mapping[str, Any], kind: str) -> str:
    """The schedule as JSON, or '' when the kind has none or no valid repeat was posted."""
    repeat = str(form.get("repeat") or "").strip()
    if kind not in REPEAT_KINDS or repeat not in REPEATS:
        return ""
    every = _count(form.get("every"), 99)
    if repeat in ("daily", "as_needed"):
        every = 1
    if repeat == "days" and every == 1:
        repeat = "daily"
    weekdays: list[int] = []
    if repeat == "weekly":
        days = {_to_int(item) for item in _many(form, "weekday")}
        weekdays = sorted(day for day in days if day is not None and 0 <= day <= 6)
    if kind in REGIMEN_KINDS:
        posted_parts = set(_many(form, "day_part"))
        times = [part for part in DAY_PARTS if part in posted_parts]
        clock = sorted({text for text in _many(form, "clock") if _valid_clock(text)})[:12]
        per_day = max(_count(form.get("per_day"), 24), len(times) + len(clock))
        meal = str(form.get("meal") or "").strip()
        if meal not in MEALS:
            meal = ""
    else:
        per_day, times, clock, meal = 1, [], [], ""
    return json.dumps(
        {
            "repeat": repeat, "every": every, "weekdays": weekdays, "per_day": per_day,
            "times": times, "clock": clock, "meal": meal,
        },
        separators=(",", ":"),
    )


def _ai_effects(form: Mapping[str, Any]) -> list[dict]:
    """The accepted AI effects the form posts, each a JSON object; the first few usable ones."""
    effects: list[dict] = []
    for raw in _many(form, "ai_effect"):
        if len(effects) == AI_EFFECT_LIMIT:
            break
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("direction") not in DIRECTIONS:
            continue
        concept = item.get("concept_id")
        concept_id = concept.strip() if isinstance(concept, str) else ""
        effects.append({
            "concept_id": concept_id or None,
            "label": _cut(item.get("label"), SHORT),
            "direction": item["direction"],
            "note": _cut(item.get("note"), EFFECT_NOTE),
            "quote": _cut(item.get("quote"), EFFECT_QUOTE),
        })
    return effects


def clean(form: Mapping[str, Any], *, today: date) -> tuple[dict, str | None]:
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

    amount = _dose_amount(form) if kind in REGIMEN_KINDS else None
    unit = str(form.get("dose_unit") or "").strip()
    values["dose_amount"] = amount
    values["dose_unit"] = unit if amount is not None and unit in DOSE_UNITS else ""
    values["schedule_json"] = _schedule(form, kind)
    posted_fields = {part.strip() for part in str(form.get("ai_fields") or "").split(",")}
    values["ai_fields"] = tuple(
        field for field in SUGGESTED_FIELDS if field in posted_fields and values[field]
    )
    values["ai_effects"] = _ai_effects(form)
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


def _has_effect(existing: list[dict], effect: Mapping[str, Any]) -> bool:
    """True when an effect on the same concept, or with the same label, is already there."""
    concept = effect.get("concept_id") or None
    label = str(effect.get("label") or "").strip().casefold()
    for item in existing:
        if concept and item.get("concept_id") == concept:
            return True
        if label and str(item.get("label") or "").strip().casefold() == label:
            return True
    return False


def _add_ai_effects(connection: sqlite3.Connection, owner_id: str, factor_id: str, effects: list[dict]) -> None:
    existing = [
        {"concept_id": row["concept_id"], "label": row["label"]}
        for row in connection.execute(
            "SELECT concept_id, label FROM factor_effects WHERE factor_id=? AND owner_user_id=?",
            (factor_id, owner_id),
        )
    ]
    for effect in effects:
        if _has_effect(existing, effect):
            continue
        add_effect(
            connection, owner_id, factor_id,
            concept_id=effect.get("concept_id") or None,
            label=str(effect.get("label") or ""),
            direction=effect["direction"],
            note=str(effect.get("note") or ""),
            origin="ai",
            evidence=str(effect.get("quote") or ""),
        )
        existing.append({"concept_id": effect.get("concept_id") or None, "label": effect.get("label") or ""})


def create(connection: sqlite3.Connection, owner_id: str, patient_id: str, values: Mapping[str, Any]) -> str:
    factor_id = str(uuid.uuid4())
    now = utc_now()
    row: dict[str, Any] = {key: values[key] for key in _VALUE_COLUMNS}
    row["document_id"] = _document_for(connection, owner_id, values["document_id"])
    row["reference_source"], row["reference_url"] = _reference(values)
    row["ai_fields"] = ",".join(values.get("ai_fields", ()))
    row.update(id=factor_id, owner_user_id=owner_id, patient_id=patient_id, created_at=now, updated_at=now)
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO factors ({columns}) VALUES ({marks})", tuple(row.values()))
    _add_ai_effects(connection, owner_id, factor_id, values.get("ai_effects", []))
    return factor_id


def update(connection: sqlite3.Connection, owner_id: str, factor_id: str, values: Mapping[str, Any]) -> bool:
    current = connection.execute(
        "SELECT * FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if current is None:
        return False
    changed = {name for name in SUGGESTED_FIELDS if current[name] != values[name]}
    names = tuple(name for name in _names(current["ai_fields"]) if name not in changed)
    for name in values.get("ai_fields", ()):
        names = _with(names, name)
    names = tuple(name for name in SUGGESTED_FIELDS if name in names)
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
    _add_ai_effects(connection, owner_id, factor_id, values.get("ai_effects", []))
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


def _regimen(text: str | None) -> dict | None:
    """The schedule stored as JSON, with every key filled in; None when there is none."""
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("repeat") not in REPEATS:
        return None
    plan: dict[str, Any] = {
        "repeat": value["repeat"], "every": 1, "weekdays": [], "per_day": 1,
        "times": [], "clock": [], "meal": "",
    }
    for key in ("every", "weekdays", "per_day", "times", "clock", "meal"):
        if key in value:
            plan[key] = value[key]
    return plan


def _shape(row: sqlite3.Row, effects: list[dict], today: date) -> dict:
    data = dict(row)
    data["effective_status"] = effective_status(row, today)
    data["effects"] = effects
    data["regimen"] = _regimen(row["schedule_json"])
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


def search_rows(connection: sqlite3.Connection, owner_id: str) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT id, name, substance, kind, status, reason FROM factors WHERE owner_user_id=? ORDER BY name, id",
            (owner_id,),
        )
    ]


def _amount_form(amount: float) -> str:
    """The plural form of a dose amount.  A fraction takes the Ukrainian genitive singular, the "few" form."""
    if float(amount).is_integer():
        return plural_form(int(amount))
    return "few" if get_locale() == "uk" else "many"


def _plan_parts(plan: Mapping[str, Any], kind: str) -> list[str]:
    repeat = plan["repeat"]
    every = plan["every"]
    per_day = plan["per_day"]
    when = [t(f"med.daypart.{part}") for part in plan["times"]] + list(plan["clock"])
    regimen = kind in REGIMEN_KINDS
    parts: list[str] = []
    if repeat == "as_needed":
        text = t("med.regimen.as_needed")
        if per_day > 1:
            text += ", " + t_plural("med.regimen.up_to", per_day)
        parts.append(text)
    elif repeat == "daily":
        if regimen:
            text = t_plural("med.regimen.per_day", per_day)
            if when:
                text += " (" + ", ".join(when) + ")"
        else:
            text = t("med.regimen.daily")
        parts.append(text)
    elif repeat == "days":
        parts.append(t_plural("med.regimen.days", every))
    elif repeat == "weekly":
        text = t("med.regimen.week1") if every == 1 else t_plural("med.regimen.weeks", every)
        if plan["weekdays"]:
            days = ", ".join(t(f"med.weekday.{day}") for day in plan["weekdays"])
            text += " " + t("med.regimen.on_days", days=days)
        parts.append(text)
    elif repeat == "monthly":
        parts.append(t("med.regimen.month1") if every == 1 else t_plural("med.regimen.months", every))
    if repeat in ("days", "weekly", "monthly") and regimen:
        if per_day > 1:
            text = t_plural("med.regimen.per_day", per_day)
            if when:
                text += " (" + ", ".join(when) + ")"
            parts.append(text)
        elif when:
            parts.append(", ".join(when))
    if plan["meal"]:
        parts.append(t(f"med.meal.{plan['meal']}"))
    return parts


def _regimen_parts(row: Mapping[str, Any]) -> list[str]:
    parts: list[str] = []
    amount = row.get("dose_amount")
    if amount is not None:
        number = format_number_localized(amount, 3)
        unit = row.get("dose_unit") or ""
        if unit:
            unit_word = t(f"med.unit.{unit}_{_amount_form(amount)}")
            parts.append(f"{number} {unit_word}")
        else:
            parts.append(number)
    elif row.get("dose"):
        parts.append(row["dose"])
    plan = row.get("regimen")
    if isinstance(plan, dict):
        parts.extend(_plan_parts(plan, row.get("kind") or ""))
    if row.get("schedule"):
        parts.append(row["schedule"])
    return parts


def regimen_text(row: Mapping[str, Any], locale: str) -> str:
    """One line saying how the thing is taken: the dose, the times and days, the meal, then the note."""
    token = activate_locale(locale)
    try:
        parts = _regimen_parts(row)
    finally:
        reset_locale(token)
    return " · ".join(parts)


def _line(factor: Mapping[str, Any], *, detail: bool) -> str:
    inside = [factor["kind"]]
    if factor["substance"]:
        inside.append(factor["substance"])
    if factor["atc_code"]:
        inside.append(f"ATC {factor['atc_code']}")
    head = f"- {factor['name']} [{'; '.join(inside)}]"
    dosing = "; ".join(part for part in (factor["strength"], regimen_text(factor, "en")) if part)
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
