"""Possible diagnoses: patterns in a person's results that point to an ICD-10 code.

The matrix adds no thresholds of its own. It only combines the bands that
``data/reference_library.json`` publishes, matched by their labels.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from anamna.db import utc_now

from . import reference

#: A result older than this raises nothing.
RECENT_DAYS = 730

#: One alternative: (metric name, band labels). A card shows it when its band is one of the labels.
Alternative = tuple[str, tuple[str, ...]]
#: Alternatives of one group: the group holds when any of them is shown.
Group = tuple[Alternative, ...]


@dataclass(frozen=True)
class Rule:
    """A pattern of results and the code it suggests."""

    id: str
    code: str
    doctor: str
    all: tuple[Group, ...]
    none: tuple[Group, ...] = ()
    needs: tuple[tuple[str, ...], ...] = ()
    covered_by: tuple[str, ...] = ()


_CHOL: Group = (
    (
        "LDL cholesterol",
        (
            "Above the European laboratory flagging cut-point",
            "Severe hypercholesterolaemia",
            "High (US classification)",
            "Very high (US classification)",
        ),
    ),
    (
        "Total cholesterol",
        (
            "At or above the European flagging cut-point",
            "Severe hypercholesterolaemia",
            "High (US classification)",
        ),
    ),
)
_TG: Group = (("Triglycerides", ("High", "Very high", "Severe: pancreatitis risk")),)
_PREDIABETES: Group = (
    (
        "Blood glucose",
        (
            "Prediabetes - impaired fasting glucose (ADA / Ukraine)",
            "Impaired fasting glucose (WHO)",
            "High risk of type 2 diabetes - non-diabetic hyperglycaemia (NICE, UK)",
        ),
    ),
    (
        "Hemoglobin A1c",
        (
            "Prediabetes range (ADA / Ukraine)",
            "High risk of type 2 diabetes (NICE, UK, 42-47 mmol/mol)",
        ),
    ),
)
_DIABETES: Group = (
    (
        "Blood glucose",
        (
            "Diabetes range, fasting (ADA / Ukraine)",
            "Diabetes range, fasting (WHO)",
            "Possible type 2 diabetes - repeat test required (NICE, UK)",
            "Diabetes range for a random (non-fasting) sample (ADA / WHO / Ukraine)",
        ),
    ),
    (
        "Hemoglobin A1c",
        (
            "Diabetes range (ADA / Ukraine)",
            "Diabetes range (WHO)",
            "Possible type 2 diabetes - repeat test required (NICE, UK, >=48 mmol/mol)",
        ),
    ),
)
_ANAEMIA: Group = (
    (
        "Hemoglobin",
        (
            "Severe anaemia (WHO)",
            "Moderate anaemia (WHO)",
            "Mild anaemia (WHO)",
            "Mild anaemia (WHO), below the Nordic reference interval",
        ),
    ),
)
_FERRITIN_LOW: Group = (
    (
        "Ferritin",
        (
            "Iron deficiency (apparently healthy adults)",
            "Iron deficiency in the presence of infection or inflammation",
        ),
    ),
)
_PRESSURE: tuple[str, ...] = (
    "Stage 2 hypertension (US, AHA/ACC)",
    "Hypertensive crisis (US, AHA/ACC)",
    "Grade 1 hypertension (EU, ESH)",
    "Grade 2 hypertension (EU, ESH)",
    "Grade 3 hypertension (EU, ESH)",
)
_TSH_HIGH: tuple[str, ...] = (
    "Mildly elevated",
    "Markedly elevated",
    "Mildly elevated (age 80 and over)",
    "Markedly elevated (age 80 and over)",
)
_TSH_LOW: tuple[str, ...] = ("Below reference interval", "Below reference interval (age 80 and over)")

RULES: tuple[Rule, ...] = (
    Rule("lipid_mixed", "E78.2", "cardiologist", all=(_CHOL, _TG), covered_by=("E78",)),
    Rule(
        "lipid_cholesterol",
        "E78.0",
        "cardiologist",
        all=(_CHOL,),
        none=(_TG,),
        needs=(("Triglycerides",),),
        covered_by=("E78",),
    ),
    Rule(
        "lipid_triglycerides",
        "E78.1",
        "cardiologist",
        all=(_TG,),
        none=(_CHOL,),
        needs=(("Total cholesterol", "LDL cholesterol"),),
        covered_by=("E78",),
    ),
    Rule(
        "glucose_intermediate",
        "E09.9",
        "endocrinologist",
        all=(_PREDIABETES,),
        none=(_DIABETES,),
        covered_by=("E09", "E10", "E11", "E12", "E13", "E14", "R73"),
    ),
    Rule(
        "diabetes_range",
        "E14.9",
        "endocrinologist",
        all=(_DIABETES,),
        covered_by=("E10", "E11", "E12", "E13", "E14"),
    ),
    Rule("anaemia_iron", "D50.9", "family", all=(_ANAEMIA, _FERRITIN_LOW), covered_by=("D50",)),
    Rule(
        "iron_deficiency",
        "E61.1",
        "family",
        all=(_FERRITIN_LOW,),
        none=(_ANAEMIA,),
        needs=(("Hemoglobin",),),
        covered_by=("E61.1", "D50"),
    ),
    Rule(
        "anaemia_unspecified",
        "D64.9",
        "family",
        all=(_ANAEMIA,),
        none=(_FERRITIN_LOW,),
        covered_by=("D5", "D60", "D61", "D62", "D63", "D64"),
    ),
    Rule(
        "iron_overload",
        "E83.1",
        "family",
        all=(
            (
                (
                    "Ferritin",
                    (
                        "Possible risk of iron overload (men and non-menstruating women)",
                        "Possible risk of iron overload (women)",
                        "Possible risk of iron overload in the presence of illness",
                    ),
                ),
            ),
        ),
        covered_by=("E83.1",),
    ),
    Rule(
        "hypothyroid",
        "E03.9",
        "endocrinologist",
        all=((("Thyroid stimulating hormone", _TSH_HIGH),),),
        covered_by=("E02", "E03", "E06"),
    ),
    Rule(
        "thyrotoxicosis",
        "E05.9",
        "endocrinologist",
        all=((("Thyroid stimulating hormone", _TSH_LOW),),),
        covered_by=("E05",),
    ),
    Rule(
        "hyperuricaemia",
        "E79.0",
        "family",
        all=(
            (
                (
                    "Uric acid",
                    (
                        "405 µmol/L (6.8 mg/dl) and above - urate above the saturation point of monosodium urate",
                    ),
                ),
            ),
        ),
        covered_by=("E79", "M10"),
    ),
    Rule(
        "vitamin_d",
        "E55.9",
        "family",
        all=(
            (("25-hydroxyvitamin D", ("Deficient (US Food and Nutrition Board / NASEM)",)),),
        ),
        covered_by=("E55",),
    ),
    Rule(
        "b12_deficiency",
        "E53.8",
        "family",
        all=((("Vitamin B12", ("Subnormal, consistent with deficiency",)),),),
        covered_by=("E53.8", "D51"),
    ),
    Rule(
        "folate_deficiency",
        "E53.8",
        "family",
        all=((("Folate, serum", ("Deficiency",)),),),
        covered_by=("E53.8", "D52"),
    ),
    Rule(
        "hypertension",
        "I10",
        "family",
        all=((("Systolic blood pressure", _PRESSURE), ("Diastolic blood pressure", _PRESSURE)),),
        covered_by=("I10", "I11", "I12", "I13", "I15"),
    ),
    Rule(
        "obesity",
        "E66",
        "family",
        all=(
            (
                (
                    "Body mass index",
                    ("Obesity class I", "Obesity class II", "Obesity class III"),
                ),
            ),
        ),
        covered_by=("E66",),
    ),
    Rule(
        "ckd",
        "N18.9",
        "nephrologist",
        all=(
            (
                (
                    "Estimated glomerular filtration rate (CKD-EPI 2021)",
                    (
                        "G3a: mildly to moderately decreased",
                        "G3b: moderately to severely decreased",
                        "G4: severely decreased",
                        "G5: kidney failure",
                    ),
                ),
            ),
        ),
        covered_by=("N18", "N19"),
    ),
    Rule(
        "transaminases",
        "R74.0",
        "gastroenterologist",
        all=(
            (
                (
                    "Alanine aminotransferase",
                    (
                        "Above healthy range (ACG / EASL-EASD-EASO)",
                        "Above traditional ULN (EASL hepatitis B)",
                    ),
                ),
            ),
        ),
        covered_by=("R74", "K7"),
    ),
    Rule(
        "lvh",
        "I51.7",
        "cardiologist",
        all=(
            (
                (
                    "Left ventricular mass index",
                    (
                        "Left ventricular hypertrophy (above 95 g/m²)",
                        "Left ventricular hypertrophy (above 115 g/m²)",
                    ),
                ),
            ),
        ),
        covered_by=("I51.7", "I11", "I13", "I42"),
    ),
    Rule(
        "thrombocytopenia",
        "D69.6",
        "haematologist",
        all=(
            (
                (
                    "Platelet count",
                    (
                        "Thrombocytopenia below the ASH ITP diagnostic threshold",
                        "Prophylactic platelet transfusion threshold (NICE NG24)",
                        "Transfusion threshold with clinically significant bleeding (NICE NG24)",
                    ),
                ),
            ),
        ),
        covered_by=("D69",),
    ),
    Rule(
        "eosinophilia",
        "D72.1",
        "family",
        all=(
            (
                (
                    "Eosinophils, absolute",
                    (
                        "Mild eosinophilia",
                        "Moderate hypereosinophilia",
                        "Severe hypereosinophilia",
                    ),
                ),
            ),
        ),
        covered_by=("D72.1",),
    ),
    Rule(
        "hyponatraemia",
        "E87.1",
        "family",
        all=((("Sodium", ("Severe hyponatraemia", "Hyponatraemia")),),),
        covered_by=("E87.1",),
    ),
    Rule(
        "hypokalaemia",
        "E87.6",
        "family",
        all=((("Potassium", ("Hypokalaemia",)),),),
        covered_by=("E87.6",),
    ),
    Rule(
        "hyperkalaemia",
        "E87.5",
        "family",
        all=((("Potassium", ("Hyperkalaemia",)),),),
        covered_by=("E87.5",),
    ),
)

#: Code prefixes -> metrics shown on a diagnosis page as "results to watch". First match wins.
WATCH: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("E78",),
        (
            "Total cholesterol",
            "LDL cholesterol",
            "HDL cholesterol",
            "Non-HDL cholesterol",
            "Triglycerides",
            "Apolipoprotein B",
            "Lipoprotein(a)",
        ),
    ),
    (
        ("E09", "E10", "E11", "E12", "E13", "E14", "R73"),
        ("Blood glucose", "Hemoglobin A1c"),
    ),
    (
        ("I10", "I11", "I12", "I13", "I15"),
        (
            "Systolic blood pressure",
            "Diastolic blood pressure",
            "Left ventricular mass index",
            "Estimated glomerular filtration rate (CKD-EPI 2021)",
            "Potassium",
        ),
    ),
    (
        ("D50", "D51", "D52", "D53", "D64", "E61.1"),
        (
            "Hemoglobin",
            "Ferritin",
            "Mean corpuscular volume",
            "Vitamin B12",
            "Folate, serum",
        ),
    ),
    (
        ("E02", "E03", "E05", "E06"),
        (
            "Thyroid stimulating hormone",
            "Free thyroxine",
            "Free triiodothyronine",
            "Thyroid peroxidase antibodies",
        ),
    ),
    (("E79", "M10"), ("Uric acid",)),
    (
        ("N18", "N19"),
        (
            "Estimated glomerular filtration rate (CKD-EPI 2021)",
            "Creatinine",
            "Potassium",
        ),
    ),
    (
        ("K7", "R74"),
        (
            "Alanine aminotransferase",
            "Aspartate aminotransferase",
            "Gamma-glutamyl transferase",
            "Total bilirubin",
        ),
    ),
    (("E66",), ("Body mass index", "Blood glucose", "Hemoglobin A1c", "Triglycerides", "HDL cholesterol")),
    (("E55",), ("25-hydroxyvitamin D", "Calcium, total")),
    (("E53",), ("Vitamin B12", "Folate, serum")),
    (("E83.1",), ("Ferritin", "Serum iron")),
    (
        ("I51.7", "I42"),
        ("Left ventricular mass index", "Systolic blood pressure", "Diastolic blood pressure"),
    ),
    (("D69",), ("Platelet count",)),
    (("E87",), ("Sodium", "Potassium")),
)


def watch_metrics(code: str) -> tuple[str, ...]:
    """The metrics to watch for a diagnosis code; () when none is listed."""
    for prefixes, metrics in WATCH:
        if code.startswith(prefixes):
            return metrics
    return ()


def _recent_day(card: dict, today: date) -> str | None:
    """The card's ISO date when it is within RECENT_DAYS of today, else None."""
    text = str(card.get("latest_date") or "")[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return text if today - day <= timedelta(days=RECENT_DAYS) else None


def _shown(card: dict, labels: tuple[str, ...]) -> dict | None:
    """The verdict, or one of its authority positions, whose band is one of the labels."""
    verdict = card.get("verdict") or {}
    for source in (verdict, *(verdict.get("authority_positions") or [])):
        if source.get("band_label") in labels:
            return source
    return None


def _group_evidence(recent: Sequence[tuple[dict, str]], group: Group) -> list[dict]:
    """One evidence dict per recent card that shows an alternative of the group."""
    found: list[dict] = []
    for card, day in recent:
        for metric, labels in group:
            if card.get("name") != metric:
                continue
            hit = _shown(card, labels)
            if hit is not None:
                found.append(
                    {
                        "metric": metric,
                        "metric_id": card.get("id"),
                        "url": card.get("url"),
                        "value": card.get("value_text"),
                        "unit": card.get("unit"),
                        "date": day,
                        "band": hit.get("band_label"),
                        "source_id": hit.get("source_id"),
                        "source_name": hit.get("source_name"),
                        "source_url": hit.get("source_url"),
                    }
                )
                break
    return found


def _has_metric(recent: Sequence[tuple[dict, str]], names: tuple[str, ...]) -> bool:
    return any(card.get("name") in names for card, _ in recent)


def _evidence_for(recent: Sequence[tuple[dict, str]], rule: Rule) -> list[dict] | None:
    """The evidence of a rule that holds, or None when it does not."""
    evidence: list[dict] = []
    for group in rule.all:
        found = _group_evidence(recent, group)
        if not found:
            return None
        evidence.extend(found)
    if any(_group_evidence(recent, group) for group in rule.none):
        return None
    if not all(_has_metric(recent, names) for names in rule.needs):
        return None
    return evidence


def matches(cards: list[dict], *, today: date) -> dict[str, list[dict]]:
    """Rule id -> evidence, for every rule that holds on these cards."""
    recent = [(card, day) for card in cards if (day := _recent_day(card, today))]
    held: dict[str, list[dict]] = {}
    for rule in RULES:
        evidence = _evidence_for(recent, rule)
        if evidence is not None:
            held[rule.id] = evidence
    return held


def _active_codes(connection, owner_id: str) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT code FROM diagnoses WHERE owner_user_id=? AND status='active' AND code<>''",
            (owner_id,),
        )
    ]


