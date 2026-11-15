"""Conservative arithmetic for missing results from one confirmed laboratory sample.

No equation supplies a reference range. Each output remains provisional and
keeps its inputs' evidence. Printed results always take precedence. Derived
rows never feed another equation, avoiding circular reconstructions of a CBC.

Equations: University of Utah Laboratory Medicine
Curriculum, NHS Cholesterol levels, Sysmex's parameter glossary and the NHLBI
HEIRS Laboratory Test Descriptions. URLs are exposed in ``LAB_CALCULATIONS``
so the reference library and the UI can cite the same publications.
"""

from __future__ import annotations

import math
import json
import sqlite3
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from .config import ID_NAMESPACE_PREFIX
from .devices.units import convert_quantity, finite_number, is_plausible
from .ingest.concepts import stable_concept_id, specimen_family
from .ingest.parsers import PARSER_VERSION
from .reference import canonical_unit, convert_value

UTAH_SOURCE = "https://webpath.med.utah.edu/EXAM/LabMedCurric/LabMed04_01.html"
NHS_SOURCE = "https://www.nhs.uk/conditions/high-cholesterol/cholesterol-levels/"
SYSMEX_SOURCE = "https://www.sysmex-europe.com/academy/library/glossary/"
BILIRUBIN_SOURCE = "https://biolincc.nhlbi.nih.gov/media/studies/heirs/Laboratory%20Test%20Descriptions.pdf"
ALBUMIN_GLOBULIN_SOURCE = "https://www.beaumontlaboratory.com/lab-test-directory/detail?URL=albumin-globulin-ratio&itemID=1"
ATHEROGENIC_SOURCE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9812546/"
BMI_SOURCE = "https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html"
RETICULOCYTE_SOURCE = "https://www.sysmex.gr/academy/kentro-gnoseon/technologies/reticulocyte-count-application-ret/"
RETICULOCYTE_FRACTIONS_SOURCE = "https://www.sysmex.de/fileadmin/media/f101/Xtra/Themenblaetter/Sysmex-White-Paper-Retikulozyt.pdf"

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"{ID_NAMESPACE_PREFIX}/derived/laboratory")


@dataclass(frozen=True)
class Input:
    name: str
    unit: str
    allow_zero: bool = False
    maximum: float | None = None

    @property
    def concept_id(self) -> str:
        return stable_concept_id(self.name)


@dataclass(frozen=True)
class Calculation:
    name: str
    method: str
    unit: str
    inputs: tuple[Input, ...]
    equation: Callable[..., float]
    formula: str
    source_url: str
    maximum: float | None = None
    #: Decimal places the result is stored with: what a laboratory prints for
    #: this quantity.  Four everywhere read a plateletcrit as 0.1771 %, a
    #: precision neither input carries.
    decimals: int = 2

    @property
    def concept_id(self) -> str:
        return stable_concept_id(self.name)


_RBC = Input("Red blood cell count", "10^12/L")
_HGB = Input("Hemoglobin", "g/L")
_HCT = Input("Hematocrit", "%", maximum=100)
_WBC = Input("White blood cell count", "10^9/L")

