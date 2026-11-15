"""Refresh sourced calculations from independently confirmed observations.

The CKD-EPI 2021 equation estimates adult eGFR; ``lab_calculations`` supplies
same-sample arithmetic for blood counts and chemistry. New or changed outputs
stay provisional. Reported results take precedence and a person's review of
an unchanged calculation is retained. Device calculations share the refresh
hook, but keep their own device-day provenance and dependency records.
"""

from __future__ import annotations

import sqlite3
import uuid
import math
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .config import ID_NAMESPACE_PREFIX
from .db import utc_now
from .health import PREGNANCY_DAYS, age_on
from .ingest.concepts import stable_concept_id, specimen_family
from .ingest.parsers import PARSER_VERSION
from .reference import canonical_unit

DERIVED_EGFR_METHOD = "derived_ckd_epi_2021"
EGFR_CONCEPT_ID = stable_concept_id("Estimated glomerular filtration rate (CKD-EPI 2021)")
EGFR_REPORTED_CONCEPT_ID = stable_concept_id("Estimated glomerular filtration rate, reported")
EGFR_UNIT = "mL/min/1.73m²"
EGFR_LABEL = "eGFR (CKD-EPI 2021)"
CREATININE_CONCEPT_ID = stable_concept_id("Creatinine")
#: µmol/L per mg/dL of creatinine (molar mass 113.12 g/mol), the factor KDIGO uses.
CREATININE_UMOL_PER_MG_DL = 88.4
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"{ID_NAMESPACE_PREFIX}/derived/egfr-ckd-epi-2021")


def ckd_epi_2021(creatinine_mg_dl: float, age: float, sex: str) -> float:
    """eGFR in mL/min/1.73 m² for an adult; ``sex`` is "female" or "male"."""
    if (sex not in {"female", "male"} or not math.isfinite(creatinine_mg_dl)
            or creatinine_mg_dl <= 0 or not math.isfinite(age) or age < 18):
        raise ValueError("Unsupported CKD-EPI 2021 input")
    female = sex == "female"
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = creatinine_mg_dl / kappa
    egfr = 142 * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** -1.200 * 0.9938**age
    return egfr * 1.012 if female else egfr


def _creatinine_mg_dl(value: float, unit: str | None) -> float | None:
    folded = canonical_unit(unit)
    if not math.isfinite(value) or value <= 0:
        return None
    if folded == "umol/l":
        return value / CREATININE_UMOL_PER_MG_DL
    if folded == "mg/dl":
        return value
    if folded == "mg/l":
        return value / 10
    if folded == "g/l":
        return value * 100
    if folded == "mmol/l":
        return value * 1000 / CREATININE_UMOL_PER_MG_DL
    return None


