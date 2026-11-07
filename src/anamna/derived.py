"""Values the record calculates from other stored values.

One so far: the estimated glomerular filtration rate.  KDIGO 2024 says kidney
function is assessed with an estimating equation rather than serum creatinine
alone, and no laboratory in this record prints one -- so every creatinine
reading was a number nobody could act on.

The equation is CKD-EPI 2021 (Inker LA et al., N Engl J Med 2021;385:1737-49),
the race-free refit KDIGO and the US National Kidney Foundation recommend:

    eGFR = 142 × min(Scr/κ, 1)^α × max(Scr/κ, 1)^−1.200 × 0.9938^age × 1.012 [female]
    κ = 0.7 (female) / 0.9 (male),  α = −0.241 (female) / −0.302 (male),  Scr in mg/dL

A derived row is an ordinary observation, so the metric page, its chart, the
search and the document it came from all show it with no special case.  It
carries the creatinine's document, page, date and evidence line -- the printed
line it was calculated from -- and ``extraction_method`` names the equation.
It is calculated only from a creatinine a person has verified or corrected,
and then carries that verification: arithmetic on a confirmed value is not a
new extraction waiting for review, and an eGFR worked out from a number the
parser may have misread would put a kidney-function figure nobody checked in
front of the patient -- and a second value on every review list.
"""

from __future__ import annotations

import sqlite3
import uuid

from .config import ID_NAMESPACE_PREFIX
from .db import utc_now
from .health import age_on
from .ingest.concepts import stable_concept_id
from .ingest.parsers import PARSER_VERSION
from .reference import canonical_unit

DERIVED_EGFR_METHOD = "derived_ckd_epi_2021"
EGFR_CONCEPT_ID = stable_concept_id("Estimated glomerular filtration rate (CKD-EPI 2021)")
EGFR_UNIT = "mL/min/1.73m²"
EGFR_LABEL = "eGFR (CKD-EPI 2021)"
CREATININE_CONCEPT_ID = stable_concept_id("Creatinine")
#: µmol/L per mg/dL of creatinine (molar mass 113.12 g/mol), the factor KDIGO uses.
CREATININE_UMOL_PER_MG_DL = 88.4
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"{ID_NAMESPACE_PREFIX}/derived/egfr-ckd-epi-2021")


def ckd_epi_2021(creatinine_mg_dl: float, age: float, sex: str) -> float:
    """eGFR in mL/min/1.73 m² for an adult; ``sex`` is "female" or "male"."""
    female = sex == "female"
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = creatinine_mg_dl / kappa
    egfr = 142 * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** -1.200 * 0.9938**age
    return egfr * 1.012 if female else egfr


def _creatinine_mg_dl(value: float, unit: str | None) -> float | None:
    folded = canonical_unit(unit)
    if folded in {"umol/l", ""}:
        # Unitless creatinine is the µmol/L every laboratory here prints; the
        # concept's own unit.  A value in that range cannot be mg/dL.
        return value / CREATININE_UMOL_PER_MG_DL if value > 20 else None
    if folded == "mg/dl":
        return value
    if folded == "mmol/l":
        return value * 1000 / CREATININE_UMOL_PER_MG_DL
    return None


def _wanted(connection: sqlite3.Connection) -> dict[str, tuple]:
    """Every eGFR the current record supports, keyed by its derived row id."""
    rows = connection.execute(
        """SELECT o.*, p.date_of_birth, p.sex_at_birth
             FROM observations o JOIN patients p ON p.id = o.patient_id
            WHERE o.concept_id = ? AND o.value_numeric IS NOT NULL
              AND COALESCE(o.comparator, '') = '' AND o.observed_at IS NOT NULL
              AND o.verification_status IN ('verified', 'corrected')
              AND p.sex_at_birth IN ('female', 'male') AND p.date_of_birth IS NOT NULL""",
        (CREATININE_CONCEPT_ID,),
    ).fetchall()
    # A report that printed its own eGFR keeps it; a second, calculated one
    # beside it would be the same measurement twice.
    printed = {
        (row[0], row[1])
        for row in connection.execute(
            """SELECT COALESCE(report_id, document_id), substr(observed_at, 1, 10) FROM observations
                WHERE concept_id = ? AND extraction_method <> ?
                  AND verification_status <> 'rejected'""",
            (EGFR_CONCEPT_ID, DERIVED_EGFR_METHOD),
        )
    }
    wanted: dict[str, tuple] = {}
    for row in rows:
        age = age_on(row["date_of_birth"], row["observed_at"])
        mg_dl = _creatinine_mg_dl(float(row["value_numeric"]), row["unit_raw"])
        # CKD-EPI is validated for adults only; children need a different equation.
        if age is None or age < 18 or not mg_dl:
            continue
        if (row["report_id"] or row["document_id"], str(row["observed_at"])[:10]) in printed:
            continue
        status = "verified"
        wanted[str(uuid.uuid5(_NAMESPACE, str(row["id"])))] = (
            row["owner_user_id"], row["patient_id"], row["document_id"], row["page_number"],
            EGFR_CONCEPT_ID, EGFR_LABEL, "numeric",
            float(round(ckd_epi_2021(mg_dl, age, str(row["sex_at_birth"])))),
            EGFR_UNIT, EGFR_UNIT, row["observed_at"], status, DERIVED_EGFR_METHOD,
            row["confidence"], row["evidence_text"], row["evidence_bbox_json"], PARSER_VERSION,
            row["report_id"], row["entry_source"], row["entered_by_user_id"],
        )
    return wanted


_COLUMNS = (
    "owner_user_id", "patient_id", "document_id", "page_number", "concept_id", "raw_name",
    "value_type", "value_numeric", "unit_raw", "unit_canonical", "observed_at",
    "verification_status", "extraction_method", "confidence", "evidence_text",
    "evidence_bbox_json", "parser_version", "report_id", "entry_source", "entered_by_user_id",
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
    if connection.execute("SELECT 1 FROM concepts WHERE id = ?", (EGFR_CONCEPT_ID,)).fetchone() is None:
        return counts  # catalogue not seeded yet; start-up seeds it, then calls this again
    wanted = _wanted(connection)
    existing = {
        str(row["id"]): row
        for row in connection.execute(
            "SELECT * FROM observations WHERE extraction_method = ?", (DERIVED_EGFR_METHOD,)
        )
    }
    for row_id in existing.keys() - wanted.keys():
        connection.execute("DELETE FROM observations WHERE id = ?", (row_id,))
        counts["removed"] += 1
    for row_id, values in wanted.items():
        current = existing.get(row_id)
        if current is not None:
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
    return counts