LAB_CALCULATIONS = [
    Calculation("Mean corpuscular volume", "derived_mcv", "fL", (_HCT, _RBC),
                lambda hct, rbc: hct * 10 / rbc, "MCV = Hct (%) × 10 / RBC (10^12/L)", UTAH_SOURCE,
                decimals=1),
    Calculation("Mean corpuscular hemoglobin", "derived_mch", "pg", (_HGB, _RBC),
                lambda hb, rbc: hb / rbc, "MCH = Hb (g/L) / RBC (10^12/L)", UTAH_SOURCE, decimals=1),
    Calculation("Mean corpuscular hemoglobin concentration", "derived_mchc", "g/L", (_HGB, _HCT),
                lambda hb, hct: hb * 100 / hct, "MCHC = Hb (g/L) × 100 / Hct (%)", UTAH_SOURCE, decimals=1),
    Calculation("Hematocrit", "derived_hematocrit", "%", (_RBC, Input("Mean corpuscular volume", "fL")),
                lambda rbc, mcv: rbc * mcv / 10, "Hct (%) = RBC (10^12/L) × MCV (fL) / 10", UTAH_SOURCE, 100, decimals=1),
    Calculation("Plateletcrit", "derived_plateletcrit", "%",
                (Input("Platelet count", "10^9/L", allow_zero=True), Input("Mean platelet volume", "fL")),
                lambda plt, mpv: plt * mpv / 10000,
                "PCT (%) = PLT (10^9/L) × MPV (fL) / 10000", SYSMEX_SOURCE, 100, decimals=2),
    Calculation("Non-HDL cholesterol", "derived_non_hdl", "mmol/L",
                (Input("Total cholesterol", "mmol/L"), Input("HDL cholesterol", "mmol/L", allow_zero=True)),
                lambda total, hdl: total - hdl, "non-HDL = TC (mmol/L) − HDL (mmol/L)", NHS_SOURCE, decimals=2),
    Calculation("Atherogenic coefficient", "derived_atherogenic_coefficient", "ratio",
                (Input("Total cholesterol", "mmol/L"), Input("HDL cholesterol", "mmol/L")),
                lambda total, hdl: (total - hdl) / hdl,
                "AC = (TC (mmol/L) − HDL (mmol/L)) / HDL (mmol/L)", ATHEROGENIC_SOURCE, decimals=2),
    Calculation("Indirect bilirubin", "derived_indirect_bilirubin", "µmol/L",
                (Input("Total bilirubin", "µmol/L", allow_zero=True),
                 Input("Direct bilirubin", "µmol/L", allow_zero=True)),
                lambda total, direct: total - direct,
                "IBIL = TBIL (µmol/L) − DBIL (µmol/L)", BILIRUBIN_SOURCE, decimals=1),
    Calculation("Albumin to globulin ratio", "derived_albumin_globulin_ratio", "ratio",
                (Input("Albumin", "g/L"), Input("Total protein", "g/L")),
                lambda albumin, total: albumin / (total - albumin) if total > albumin else math.nan,
                "A/G = albumin (g/L) / (total protein (g/L) − albumin (g/L))", ALBUMIN_GLOBULIN_SOURCE, decimals=2),
    Calculation("Globulin, calculated", "derived_globulin", "g/L",
                (Input("Total protein", "g/L"), Input("Albumin", "g/L")),
                lambda total, albumin: total - albumin,
                "Globulin (g/L) = total protein (g/L) − albumin (g/L)", ALBUMIN_GLOBULIN_SOURCE, decimals=1),
    Calculation("Body mass index", "derived_bmi", "kg/m²",
                (Input("Body weight", "kg"), Input("Body height", "cm")),
                lambda weight, height: weight / height ** 2 * 10000,
                "BMI (kg/m²) = weight (kg) / height (cm)² × 10000", BMI_SOURCE, decimals=1),
    Calculation("Reticulocytes, absolute", "derived_reticulocytes_absolute", "10^9/L",
                (_RBC, Input("Reticulocytes", "%", allow_zero=True, maximum=100)),
                lambda rbc, percent: rbc * percent * 10,
                "RET (10^9/L) = RBC (10^12/L) × RET (%) × 10", RETICULOCYTE_SOURCE, decimals=1),
    Calculation("Reticulocytes", "derived_reticulocytes_percentage", "%",
                (_RBC, Input("Reticulocytes, absolute", "10^9/L", allow_zero=True)),
                lambda rbc, absolute: absolute / (rbc * 10),
                "RET (%) = RET (10^9/L) / (RBC (10^12/L) × 10)", RETICULOCYTE_SOURCE, 100, decimals=2),
    Calculation("Immature reticulocyte fraction", "derived_immature_reticulocyte_fraction", "%",
                (Input("Reticulocytes, medium fluorescence fraction", "%", allow_zero=True, maximum=100),
                 Input("Reticulocytes, high fluorescence fraction", "%", allow_zero=True, maximum=100)),
                lambda medium, high: medium + high,
                "IRF (%) = MFR (%) + HFR (%)", RETICULOCYTE_FRACTIONS_SOURCE, 100, decimals=1),
]

# These are distinct analyser populations. Never use a manual differential,
# segmented/band neutrophils or a three-part granulocyte count as neutrophils.
for _name in ("Neutrophils", "Lymphocytes", "Monocytes", "Eosinophils", "Basophils",
              "Immature granulocytes", "Granulocytes", "Mixed white cells"):
    LAB_CALCULATIONS.extend((
        Calculation(f"{_name}, absolute", "derived_differential_absolute", "10^9/L",
                    (_WBC, Input(_name, "%", allow_zero=True, maximum=100)),
                    lambda wbc, percent: wbc * percent / 100,
                    "ABS (10^9/L) = WBC (10^9/L) × % / 100", SYSMEX_SOURCE, decimals=2),
        Calculation(_name, "derived_differential_percentage", "%",
                    (_WBC, Input(f"{_name}, absolute", "10^9/L", allow_zero=True)),
                    lambda wbc, absolute: absolute * 100 / wbc,
                    "% = ABS (10^9/L) × 100 / WBC (10^9/L)", SYSMEX_SOURCE, 100, decimals=1),
    ))

