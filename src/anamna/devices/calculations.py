"""Missing BMI values, calculated with dated, person-specific dependencies.

The equation is CDC's weight (kg) / height (m) squared:
https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html
This is a provisional calculation, never a newly verified measurement.  A
reported BMI always wins.  Children require a height from the same day;
carrying a height forward is allowed only when both measurements are adult.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime

from ..db import utc_now
from ..health import age_on
from ..reference import canonical_unit
from .exclusions import OPENWEARABLES, _rule, label_for, source_rule_names
from .reconcile import select_daily, valid_row
from .timezone import user_timezone
from .units import convert_quantity, finite_number

BMI_ID_PREFIX = "derived-bmi-"
BMI_SOURCE = "Calculated BMI"
#: Two heights of one day within this distance are one height, not a disagreement.
HEIGHT_AGREEMENT_CM = 0.5
_COLUMNS = (
    "owner_user_id", "patient_id", "import_id", "source_name", "source_vendor",
    "metric_key", "metric_name", "category", "day", "aggregation", "unit",
    "value", "value_min", "value_max", "value_sum", "sample_count",
)


def _day(value, *, timestamp: bool = False) -> str | None:
    try:
        text = str(value)
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        if timestamp:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        return None
    except ValueError:
        return None


def _height_cm(value, unit) -> float | None:
    number = finite_number(value)
    folded = canonical_unit(unit)
    if number is None or not folded:
        return None
    try:
        number = convert_quantity(number, folded, "cm")
    except ValueError:
        return None
    return number if number is not None and math.isfinite(number) and 30 < number < 280 else None


def _height_for(patient, day, heights):
    try:
        born = date.fromisoformat(str(patient["date_of_birth"])).isoformat()
    except ValueError:
        born = None
    adult = (age_on(born, day) or 0) >= 20
    eligible = defaultdict(list)
    for item in heights:
        height_day = item[2]
        if height_day > day:
            continue
        if height_day != day and not (adult and (age_on(born, height_day) or 0) >= 20):
            continue
        eligible[height_day].append(item)
    for height_day in sorted(eligible, reverse=True):
        choices = eligible[height_day]
        values = [item[3] for item in choices]
        # Two heights recorded that day agree when they are the same height
        # written twice (170 and 170.2). When they genuinely disagree, do not
        # choose a clinical interpretation by database insertion order: the
        # previous eligible day speaks instead.
        if max(values) - min(values) <= HEIGHT_AGREEMENT_CM:
            return min(choices, key=lambda item: (item[0] != "observation_height", item))
    # The profile height covers an adult weight no dated height is eligible
    # for, including every weight older than the first measured height.
    if adult:
        height = _height_cm(patient["height_cm"], "cm")
        if height is not None:
            return ("profile_height", str(patient["id"]), None, height, "cm")
    return None


def _excluded_calculation(connection):
    """Bind exclusion rules to the inputs' original writer, never to Anamna.

    A daily aggregate has lost the exact instant of its latest sample.  An
    explicit reading exclusion on that day therefore withholds a fallback
    derived from that origin: absence is safer than recreating a number the
    person said was not theirs.  Stored weight evidence is left untouched.
    """
    imports = dict(connection.execute("SELECT id, adapter_key FROM device_imports"))
    active = defaultdict(list)
    for row in connection.execute("SELECT * FROM device_exclusions WHERE revoked_at IS NULL"):
        active[str(row["owner_user_id"])].append(row)
    bound = {}

    def excluded(row, key):
        owner = str(row["owner_user_id"])
        context = str(imports.get(row["import_id"], ""))
        if context.startswith("openwearables"):
            context = OPENWEARABLES
        identity = (owner, context, str(row["source_name"]))
        if identity not in bound:
            # Body-series raw samples, including OpenWearables, are grouped
            # with local_day; their date is not the server's UTC summary day.
            zone = user_timezone(connection, owner)
            names = source_rule_names(identity[2])
            rules = [_rule(item) for item in active[owner] if label_for(item, context) in names]
            bound[identity] = (zone, rules)
        zone, rules = bound[identity]
        day = date.fromisoformat(str(row["day"]))
        for rule in rules:
            if rule.series is not None and key not in rule.series:
                continue
            if rule.scope == "reading":
                if rule.lower.astimezone(zone).date() == day:
                    return True
            elif rule.covers(key, None, day, None, zone):
                return True
        return False

    return excluded


def _wanted(connection):
    patients = {str(row["id"]): dict(row) for row in connection.execute("SELECT * FROM patients")}
    preferences = defaultdict(dict)
    for row in connection.execute("SELECT owner_user_id, preference_group, source_key FROM device_source_preferences"):
        preferences[str(row[0])][str(row[1])] = str(row[2])
    excluded = _excluded_calculation(connection)
    device = [dict(row) for row in connection.execute(
        """SELECT m.* FROM device_metric_days m JOIN device_imports i ON i.id=m.import_id
           AND i.owner_user_id=m.owner_user_id AND i.patient_id=m.patient_id
           WHERE m.metric_key IN ('body_weight', 'body_height', 'body_mass_index')"""
    )]
    printed = {
        (str(row["owner_user_id"]), str(row["patient_id"]), str(row["day"]))
        for row in device if row["metric_key"] == "body_mass_index" and not str(row["id"]).startswith(BMI_ID_PREFIX)
    }
    # A clinical BMI is also a reported value, and must not be duplicated by a
    # newly computed device copy of the same person's measurement day.
    printed.update(
        (str(row[0]), str(row[1]), str(row[2])[:10])
        for row in connection.execute(
            """SELECT o.owner_user_id, o.patient_id, o.observed_at FROM observations o
               JOIN patients p ON p.id=o.patient_id AND p.owner_user_id=o.owner_user_id
               LEFT JOIN documents d ON d.id=o.document_id
               LEFT JOIN reports r ON r.id=o.report_id
               LEFT JOIN documents rd ON rd.id=r.document_id
               WHERE o.concept_id='body-mass-index' AND o.verification_status<>'rejected'
                 AND (substr(o.extraction_method, 1, 8)<>'derived_' OR o.extraction_method='derived_bmi')
                 AND (o.document_id IS NULL OR (d.owner_user_id=o.owner_user_id AND d.patient_id=o.patient_id))
                 AND (o.report_id IS NULL OR (r.owner_user_id=o.owner_user_id AND r.patient_id=o.patient_id
                      AND rd.owner_user_id=o.owner_user_id AND rd.patient_id=o.patient_id
                      AND (o.document_id IS NULL OR r.document_id=o.document_id)))"""
        )
    )
    weights, device_heights = defaultdict(list), defaultdict(list)
    for row in device:
        identity = (str(row["owner_user_id"]), str(row["patient_id"]))
        if _day(row["day"]) is None:
            continue
        if excluded(row, str(row["metric_key"])):
            continue
        if row["metric_key"] == "body_weight" and canonical_unit(row["unit"]) == "kg" and valid_row(row):
            weights[identity].append(row)
        if row["metric_key"] == "body_height":
            height = _height_cm(row["value"], row["unit"])
            if height is not None:
                device_heights[identity].append({**row, "value": height, "unit": "cm"})
    heights = defaultdict(list)
    for identity, rows in device_heights.items():
        for row in select_daily(rows, preferences[identity[0]].get("body_height", "")):
            heights[identity].append(("device_height", str(row["id"]), str(row["day"]), float(row["value"]), "cm"))
    for row in connection.execute(
        """SELECT o.* FROM observations o
           JOIN patients p ON p.id=o.patient_id AND p.owner_user_id=o.owner_user_id
           LEFT JOIN documents d ON d.id=o.document_id
           LEFT JOIN reports r ON r.id=o.report_id
           LEFT JOIN documents rd ON rd.id=r.document_id
           WHERE o.concept_id='body-height'
           AND o.verification_status IN ('verified', 'corrected') AND o.value_numeric IS NOT NULL
           AND COALESCE(o.comparator, '')='' AND substr(o.extraction_method, 1, 8)<>'derived_'
           AND TRIM(COALESCE(NULLIF(o.report_id, ''), o.document_id, '')) <> ''
           AND (o.document_id IS NULL OR (d.owner_user_id=o.owner_user_id AND d.patient_id=o.patient_id))
           AND (o.report_id IS NULL OR (r.owner_user_id=o.owner_user_id AND r.patient_id=o.patient_id
                AND rd.owner_user_id=o.owner_user_id AND rd.patient_id=o.patient_id
                AND (o.document_id IS NULL OR r.document_id=o.document_id)))"""
    ):
        height = _height_cm(row["value_numeric"], row["unit_raw"])
        height_day = _day(row["observed_at"], timestamp=True)
        if height is not None and height_day:
            heights[(str(row["owner_user_id"]), str(row["patient_id"]))].append(
                ("observation_height", str(row["id"]), height_day, height, "cm")
            )
    wanted = {}
    for identity, rows in weights.items():
        owner, patient_id = identity
        patient = patients.get(patient_id)
        if patient is None or str(patient["owner_user_id"]) != owner:
            continue
        for weight in select_daily(rows, preferences[owner].get("body_weight", "")):
            day = str(weight["day"])
            if (
                (owner, patient_id, day) in printed
                or excluded(weight, "body_mass_index")
                or excluded({**weight, "source_name": BMI_SOURCE}, "body_mass_index")
            ):
                continue
            height = _height_for(patient, day, heights[identity])
            if height is None:
                continue
            value = round(float(weight["value"]) / (height[3] / 100) ** 2, 2)
            row_id = BMI_ID_PREFIX + hashlib.sha256(str(weight["id"]).encode()).hexdigest()
            values = (
                owner, patient_id, weight["import_id"], BMI_SOURCE, "Anamna", "body_mass_index",
                "Body mass index", "device_body", day, "latest", "kg/m²", value, value, value, value, 1,
            )
            inputs = (
                ("device_weight", str(weight["id"]), day, float(weight["value"]), "kg"), height,
            )
            wanted[row_id] = (values, inputs)
    # The existing device natural key is owner/source/metric/day.  Multiple
    # patients under one owner on one day are ambiguous in that schema.
    counts = Counter((values[0], values[8]) for values, _ in wanted.values())
    return {key: item for key, item in wanted.items() if counts[(item[0][0], item[0][8])] == 1}


def refresh_device_calculations(connection: sqlite3.Connection) -> dict[str, int]:
    """Reconcile fallback BMI and dependency rows without committing the caller's transaction."""
    counts = {"added": 0, "updated": 0, "removed": 0}
    changed_owners = set()
    # Read-only tools can still open backups predating the provenance table.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='device_calculation_inputs'").fetchone():
        return counts
    wanted = _wanted(connection)
    existing = {str(row["id"]): row for row in connection.execute(
        "SELECT * FROM device_metric_days WHERE substr(id, 1, ?)=?", (len(BMI_ID_PREFIX), BMI_ID_PREFIX)
    )}
    # Remove obsolete selected-source rows first, since the natural key must
    # be free before the newly selected weight's calculation is inserted.
    for row_id in existing.keys() - wanted.keys():
        changed_owners.add(str(existing[row_id]["owner_user_id"]))
        connection.execute("DELETE FROM device_metric_days WHERE id=?", (row_id,))
        counts["removed"] += 1
    for row_id, (values, inputs) in wanted.items():
        current = existing.get(row_id)
        stored_inputs = tuple(tuple(row) for row in connection.execute(
            """SELECT input_kind, input_id, input_day, input_value, input_unit
               FROM device_calculation_inputs WHERE row_id=? ORDER BY input_kind""", (row_id,)
        ))
        changed = stored_inputs != tuple(sorted(inputs))
        if current is None:
            connection.execute(
                f"INSERT INTO device_metric_days(id, {', '.join(_COLUMNS)}, created_at) VALUES ({', '.join('?' * (len(_COLUMNS) + 2))})",
                (row_id, *values, utc_now()),
            )
            counts["added"] += 1
        elif tuple(current[column] for column in _COLUMNS) != values or changed:
            connection.execute(
                f"UPDATE device_metric_days SET {', '.join(f'{column}=?' for column in _COLUMNS)} WHERE id=?",
                (*values, row_id),
            )
            counts["updated"] += 1
        else:
            continue
        changed_owners.add(str(values[0]))
        connection.execute("DELETE FROM device_calculation_inputs WHERE row_id=?", (row_id,))
        connection.executemany(
            """INSERT INTO device_calculation_inputs(row_id, input_kind, input_id, input_day, input_value, input_unit)
               VALUES (?, ?, ?, ?, ?, ?)""", [(row_id, *item) for item in inputs],
        )
    for owner in changed_owners:
        connection.execute(
            """INSERT INTO device_calculation_revisions(owner_user_id,revision) VALUES (?,1)
               ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1""", (owner,)
        )
    return counts