def _wanted(connection: sqlite3.Connection) -> dict[str, tuple]:
    """Every eGFR the current record supports, keyed by its derived row id."""
    from .devices.units import finite_number
    from .lab_calculations import _sample_may_match

    rows = connection.execute(
        """SELECT o.*, p.date_of_birth, p.sex_at_birth, p.pregnancy_due_date
             FROM observations o JOIN patients p ON p.id = o.patient_id AND p.owner_user_id=o.owner_user_id
             LEFT JOIN documents d ON d.id=o.document_id
             LEFT JOIN reports r ON r.id=o.report_id
             LEFT JOIN documents rd ON rd.id=r.document_id
            WHERE o.concept_id = ? AND o.observed_at IS NOT NULL
              AND o.verification_status <> 'rejected'
              AND substr(o.extraction_method, 1, 8) <> 'derived_'
              AND TRIM(COALESCE(NULLIF(o.report_id, ''), o.document_id, '')) <> ''
              AND (o.document_id IS NULL OR (d.owner_user_id=o.owner_user_id AND d.patient_id=o.patient_id))
              AND (o.report_id IS NULL OR (r.owner_user_id=o.owner_user_id AND r.patient_id=o.patient_id
                   AND rd.owner_user_id=o.owner_user_id AND rd.patient_id=o.patient_id
                   AND (o.document_id IS NULL OR r.document_id=o.document_id)))
              AND p.sex_at_birth IN ('female', 'male') AND p.date_of_birth IS NOT NULL""",
        (CREATININE_CONCEPT_ID,),
    ).fetchall()
    # A report that printed its own eGFR keeps it; a second, calculated one
    # beside it would be the same measurement twice.
    printed = [
        (row["owner_user_id"], row["patient_id"],
         ("report", row["report_id"]) if row["report_id"] else ("document", row["document_id"]),
         row["observed_at"], (row["specimen"] or "").strip().casefold(), row["sample_condition"])
        for row in connection.execute(
            """SELECT o.owner_user_id, o.patient_id, o.report_id, o.document_id, o.observed_at,
                      o.specimen, o.sample_condition FROM observations o
                JOIN patients p ON p.id=o.patient_id AND p.owner_user_id=o.owner_user_id
                LEFT JOIN documents d ON d.id=o.document_id
                LEFT JOIN reports r ON r.id=o.report_id
                LEFT JOIN documents rd ON rd.id=r.document_id
                WHERE o.concept_id IN (?, ?) AND o.extraction_method <> ?
                  AND o.verification_status <> 'rejected'
                  AND (o.document_id IS NULL OR (d.owner_user_id=o.owner_user_id AND d.patient_id=o.patient_id))
                  AND (o.report_id IS NULL OR (r.owner_user_id=o.owner_user_id AND r.patient_id=o.patient_id
                       AND rd.owner_user_id=o.owner_user_id AND rd.patient_id=o.patient_id
                       AND (o.document_id IS NULL OR r.document_id=o.document_id)))""",
            (EGFR_CONCEPT_ID, EGFR_REPORTED_CONCEPT_ID, DERIVED_EGFR_METHOD),
        )
    ]
    printed_by_source = defaultdict(list)
    for target in printed:
        printed_by_source[target[:3]].append(target)
    wanted: dict[str, tuple] = {}
    def sample(row):
        source = ("report", row["report_id"]) if row["report_id"] else ("document", row["document_id"])
        return (row["owner_user_id"], row["patient_id"], source,
                row["observed_at"], (row["specimen"] or "").strip().casefold(), row["sample_condition"])

    samples = Counter(sample(row) for row in rows)
    for row in rows:
        try:
            observed_at = str(row["observed_at"])
            date.fromisoformat(observed_at[:10])
            if len(observed_at) != 10:
                datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if row["verification_status"] not in {"verified", "corrected"}:
            continue
        if row["comparator"] or row["value_numeric"] is None:
            continue
        if specimen_family(row["specimen"]) not in (None, "hematology"):
            continue
        if samples[sample(row)] != 1:
            continue
        try:
            born = date.fromisoformat(str(row["date_of_birth"]))
        except ValueError:
            continue
        age = age_on(born.isoformat(), row["observed_at"])
        number = finite_number(row["value_numeric"])
        mg_dl = _creatinine_mg_dl(number, row["unit_raw"]) if number is not None else None
        # CKD-EPI is validated for adults only; children need a different equation.
        if age is None or age < 18 or not mg_dl:
            continue
        # Use the same recorded-pregnancy window as the application's sample
        # facts. eGFR equations are not valid in pregnancy (UK Kidney 4.1.1;
        # NICE NG3 1.3.30); preserve reported values, but do not reconstruct one.
        try:
            due = date.fromisoformat(str(row["pregnancy_due_date"]))
        except ValueError:
            due = None
        taken = date.fromisoformat(observed_at[:10])
        if due is not None and due - timedelta(days=PREGNANCY_DAYS) <= taken <= due:
            continue
        if any(_sample_may_match(sample(row), target) for target in printed_by_source[sample(row)[:3]]):
            continue
        status = "extracted"
        evidence = (f"CKD-EPI 2021: Scr={mg_dl:g} mg/dL; age={age:g}; "
                    f"sex={row['sex_at_birth']}; date_of_birth={row['date_of_birth']}; "
                    f"input_id={row['id']}; value={row['value_numeric']!r}; "
                    f"unit_raw={row['unit_raw']!r}; unit_canonical={row['unit_canonical']!r}; "
                    f"observed_at={row['observed_at']!r}; specimen={row['specimen']!r}; "
                    f"sample_condition={row['sample_condition']!r}; {row['evidence_text']}")
        wanted[str(uuid.uuid5(_NAMESPACE, str(row["id"])))] = (
            row["owner_user_id"], row["patient_id"], row["document_id"], row["page_number"],
            EGFR_CONCEPT_ID, EGFR_LABEL, "numeric",
            float(round(ckd_epi_2021(mg_dl, age, str(row["sex_at_birth"])))),
            EGFR_UNIT, EGFR_UNIT, row["observed_at"], status, DERIVED_EGFR_METHOD,
            row["confidence"], evidence, row["evidence_bbox_json"], PARSER_VERSION,
            row["report_id"], row["entry_source"], row["entered_by_user_id"],
            row["specimen"], row["sample_condition"],
            json.dumps([
                {"input_kind": "observation", "input_id": row["id"],
                 "input_concept_id": row["concept_id"], "input_name": "Creatinine",
                 "input_value": row["value_numeric"], "input_unit": row["unit_raw"] or row["unit_canonical"],
                 "input_day": row["observed_at"], "document_id": row["document_id"], "report_id": row["report_id"]},
            ], ensure_ascii=False, sort_keys=True),
        )
    return wanted