LAB_CALCULATIONS = tuple(LAB_CALCULATIONS)
# The same sample does not establish analytical compatibility. Some laboratory
# methods for direct and total bilirubin cannot validly be subtracted:
# https://pch-pathlab.com/cms/?q=test-rep-dbil . Keep this managed method in the
# registry so refresh retracts earlier provisional outputs, but do not apply it
# without explicit compatible-assay evidence (not currently captured).
INACTIVE_LAB_METHODS = frozenset({"derived_indirect_bilirubin"})
LAB_DERIVED_METHODS = frozenset(calculation.method for calculation in LAB_CALCULATIONS)
DERIVED_LAB_METHODS = LAB_DERIVED_METHODS
_CONCEPT_IDS = frozenset(
    concept_id for calculation in LAB_CALCULATIONS
    for concept_id in (calculation.concept_id, *(item.concept_id for item in calculation.inputs))
)


def _scope(row: sqlite3.Row) -> tuple:
    # A date alone is not evidence of the same sample. Preserve an exact time
    # when one exists, and never borrow between orders, people or specimens.
    source = ("report", row["report_id"]) if row["report_id"] else ("document", row["document_id"])
    return (row["owner_user_id"], row["patient_id"], source,
            row["observed_at"], (row["specimen"] or "").strip().casefold(), row["sample_condition"])