def _diagnosis_active(connection, owner_id: str, diagnosis_id: str | None) -> bool:
    """Whether the diagnosis that confirmed a possibility is still on the record and active."""
    row = connection.execute(
        "SELECT status FROM diagnoses WHERE id = ? AND owner_user_id = ?", (diagnosis_id, owner_id),
    ).fetchone()
    return row is not None and row[0] == "active"


def refresh(connection, owner_id: str, cards: list[dict], *, today: date) -> dict:
    """Bring diagnosis_suspicions in line with the cards. Does not commit.

    A 'confirmed' row whose diagnosis was deleted or is no longer active is treated as
    'cleared': it reopens when the rule holds and is not covered, and otherwise becomes 'cleared'.

    Returns {"opened": n, "cleared": n}.
    """
    held = matches(cards, today=today)
    active = _active_codes(connection, owner_id)
    now = utc_now()
    opened = cleared = 0
    for rule in RULES:
        covered = any(code.startswith(prefix) for code in active for prefix in rule.covered_by)
        row = connection.execute(
            "SELECT id, state, diagnosis_id FROM diagnosis_suspicions WHERE owner_user_id=? AND rule_id=?",
            (owner_id, rule.id),
        ).fetchone()
        state = row[1] if row is not None else None
        if state == "confirmed" and not _diagnosis_active(connection, owner_id, row[2]):
            if rule.id in held and not covered:
                connection.execute(
                    """UPDATE diagnosis_suspicions
                       SET state='open', diagnosis_id=NULL, evidence_json=?, last_seen_at=?, state_changed_at=?
                       WHERE id=?""",
                    (json.dumps(held[rule.id], ensure_ascii=False), now, now, row[0]),
                )
                opened += 1
            else:
                connection.execute(
                    "UPDATE diagnosis_suspicions SET state='cleared', diagnosis_id=NULL, state_changed_at=? WHERE id=?",
                    (now, row[0]),
                )
                cleared += 1
            continue
        if rule.id in held and not covered:
            evidence = json.dumps(held[rule.id], ensure_ascii=False)
            if row is None:
                connection.execute(
                    """INSERT INTO diagnosis_suspicions(
                           id, owner_user_id, rule_id, code, state, evidence_json,
                           first_seen_at, last_seen_at, state_changed_at
                       ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), owner_id, rule.id, rule.code, evidence, now, now, now),
                )
                opened += 1
            elif state == "cleared":
                connection.execute(
                    """UPDATE diagnosis_suspicions
                       SET state='open', evidence_json=?, last_seen_at=?, state_changed_at=?
                       WHERE id=?""",
                    (evidence, now, now, row[0]),
                )
                opened += 1
            elif state in ("open", "muted"):
                connection.execute(
                    "UPDATE diagnosis_suspicions SET evidence_json=?, last_seen_at=? WHERE id=?",
                    (evidence, now, row[0]),
                )
        elif state == "open":
            connection.execute(
                "UPDATE diagnosis_suspicions SET state='cleared', state_changed_at=? WHERE id=?",
                (now, row[0]),
            )
            cleared += 1
    return {"opened": opened, "cleared": cleared}


def listing(connection, owner_id: str, states: tuple[str, ...] = ("open",)) -> list[dict]:
    """The owner's suspicions in the given states, with decoded evidence."""
    rules = {rule.id: rule for rule in RULES}
    marks = ",".join("?" for _ in states)
    rows = connection.execute(
        f"""SELECT id, rule_id, code, state, evidence_json, first_seen_at, last_seen_at
            FROM diagnosis_suspicions
            WHERE owner_user_id=? AND state IN ({marks})
            ORDER BY first_seen_at, id""",
        (owner_id, *states),
    ).fetchall()
    result = []
    for row in rows:
        rule = rules.get(row[1])
        if rule is None:
            continue
        result.append(
            {
                "id": row[0],
                "rule_id": row[1],
                "code": row[2],
                "state": row[3],
                "evidence": json.loads(row[4]),
                "first_seen_at": row[5],
                "last_seen_at": row[6],
                "doctor": rule.doctor,
            }
        )
    return result


def band_text(connection, metric: str, band: str, locale: str) -> str:
    """The band's label in the locale, from the curated rule the evidence names.

    The stored English label when the rule no longer exists.
    """
    row = connection.execute(
        """SELECT r.* FROM curated_reference_rules r
           JOIN concepts k ON k.id = r.concept_id
           WHERE k.canonical_name = ? AND r.label = ? LIMIT 1""",
        (metric, band),
    ).fetchone()
    if row is None or not hasattr(row, "keys"):
        return band
    return reference.rule_label(row, locale)


def _move(connection, owner_id: str, suspicion_id: str, source: str, target: str) -> bool:
    cursor = connection.execute(
        """UPDATE diagnosis_suspicions SET state=?, state_changed_at=?
           WHERE id=? AND owner_user_id=? AND state=?""",
        (target, utc_now(), suspicion_id, owner_id, source),
    )
    return cursor.rowcount == 1


def mute(connection, owner_id: str, suspicion_id: str) -> bool:
    """Ban a possible diagnosis from the list until it is restored."""
    return _move(connection, owner_id, suspicion_id, "open", "muted")


def restore(connection, owner_id: str, suspicion_id: str) -> bool:
    """Bring a muted possible diagnosis back to the list."""
    return _move(connection, owner_id, suspicion_id, "muted", "open")


def confirm(connection, owner_id: str, suspicion_id: str, diagnosis_id: str) -> bool:
    """Mark an open possible diagnosis as confirmed by a diagnosis of the record."""
    cursor = connection.execute(
        """UPDATE diagnosis_suspicions
           SET state='confirmed', diagnosis_id=?, state_changed_at=?
           WHERE id=? AND owner_user_id=? AND state='open'""",
        (diagnosis_id, utc_now(), suspicion_id, owner_id),
    )
    return cursor.rowcount == 1