_COLUMNS = (
    "owner_user_id", "patient_id", "document_id", "page_number", "concept_id", "raw_name",
    "value_type", "value_numeric", "unit_raw", "unit_canonical", "observed_at",
    "verification_status", "extraction_method", "confidence", "evidence_text",
    "evidence_bbox_json", "parser_version", "report_id", "entry_source", "entered_by_user_id",
    "specimen", "sample_condition", "calculation_inputs_json",
)


def refresh_derived_observations(connection: sqlite3.Connection) -> dict[str, int]:
    """Bring every derived row in line with its inputs; idempotent.

    Runs after ingest, re-read, on start-up and after any request that changes
    the record, so a corrected creatinine, a changed date of birth or a
    verification is reflected without anyone remembering to recalculate.  A
    derived row a person has since corrected (its method is no longer this
    one) is theirs and is left alone.
    """
    counts = {"added": 0, "updated": 0, "removed": 0}
    from .devices.calculations import refresh_device_calculations

    if connection.execute("SELECT 1 FROM concepts WHERE id = ?", (EGFR_CONCEPT_ID,)).fetchone() is None:
        return counts  # catalogue not seeded yet; start-up seeds it, then calls this again
    from .lab_calculations import DERIVED_LAB_METHODS, wanted_lab_observations

    wanted = {**_wanted(connection), **wanted_lab_observations(connection)}
    methods = (DERIVED_EGFR_METHOD, *sorted(DERIVED_LAB_METHODS))
    existing = {
        str(row["id"]): row
        for row in connection.execute(
            f"SELECT * FROM observations WHERE extraction_method IN ({','.join('?' for _ in methods)})", methods
        )
    }
    for row_id in existing.keys() - wanted.keys():
        connection.execute("DELETE FROM observations WHERE id = ?", (row_id,))
        counts["removed"] += 1
    for row_id, values in wanted.items():
        current = existing.get(row_id)
        if current is not None:
            # A person's decision survives an unchanged calculation. Changing
            # any input/evidence makes the new result provisional again.
            # A global PDF-parser release is bookkeeping, not a changed
            # equation or input. It must not undo a person's calculation review.
            review_neutral = {"verification_status", "parser_version"}
            unchanged = all(
                current[column] == values[index]
                for index, column in enumerate(_COLUMNS) if column not in review_neutral
            )
            if unchanged:
                continue
            if tuple(current[column] for column in _COLUMNS) != values:
                connection.execute(
                    f"UPDATE observations SET {', '.join(f'{c}=?' for c in _COLUMNS)} WHERE id = ?",
                    (*values, row_id),
                )
                counts["updated"] += 1
            continue
        inserted = connection.execute(
            f"""INSERT OR IGNORE INTO observations(id, {', '.join(_COLUMNS)}, created_at)
                VALUES (?, {', '.join('?' * len(_COLUMNS))}, ?)""",
            (row_id, *values, utc_now()),
        ).rowcount
        counts["added"] += inserted
    # A confirmed same-sample clinical BMI outranks a device fallback. Reconcile
    # device calculations last so either path produces just one derived BMI.
    for key, value in refresh_device_calculations(connection).items():
        counts[key] += value
    return counts