def _sample_may_match(left: tuple, right: tuple) -> bool:
    """Reported targets win only when they could belong to this sample.

    Missing time/specimen/condition remains ambiguous. Explicitly different
    timed draws or specimens in one report are not interchangeable targets.
    """
    if left[:3] != right[:3]:
        return False
    def parsed(value):
        try:
            text = str(value)
            return (datetime.combine(date.fromisoformat(text), datetime.min.time()) if len(text) == 10
                    else datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None
    a, b = parsed(left[3]), parsed(right[3])
    if a is not None and b is not None:
        if a.tzinfo is not None and b.tzinfo is not None:
            if a != b:
                return False
        elif a.date() != b.date():
            return False
    if len(str(left[3])) > 10 and len(str(right[3])) > 10:
        # An unknown offset cannot establish a different absolute instant.
        if a is not None and b is not None and (a.tzinfo is None) == (b.tzinfo is None) and a != b:
            return False
    return all(not a or not b or a == b for a, b in zip(left[4:], right[4:], strict=True))


def _input_value(row: sqlite3.Row, definition: Input) -> float | None:
    if (row["verification_status"] not in {"verified", "corrected"}
            or row["comparator"] or row["value_numeric"] is None
            or str(row["extraction_method"]).startswith("derived_")):
        return None
    # Canonical metadata may have been inferred from the concept or left stale
    # after a correction. Only a unit actually recorded with the source value
    # establishes the dimensions of an arithmetic input.
    unit = row["unit_raw"]
    if not canonical_unit(unit):
        return None
    number = finite_number(row["value_numeric"])
    if number is None:
        return None
    # Hct L/L is an explicit volume fraction, not a guessed percentage.
    if definition.name in {"Body weight", "Body height"}:
        try:
            value = convert_quantity(number, canonical_unit(unit), definition.unit)
        except ValueError:
            return None
        if not is_plausible("body_weight" if definition.name == "Body weight" else "body_height", value):
            return None
    elif definition.name == "Hematocrit" and canonical_unit(unit) == "l/l":
        value = number * 100
    elif definition.name == "Reticulocytes, absolute" and canonical_unit(unit) == "10^12/l":
        # The source's 10^6/µL is a tera-per-litre count, 1000 times the
        # giga-per-litre unit of an absolute reticulocyte result. No magnitude
        # inference is permitted when the unit is missing or different.
        value = number * 1000
    else:
        value = convert_value(number, unit, definition.unit, definition.concept_id)
    if value is None or not math.isfinite(value) or value < 0 or (value == 0 and not definition.allow_zero):
        return None
    if definition.maximum is not None and value > definition.maximum:
        return None
    return value


def wanted_lab_observations(
    connection: sqlite3.Connection, owner_user_id: str | None = None,
) -> dict[str, tuple]:
    """Return supported missing results in the column order of derived._COLUMNS.

    Reads source observations only; it never writes or marks anything checked.
    ``owner_user_id`` limits it to one account's record.
    Multiple inputs for one concept in a sample are ambiguous even when their
    displayed numbers happen to match. A missing report/document or date is
    insufficient provenance for combining laboratory values.
    """
    groups: dict[tuple, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    # A plain equality, so the (owner, concept, date) index serves it.
    owner = (owner_user_id,) if owner_user_id else ()
    target_presence = defaultdict(list)
    device_bmi = set()
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='device_metric_days'").fetchone():
        # Clinical confirmed inputs replace a calculated device fallback. A
        # genuinely reported BMI takes precedence over either reconstruction.
        device_bmi = {
            (row[0], row[1], str(row[2])[:10]) for row in connection.execute(
                f"""SELECT owner_user_id, patient_id, day FROM device_metric_days
                   WHERE metric_key='body_mass_index' AND substr(id, 1, 12)<>'derived-bmi-'
                     {'AND owner_user_id = ?' if owner else ''}""",
                owner,
            )
        }
    for row in connection.execute(
        f"""SELECT o.* FROM observations o
             JOIN patients p ON p.id=o.patient_id AND p.owner_user_id=o.owner_user_id
             LEFT JOIN documents d ON d.id=o.document_id
             LEFT JOIN reports r ON r.id=o.report_id
             LEFT JOIN documents rd ON rd.id=r.document_id
             WHERE o.concept_id IN ({','.join('?' for _ in _CONCEPT_IDS)})
             AND o.verification_status <> 'rejected'
             AND COALESCE(o.report_id, o.document_id) IS NOT NULL
             AND (o.document_id IS NULL OR (d.owner_user_id=o.owner_user_id AND d.patient_id=o.patient_id))
             AND (o.report_id IS NULL OR (r.owner_user_id=o.owner_user_id AND r.patient_id=o.patient_id
                  AND rd.owner_user_id=o.owner_user_id AND rd.patient_id=o.patient_id
                  AND (o.document_id IS NULL OR r.document_id=o.document_id)))
             {'AND o.owner_user_id = ?' if owner else ''}
             ORDER BY o.id""",
        (*sorted(_CONCEPT_IDS), *owner),
    ):
        if not any(str(row[key] or "").strip() for key in ("report_id", "document_id")):
            continue
        scope = _scope(row)
        if row["extraction_method"] in DERIVED_LAB_METHODS:
            continue
        target_presence[(*scope[:3], row["concept_id"])].append(scope)
        try:
            observed_at = str(row["observed_at"])
            date.fromisoformat(observed_at[:10])
            if len(observed_at) != 10:
                datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if not str(row["extraction_method"]).startswith("derived_"):
            groups[scope][row["concept_id"]].append(row)

    seeded = {row[0] for row in connection.execute("SELECT id FROM concepts")}
    wanted = {}
    for scope, by_concept in groups.items():
        for calculation in LAB_CALCULATIONS:
            if calculation.method in INACTIVE_LAB_METHODS:
                continue
            if calculation.concept_id not in seeded:
                continue
            if calculation.method != "derived_bmi" and specimen_family(scope[4]) not in (None, "hematology"):
                continue
            if calculation.method == "derived_bmi" and (scope[0], scope[1], str(scope[3])[:10]) in device_bmi:
                continue
            if any(_sample_may_match(scope, target) for target in target_presence[(*scope[:3], calculation.concept_id)]):
                continue
            rows = []
            values = []
            for definition in calculation.inputs:
                matches = by_concept.get(definition.concept_id, ())
                if len(matches) != 1:
                    break
                value = _input_value(matches[0], definition)
                if value is None:
                    break
                rows.append(matches[0])
                values.append(value)
            if len(values) != len(calculation.inputs):
                continue
            result = calculation.equation(*values)
            if not math.isfinite(result) or result < 0:
                continue
            if calculation.maximum is not None and result > calculation.maximum:
                continue
            anchor = rows[0]
            row_id = str(uuid.uuid5(_NAMESPACE, "|".join((calculation.concept_id, *(row["id"] for row in rows)))))
            evidence = calculation.formula + "\n" + "\n".join(
                f"{row['id']}: {value:g} {definition.unit}; "
                + json.dumps({key: row[key] for key in (
                    "value_numeric", "unit_raw", "unit_canonical", "observed_at", "specimen",
                    "sample_condition", "report_id", "document_id",
                )}, ensure_ascii=False, sort_keys=True)
                + f"; {row['evidence_text']}"
                for row, value, definition in zip(rows, values, calculation.inputs, strict=True)
            )
            wanted[row_id] = (
                anchor["owner_user_id"], anchor["patient_id"], anchor["document_id"], anchor["page_number"],
                calculation.concept_id, calculation.name, "numeric", round(result, calculation.decimals),
                calculation.unit, calculation.unit, anchor["observed_at"], "extracted", calculation.method,
                min(float(row["confidence"]) for row in rows), evidence, None, PARSER_VERSION,
                anchor["report_id"], anchor["entry_source"], anchor["entered_by_user_id"],
                anchor["specimen"], anchor["sample_condition"],
                json.dumps([
                    {"input_kind": "observation", "input_id": row["id"],
                     "input_concept_id": definition.concept_id, "input_name": definition.name,
                     "input_value": row["value_numeric"], "input_unit": row["unit_raw"] or row["unit_canonical"],
                     "input_day": row["observed_at"], "document_id": row["document_id"],
                     "report_id": row["report_id"]}
                    for row, definition in zip(rows, calculation.inputs, strict=True)
                ], ensure_ascii=False, sort_keys=True),
            )
    return wanted
