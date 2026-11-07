"""Evaluation engine: turn one stored value into one displayable verdict.

Two claims are kept strictly apart and never merged:

* **curated** - an official published interval or decision threshold, cited.
* **vendor**  - the reference interval the laboratory printed on its own report.

A curated rule wins when it matches on unit, sex and age.  Otherwise the
vendor's own parsed bounds speak.  Otherwise the value is ``unjudged`` and the
verdict says why, so the interface can explain the gap instead of hiding it.

Unit safety is the single most dangerous failure mode here: 5.6 mmol/L and
5.6 mg/dL are different clinical worlds.  Conversions live in one explicit
table, are per-concept because molar masses differ, and anything not in the
table is refused rather than guessed.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
import uuid
from calendar import monthrange
from collections.abc import Callable
from contextvars import ContextVar
from datetime import date, datetime
from pathlib import Path

from .config import ID_NAMESPACE_PREFIX, resource_path
from .db import utc_now
from .health import CONCEPT_UNIT_ALIASES, UNIT_TRANSLATIONS, VALUE_TRANSLATIONS, display_unit
from .i18n import format_date_localized, format_number_localized, get_locale, t
from .ingest.text import collapse_space, normalized_key
from .panels import PANEL_BY_ID, device_twins, panel_for_concept


PARSER_AUTHORITIES = ("curated", "vendor", "none")

#: A retest is "due soon" once the due date is this close.
DUE_SOON_DAYS = 60
#: Share of the range bar the shaded band occupies when it has two bounds, and
#: when it is open at one end.  Fixing these keeps every bar visually
#: comparable: the band edge always sits at 0.2 / 0.8 of the track.
BAND_TRACK_FRACTION = 0.6
OPEN_BAND_TRACK_FRACTION = 0.8

_NO_UNIVERSAL_TARGET = "no_universal_target"

#: Interpretations that describe a reassuring result.  Used to break ties
#: between overlapping bands from different sources: a normal band from one
#: publisher must never mask an abnormal band from another.
BENIGN_INTERPRETATIONS = frozenset({"normal", "optimal", "negative"})

#: Analytes where a positive result is the desirable outcome.  Mumps IgG means
#: immunity; rendering it as an abnormal finding would be alarming and wrong.
POSITIVE_IS_GOOD = frozenset({"mumps-virus-igg"})

#: Fixed inherited attributes.  They are facts, not measurements, and must be
#: structurally incapable of producing a high/low/attention state.
NOT_A_MEASUREMENT = frozenset(
    {"blood-group", "rhesus-factor", "hla-b27", "body_height"}
)

#: How alarming an interpretation is, lowest first.  When several bands from
#: different bodies contain one value the most cautious reading leads: an LDL
#: of 5.5 is "critically high" to ESC/EAS before it is "above your goal".
_SEVERITY = {
    "critical_low": 0, "critical_high": 0, "critical": 0,
    "low": 1, "high": 1, "positive": 1, "abnormal": 1,
    "borderline": 2, "borderline_low": 2, "borderline_high": 2, "indeterminate": 2,
}

#: Clinical inputs a band can require.  A band naming one in ``requires``
#: judges only when the record holds that input, and -- when the band also
#: names a value for it -- only for a person with that value.
CV_RISK_CATEGORIES = ("low", "moderate", "high", "very_high")

#: ESC/EAS 2019 Table 4 (carried unchanged by the 2025 focused update):
#: "markedly elevated single risk factors, in particular TC >8 mmol/L or
#: LDL-C >4.9 mmol/L" place a person at HIGH risk without any score.  ACC/AHA
#: 2026 treats LDL-C >=190 mg/dL (4.9 mmol/L) the same way, and Наказ МОЗ 564
#: names LDL-C >=4.9 as severe hypercholesterolaemia.  The LDL edge is taken
#: inclusive (the US wording), the total-cholesterol edge exclusive (the only
#: body that states it, ESC/EAS, writes ">8").
_CV_RISK_MARKERS = (
    ("ldl-cholesterol", 4.9, True),
    ("total-cholesterol", 8.0, False),
)


# --- per-request lookup cache ------------------------------------------------

#: One dict per web request (set by the app's request middleware), so a page
#: that judges five hundred values reads each concept's rules once instead of
#: issuing two statements per value.  Outside a request it is ``None`` and
#: nothing is cached: a CLI run or a test that edits rules between calls never
#: reads a stale band.  ``seed_reference_library`` clears it.
RULE_CACHE: ContextVar[dict | None] = ContextVar("anamna_reference_rule_cache", default=None)


def _cached(key: tuple, build: Callable[[], object]):
    cache = RULE_CACHE.get()
    if cache is None:
        return build()
    if key not in cache:
        cache[key] = build()
    return cache[key]


def invalidate_rule_cache() -> None:
    cache = RULE_CACHE.get()
    if cache is not None:
        cache.clear()


# --- clinical context ------------------------------------------------------


def clinical_context(connection: sqlite3.Connection, owner_user_id: str | None) -> dict[str, object]:
    """The clinical inputs a risk-stratified goal needs, from this record.

    The cardiovascular risk category comes from the profile when the person
    set one.  Otherwise it is derived only where a published rule allows it
    without a risk score: an LDL cholesterol >=4.9 mmol/L or a total
    cholesterol >8 mmol/L anywhere in the record places the person in *at
    least* the high-risk category.  Nothing else is guessed -- a record with no
    such reading holds no category, and the goals stay unjudged.
    """
    if not owner_user_id:
        return {}
    row = connection.execute(
        "SELECT cv_risk_category FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1",
        (owner_user_id,),
    ).fetchone()
    chosen = str(row[0] or "") if row else ""
    if chosen in CV_RISK_CATEGORIES:
        return {"cv_risk_category": chosen, "cv_risk_basis": "profile"}
    evidence = None
    for concept_id, threshold, inclusive in _CV_RISK_MARKERS:
        found = _latest_reading_over(connection, owner_user_id, concept_id, threshold, inclusive)
        if found is None:
            continue
        observed_at, value = found
        if evidence is None or observed_at > str(evidence["date"] or ""):
            evidence = {
                "concept_id": concept_id,
                "value": value,
                "threshold": threshold,
                "inclusive": inclusive,
                "date": observed_at[:10] or None,
            }
    if evidence is None:
        return {}
    return {
        "cv_risk_category": "high",
        "cv_risk_basis": "derived",
        "cv_risk_at_least": True,
        "cv_risk_evidence": evidence,
    }


def _latest_reading_over(
    connection: sqlite3.Connection, owner_user_id: str, concept_id: str, threshold: float, inclusive: bool
) -> tuple[str, float] | None:
    """(observed_at, value in mmol/L) of the newest reading past the threshold."""
    for reading in connection.execute(
        """SELECT value_numeric, unit_raw, observed_at FROM observations
           WHERE owner_user_id=? AND concept_id=? AND value_numeric IS NOT NULL
             AND verification_status <> 'rejected'
           ORDER BY observed_at DESC""",
        (owner_user_id, concept_id),
    ):
        value = convert_value(float(reading[0]), reading[1], "mmol/L", concept_id)
        if value is None:
            continue
        if value >= threshold if inclusive else value > threshold:
            return str(reading[2] or ""), value
    return None


def risk_note(context: dict[str, object] | None) -> str | None:
    """Which cardiovascular risk category judged this value, and why -- in words."""
    context = context or {}
    category = context.get("cv_risk_category")
    if not category:
        return None
    label = t(f"cv_risk.at_least_{category}" if context.get("cv_risk_at_least") else f"cv_risk.{category}")
    if context.get("cv_risk_basis") == "profile":
        return t("cv_risk.note_profile", category=label)
    evidence = context.get("cv_risk_evidence") or {}
    return t(
        "cv_risk.note_derived",
        analyte=t(f"cv_risk.marker_{str(evidence.get('concept_id', '')).replace('-', '_')}"),
        value=_number(round(float(evidence.get("value") or 0), 2)),
        date=format_date_localized(evidence.get("date")),
        category=label,
    )

# --- units -----------------------------------------------------------------

# mg/dL = mmol/L x factor.  Each analyte has its own molar mass; sharing one
# number across lipids and glucose is exactly the mistake this table prevents.
_MMOL_L_TO_MG_DL = {
    "blood-glucose": 18.0182,
    "total-cholesterol": 38.67,
    "ldl-cholesterol": 38.67,
    "hdl-cholesterol": 38.67,
    "vldl-cholesterol": 38.67,
    "triglycerides": 88.57,
}

#: The canonical (casefolded) spelling of mg/dL, the key every conversion uses.
_MG_DL = "mg/dl"

#: (concept_id, from_unit, to_unit) -> multiplier.  Units are canonicalised.
UNIT_CONVERSIONS: dict[tuple[str, str, str], float] = {}
for _concept, _factor in _MMOL_L_TO_MG_DL.items():
    UNIT_CONVERSIONS[(_concept, "mmol/l", _MG_DL)] = _factor
    UNIT_CONVERSIONS[(_concept, _MG_DL, "mmol/l")] = 1.0 / _factor
# 25-OH vitamin D, molar mass 400.6 g/mol
UNIT_CONVERSIONS[("25-hydroxyvitamin-d", "ng/ml", "nmol/l")] = 2.496
UNIT_CONVERSIONS[("25-hydroxyvitamin-d", "nmol/l", "ng/ml")] = 1.0 / 2.496
# Cyanocobalamin, molar mass 1355.4 g/mol
UNIT_CONVERSIONS[("vitamin-b12", "pg/ml", "pmol/l")] = 0.7378
UNIT_CONVERSIONS[("vitamin-b12", "pmol/l", "pg/ml")] = 1.0 / 0.7378
# MCHC is printed in g/dL by Synevo and in g/L by Expert Hospital, so one
# patient's own series carries both: 36 g/dL and 340 g/L are the same order of
# magnitude apart by exactly 10, and read together they look like a collapse.
UNIT_CONVERSIONS[("mean-corpuscular-hemoglobin-concentration", "g/dl", "g/l")] = 10.0
UNIT_CONVERSIONS[("mean-corpuscular-hemoglobin-concentration", "g/l", "g/dl")] = 0.1
# Urobilinogen, molar mass ≈ 592 g/mol: 1 mg/dL = 16.9 µmol/L. Expert Hospital
# prints its own strip tiers in µmol/L («+- = 8,5; + = 17; ++ = 50») exactly
# where the Multistix mg/dL scale prints 0.5 / 1 / 3 — the same ordinal steps
# a factor of 16.9 apart, which corroborates the molar-mass figure.
UNIT_CONVERSIONS[("urine-urobilinogen", _MG_DL, "umol/l")] = 16.9
UNIT_CONVERSIONS[("urine-urobilinogen", "umol/l", _MG_DL)] = 1.0 / 16.9
# Free thyroxine: Synevo prints ng/dL on one panel and pmol/L on another.
# Thyroxine C15H11I4NO4, molar mass 776.87 g/mol (PubChem CID 5819), so
# 1 ng/dL = 10 ng/L / 776.87 g/mol = 12.87 pmol/L -- the factor of the
# AMA Manual of Style SI conversion table ("Thyroxine, free: ng/dL x 12.87").
UNIT_CONVERSIONS[("free-thyroxine", "ng/dl", "pmol/l")] = 12.87
UNIT_CONVERSIONS[("free-thyroxine", "pmol/l", "ng/dl")] = 1.0 / 12.87

# Same number, different label: the per-concept table lives beside the unit
# synonyms in health.py, which also folds the stored unit on the way in.
for (_concept, _printed), _stored in CONCEPT_UNIT_ALIASES.items():
    UNIT_CONVERSIONS[(_concept, _printed, _stored)] = 1.0
    UNIT_CONVERSIONS[(_concept, _stored, _printed)] = 1.0


# «Г/л» is гіга-per-litre (10^9/L, used for leukocytes and platelets); «г/л»
# is грам-per-litre (used for haemoglobin). They differ by one letter of case
# and by a factor of 10^9, and MOZ protocols print both -- Наказ 1581/2024 and
# Наказ 49/2021 use them side by side. The table lookup below casefolds, which
# collapses the two onto "g/l", so a platelet count in Г/л would be judged
# against a haemoglobin interval. This lookup runs first, case-sensitively.
_CASE_SENSITIVE_UNITS = {
    "Г/л": "10^9/L",
    "Г/Л": "10^9/L",
}


def canonical_unit(unit: str | None) -> str:
    """Fold a printed unit to a comparison key.

    ``µmol/L`` (U+00B5), ``μmol/L`` (U+03BC), ``umol/L`` and ``мкмоль/л`` are
    the same unit written four ways.  Comparing them as raw strings is how a
    creatinine result silently loses its verdict, so every unit on both sides
    of every comparison goes through here.
    """
    if not unit:
        return ""
    raw = collapse_space(str(unit).replace("\xa0", " "))
    # Look the Cyrillic form up before NFKC folding, which would rewrite the
    # superscript in "кг/м²" and miss the table entry.
    english = _CASE_SENSITIVE_UNITS.get(raw) or UNIT_TRANSLATIONS.get(raw.casefold(), raw)
    folded = unicodedata.normalize("NFKC", english).casefold()
    return folded.replace(" ", "").replace("\xa0", "").replace("µ", "u").replace("μ", "u")


def convert_value(
    value: float, from_unit: str | None, to_unit: str | None, concept_id: str
) -> float | None:
    """Convert between units, or ``None`` when no conversion is registered."""
    source = canonical_unit(from_unit)
    target = canonical_unit(to_unit)
    if not target or source == target:
        return value
    if not source:
        return None
    factor = UNIT_CONVERSIONS.get((concept_id, source, target))
    return None if factor is None else value * factor


# --- range-bar geometry ----------------------------------------------------


def _domain(low: float | None, high: float | None) -> tuple[float, float] | None:
    """Display window for the range bar, wide enough to show the band edges."""
    open_pad = (1.0 - OPEN_BAND_TRACK_FRACTION) / OPEN_BAND_TRACK_FRACTION
    if low is not None and high is not None:
        span = high - low
        if span <= 0:
            span = abs(high) or 1.0
        pad = span * (1.0 - BAND_TRACK_FRACTION) / (2.0 * BAND_TRACK_FRACTION)
        return low - pad, high + pad
    if high is not None:
        # Open below: the band runs from the start of the track to 0.8.
        span = abs(high) or 1.0
        start = 0.0 if high > 0 else high - span
        return start, high + (high - start) * open_pad
    if low is not None:
        # Open above: the band starts at 0.2 and runs off the end.
        span = abs(low) or 1.0
        return low - span * open_pad, low + span
    return None


def band_geometry(
    value: float | None,
    low: float | None,
    high: float | None,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> dict[str, object]:
    """Map a value and its band onto a 0..1 track.

    Open-ended bands get a synthesised window.  Markers outside the window are
    clamped so a value ten times the upper bound cannot break the layout, while
    ``out_of_range_side`` still tells the template to draw it past the edge.
    """
    domain = _domain(low, high)
    if domain is None:
        return {"position": None, "band_start": None, "band_end": None, "out_of_range_side": None}
    start, end = domain
    width = end - start
    if width <= 0:
        return {"position": None, "band_start": None, "band_end": None, "out_of_range_side": None}

    def place(point: float | None, default: float) -> float:
        if point is None:
            return default
        return min(1.0, max(0.0, (point - start) / width))

    side = None
    position = None
    if value is not None:
        if low is not None and (value < low or (value == low and not low_inclusive)):
            side = "low"
        elif high is not None and (value > high or (value == high and not high_inclusive)):
            side = "high"
        position = place(value, 0.0)
    return {
        "position": position,
        "band_start": place(low, 0.0),
        "band_end": place(high, 1.0),
        "out_of_range_side": side,
    }


# --- formatting ------------------------------------------------------------


def _number(value: float) -> str:
    # The interval sits directly beside the reader's own value, which already
    # formats through format_number_localized -- so a raw float repr here put
    # "6,57" and "3.5-8.8" side by side on the same Ukrainian line, the exact
    # split that function's docstring was written to close.
    # Precision is derived from the value rather than left to that function's
    # magnitude-based default, which would round a 0.001 bound to "0".
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if not text:
        return "0"
    decimals = len(text.partition(".")[2])
    return format_number_localized(value, decimals)


def range_text(
    low: float | None,
    high: float | None,
    unit: str | None,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> str:
    """An interval as a person reads it, with the comparator the band means.

    Inclusivity is not decoration on an open-ended band: a "detected" band
    written as ``lower: 0, lower_inclusive: false`` renders as "≥ 0" if the
    flag is ignored, which tells a reader that a urine bilirubin of zero is
    abnormal — the exact opposite of the band it is labelling.
    """
    # The unit travels with the number wherever an interval is shown, so it has
    # to follow the interface language: "5.6-7 ммоль/л" in Ukrainian, not
    # "5.6-7 mmol/L".
    localised = display_unit(unit) if unit else ""
    suffix = f" {localised}" if localised else ""
    if low is not None and high is not None:
        return f"{_number(low)}-{_number(high)}{suffix}"
    if high is not None:
        return f"{'≤' if high_inclusive else '<'} {_number(high)}{suffix}"
    if low is not None:
        return f"{'≥' if low_inclusive else '>'} {_number(low)}{suffix}"
    return t("em.dash")


# --- staleness -------------------------------------------------------------


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def _as_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _parse_condition(condition: object) -> dict[str, object] | None:
    if not condition:
        return None
    if isinstance(condition, dict):
        return condition
    try:
        parsed = json.loads(str(condition))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _condition_met(
    condition: dict[str, object], interpretation: str | None, age_years: float | None
) -> tuple[bool, str]:
    """Whether a conditional cadence applies, and the key that explains a miss."""
    if condition.get("any"):
        return _any_condition_met(condition["any"], interpretation, age_years)
    when = condition.get("applies_when")
    if when == "abnormal" and interpretation not in _SEVERITY:
        return False, "abnormal_only"
    if when == "not_abnormal" and interpretation in _SEVERITY:
        return False, "follow_up_by_treatment"
    if when in {"on_treatment", "occupational"}:
        # The record holds neither treatment nor occupation; a cadence written
        # for those settings is never presented as a routine schedule.
        return False, when
    reason = _age_condition_miss(condition.get("age_min"), condition.get("age_max"), age_years)
    if reason:
        return False, reason
    return True, ""


def _any_condition_met(
    items, interpretation: str | None, age_years: float | None
) -> tuple[bool, str]:
    reasons = []
    for item in items:
        met, reason = _condition_met(item, interpretation, age_years)
        if met:
            return True, ""
        reasons.append(reason)
    return False, reasons[0] if reasons else "condition"


def _age_condition_miss(low: object, high: object, age_years: float | None) -> str | None:
    """Why an age-limited cadence does not apply to this person, or None."""
    if low is None and high is None:
        return None
    if age_years is None:
        return "age_unknown"
    if (low is not None and age_years < float(low)) or (
        high is not None and age_years > float(high)
    ):
        return "age_range"
    return None


def staleness(
    last_observed_at: str | date | None,
    retest_months: int | None,
    *,
    today: date | None = None,
    rationale: str | None = None,
    condition: object = None,
    interpretation: str | None = None,
    age_years: float | None = None,
) -> dict[str, object]:
    """How out of date a result is.

    ``fresh`` / ``due_soon`` / ``overdue`` need a cited retest cadence.  When
    none is published - the majority case - the state is ``no_interval``,
    which still carries ``days_ago`` so the interface can sort oldest first.
    ``never`` means the analyte has no result at all.

    A cadence can be conditional (``retest_condition_json``): "repeat a raised
    TSH after 2-3 months" is not a routine three-month schedule, and annual FIT
    screening starts at 45.  When the condition is not met by this result
    (``interpretation``) or this person (``age_years``) the cadence does not
    apply, the state is ``no_interval`` and ``condition_note`` says why.
    """
    today = today or date.today()
    last = _as_date(last_observed_at)
    if last is None:
        return {
            "state": "never",
            "label": t("stale.never"),
            "days_ago": None,
            "last_tested": None,
            "due_on": None,
            "interval_months": retest_months,
            "rationale": rationale,
            "condition_note": None,
        }
    days_ago = (today - last).days
    condition_note = None
    parsed = _parse_condition(condition)
    if retest_months and parsed:
        met, reason = _condition_met(parsed, interpretation, age_years)
        if not met:
            condition_note = t(f"stale.condition_{reason}", months=retest_months)
            retest_months = None
    due_on = _add_months(last, retest_months) if retest_months else None
    if due_on is None:
        # Most analytes have no published screening cadence for an
        # asymptomatic adult.  Say so and keep the temporal signal, rather
        # than inventing an interval or pretending the result is fresh.
        state = "no_interval"
    elif today > due_on:
        state = "overdue"
    elif (due_on - today).days <= DUE_SOON_DAYS:
        state = "due_soon"
    else:
        state = "fresh"
    return {
        "state": state,
        "label": t(f"stale.{state}", days=days_ago, months=retest_months or 0),
        "days_ago": days_ago,
        "last_tested": last.isoformat(),
        "due_on": due_on.isoformat() if due_on else None,
        "interval_months": retest_months,
        "rationale": rationale,
        "condition_note": condition_note,
    }


# --- verdicts --------------------------------------------------------------

_VENDOR_INTERPRETATIONS = {
    "within_vendor_range": "normal",
    "low": "low",
    "high": "high",
    "borderline": "indeterminate",
    "positive": "positive",
    "negative": "negative",
}


#: Every optional field of a verdict, with its default.  ``_verdict`` takes
#: them as keywords and refuses any other name, so a misspelt field fails
#: loudly instead of silently leaving its default in place.
_VERDICT_FIELDS: dict[str, object] = {
    "source_id": None,  # str | None
    "source_name": None,  # str | None
    "source_url": None,  # str | None
    "band_label": None,  # str | None
    "low": None,  # float | None
    "high": None,  # float | None
    "low_inclusive": True,
    "high_inclusive": True,
    "unit": None,  # str | None
    "value": None,  # float | None
    "reason": None,  # str | None
    "no_universal_target": False,
    "note": None,  # str | None
    "curated_blocked": None,  # str | None
    "target_low": None,  # float | None
    "target_high": None,  # float | None
    "target_inclusive": None,  # tuple[bool, bool] | None
    "target_source": None,  # dict | None
    "authority_positions": None,  # list[dict] | None
    "official": None,  # bool | None
    "risk_context": None,  # dict | None
}


def _verdict(interpretation: str, authority: str, **fields: object) -> dict[str, object]:
    unknown = fields.keys() - _VERDICT_FIELDS.keys()
    if unknown:
        raise TypeError(f"_verdict() got unexpected fields: {sorted(unknown)}")
    field = {**_VERDICT_FIELDS, **fields}
    source_id, source_name, source_url = field["source_id"], field["source_name"], field["source_url"]
    band_label, unit, value, official = field["band_label"], field["unit"], field["value"], field["official"]
    low, high = field["low"], field["high"]
    low_inclusive, high_inclusive = field["low_inclusive"], field["high_inclusive"]
    target_low, target_high = field["target_low"], field["target_high"]
    target_inclusive, target_source = field["target_inclusive"], field["target_source"]
    risk_context = field["risk_context"]
    # The bar always shades the band the reader should be IN, which is not
    # always the band the value matched. Triglycerides 3.25 matches the "High"
    # tier [2.26, 5.64]; shading that tier puts the marker inside the shaded
    # region, which reads as reassuring while the chip says "Above range".
    # Shading the healthy band instead puts the marker visibly outside it.
    has_target = target_low is not None or target_high is not None
    bar_low, bar_high = (target_low, target_high) if has_target else (low, high)
    bar_low_inc, bar_high_inc = target_inclusive or (low_inclusive, high_inclusive)
    geometry = band_geometry(value, bar_low, bar_high, bar_low_inc, bar_high_inc)
    # The shaded interval is cited to the body that published IT. Citing the
    # matched band's body beside a target from another body attributed the
    # EAS/EFLM 3.8 non-HDL cut-point to ESC.
    target_source = target_source if has_target and target_source else {
        "source_id": source_id, "source_name": source_name, "source_url": source_url,
        "band_label": band_label, "official": official,
    }
    positions = field["authority_positions"] or []
    judged_positions = [item for item in positions if item.get("benign") is not None]
    curated = authority == "curated"
    return {
        "interpretation": interpretation,
        "label": t(f"verdict.{interpretation}"),
        "authority": authority,
        # A peer-reviewed review is cited, but it is not an official guideline,
        # and the badge must not say it is.
        "authority_label": t(
            "authority.curated_unofficial" if curated and official is False else f"authority.{authority}"
        ),
        "source_official": official,
        "source_id": source_id,
        "source_name": source_name,
        "source_url": source_url,
        "band_label": band_label,
        "unit": unit,
        "low": low,
        "high": high,
        "low_inclusive": low_inclusive,
        "high_inclusive": high_inclusive,
        "range_text": range_text(low, high, unit, low_inclusive, high_inclusive),
        # What the bar is actually showing, so the caption can name the target
        # rather than the severity tier the value happened to land in.
        "target_low": bar_low,
        "target_high": bar_high,
        "target_low_inclusive": bar_low_inc,
        "target_high_inclusive": bar_high_inc,
        "target_range_text": range_text(bar_low, bar_high, unit, bar_low_inc, bar_high_inc),
        "target_source_id": target_source.get("source_id"),
        "target_source_name": target_source.get("source_name"),
        "target_source_url": target_source.get("source_url"),
        "target_band_label": target_source.get("band_label"),
        # Tick labels must name the band the bar actually draws. Labelling the
        # matched band while shading the target produced a green bar in the
        # middle captioned with numbers from a different interval.
        "target_low_text": _number(bar_low) if bar_low is not None else "",
        "target_high_text": _number(bar_high) if bar_high is not None else "",
        "target_is_matched_band": (bar_low, bar_high) == (low, high),
        # Every publishing body with an opinion about this value, and whether
        # they agree. The UI shows all of them when they do not. "Normal" and
        # "optimal" are the same reassurance in two words, and "high" and
        # "critically high" the same alarm; a disagreement is a reassuring,
        # a watch-and-wait and an abnormal reading set against each other
        # (135/85 is stage 1 hypertension in the US, high-normal in Europe).
        "authority_positions": positions,
        "authorities_disagree": len({item["class"] for item in judged_positions}) > 1,
        # Band edges in the rule's unit, for edge_safe_decimals().
        "edges": [edge for edge in (low, high, bar_low, bar_high) if edge is not None],
        "risk_context": risk_context or None,
        "risk_note": risk_note(risk_context),
        "unjudged_reason": field["reason"],
        "no_universal_target": field["no_universal_target"],
        "positive_is_good": False,
        "curated_blocked": field["curated_blocked"],
        "conflicts_with_vendor": False,
        "vendor_low": None,
        "vendor_high": None,
        "vendor_range_text": None,
        "vendor_interpretation": None,
        "vendor_status": None,
        "note": field["note"],
        **geometry,
    }


def edge_safe_decimals(
    value: float | None, decimals: int, verdict: dict | None, unit: str | None = None,
    *, max_extra: int = 3,
) -> int:
    """Decimals that keep a displayed number on the same side of every band edge.

    "Time asleep 7 h — below the ≥7 h recommendation" is what rounding 6.95 to
    a whole hour printed, and "Respiratory rate 12 — below 12–20" what 11.68
    became. The precision a unit normally deserves is kept, and raised only
    when rounding would land on or across an edge of the band that judged the
    value. Edges are in the rule's unit, so a different display unit is left
    alone (``unit`` is compared through ``canonical_unit``).
    """
    if value is None or not verdict:
        return decimals
    if unit is not None and canonical_unit(unit) != canonical_unit(verdict.get("unit")):
        return decimals
    edges = [float(edge) for edge in verdict.get("edges") or ()]
    number = float(value)
    for extra in range(max_extra + 1):
        rounded = round(number, decimals + extra)
        if all((rounded < e) == (number < e) and (rounded == e) == (number == e) for e in edges):
            return decimals + extra
    return decimals + max_extra


def _rule_context(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _contains(
    value: float,
    low: float | None,
    high: float | None,
    low_inclusive: bool,
    high_inclusive: bool,
) -> bool:
    if low is not None and (value < low or (value == low and not low_inclusive)):
        return False
    if high is not None and (value > high or (value == high and not high_inclusive)):
        return False
    return True


def _authority_positions(containing) -> list[dict[str, object]]:
    """One entry per publishing body that has an opinion about this value.

    Different authorities genuinely disagree: a fasting glucose of 5.61 mmol/L
    is prediabetes to the ADA and to Ukraine's МОЗ protocol, and normal to the
    WHO. Collapsing that to a single verdict would hide the disagreement, which
    is exactly the thing a reader needs to see. The chip still shows one
    interpretation -- the most cautious -- but every position travels with it.
    """
    by_source: dict[str, dict[str, object]] = {}
    for rule, _context, _converted in containing:
        set_id = str(rule["reference_set_id"])
        if set_id in by_source:
            continue  # one position per body; bands within a body do not overlap
        interpretation = str(rule["interpretation"])
        declines = interpretation == _NO_UNIVERSAL_TARGET
        by_source[set_id] = {
            "source_id": set_id,
            "publisher": rule["publisher"],
            "source_name": rule["set_name"],
            "source_url": rule["source_url"],
            "region": rule["region"] if "region" in rule.keys() else None,
            "official": _official(rule),
            "interpretation": interpretation,
            "label": t(f"verdict.{interpretation}"),
            "band_label": rule["label"],
            # A body that deliberately sets no number ("no trial has shown
            # lowering Lp(a) lowers risk") is a position too, but it neither
            # agrees nor disagrees with a numeric one.
            "benign": None if declines else interpretation in BENIGN_INTERPRETATIONS,
            "class": None if declines else verdict_class(interpretation),
            "note": rule["notes"],
            "range_text": "" if declines else range_text(
                rule["lower_bound"], rule["upper_bound"], rule["unit"],
                bool(rule["lower_inclusive"]), bool(rule["upper_inclusive"]),
            ),
            # The raw bounds travel beside the formatted text so a caller that
            # needs a different number convention -- the AI hand-off writes
            # machine-readable decimals -- can render them rather than parse
            # a localised string back apart.
            "low": rule["lower_bound"],
            "high": rule["upper_bound"],
            "low_inclusive": bool(rule["lower_inclusive"]),
            "high_inclusive": bool(rule["upper_inclusive"]),
        }
    positions = sorted(
        by_source.values(),
        key=lambda item: (item["benign"] is None, str(item["publisher"] or "")),
    )
    return positions


def verdict_class(interpretation: str | None) -> str:
    """``benign`` / ``borderline`` / ``abnormal`` / ``unjudged`` -- the
    granularity at which two bodies' readings count as disagreeing."""
    if interpretation in BENIGN_INTERPRETATIONS:
        return "benign"
    if interpretation in {"borderline", "borderline_low", "borderline_high", "indeterminate"}:
        return "borderline"
    if interpretation in _SEVERITY:
        return "abnormal"
    return "unjudged"


def _official(rule) -> bool | None:
    value = rule["official"] if "official" in rule.keys() else None
    return None if value is None else bool(value)


def _looseness(rule) -> tuple[int, float]:
    """How permissive a benign band is: fewer open sides compare by width,
    an open band by its one finite edge (a higher ceiling or a lower floor is
    looser).  Counting every open band as infinitely wide made the choice
    between "<1.4" and "<3.0" fall to list order -- the strictest goal won."""
    low, high = rule["lower_bound"], rule["upper_bound"]
    if low is not None and high is not None:
        return (0, high - low)
    if high is not None:
        return (1, high)
    if low is not None:
        return (1, -low)
    return (2, 0.0)


def _is_gated(context: dict[str, object]) -> bool:
    return bool(context.get("requires"))


def _band_rank(item) -> tuple:
    """Deterministic order for bands that all contain the value.

    An abnormal band wins over a benign one, because two publishers can
    disagree and the alarming reading must not be silently dropped; among
    abnormal bands the most severe.  Then a goal that applies to this person's
    own risk category over a population cut-point, then the higher priority,
    then the narrower band.
    """
    rule, context = item[0], item[1]
    low, high = rule["lower_bound"], rule["upper_bound"]
    width = float("inf") if low is None or high is None else high - low
    return (
        rule["interpretation"] in BENIGN_INTERPRETATIONS,
        _SEVERITY.get(str(rule["interpretation"]), 3),
        not _is_gated(context),
        -int(rule["priority"] or 0),
        width,
    )


def curated_rules(connection: sqlite3.Connection, concept_id: str) -> list[sqlite3.Row]:
    locale = get_locale()
    return _cached(
        ("rules", locale, concept_id),
        lambda: connection.execute(
            """SELECT r.id, r.reference_set_id,
                      CASE WHEN ? = 'uk' AND COALESCE(r.label_uk, '') <> ''
                           THEN r.label_uk ELSE r.label END AS label,
                      r.context_json, r.unit,
                      r.lower_bound, r.upper_bound, r.lower_inclusive, r.upper_inclusive,
                      r.interpretation, r.priority,
                      CASE WHEN ? = 'uk' AND COALESCE(r.notes_uk, '') <> ''
                           THEN r.notes_uk ELSE r.notes END AS notes,
                      r.sex, r.age_min_years, r.age_max_years,
                      r.corroborated_by, r.agreement, r.divergence_note,
                      s.name AS set_name, s.publisher, s.source_url, s.region, s.official
               FROM curated_reference_rules r
               JOIN reference_sets s ON s.id = r.reference_set_id
               WHERE r.concept_id = ?
               ORDER BY r.priority DESC, r.label""",
            (locale, locale, concept_id),
        ).fetchall(),
    )


def rule_label(rule, locale: str | None = None) -> str:
    """A band's label in the reader's language: ``label_uk`` when it exists.

    For any caller that reads ``curated_reference_rules`` itself (the metric
    page's rules list did, and printed English labels on Ukrainian pages)."""
    keys = rule.keys()
    if (locale or get_locale()) == "uk" and "label_uk" in keys and rule["label_uk"]:
        return str(rule["label_uk"])
    return str(rule["label"] or "")


def rule_note(rule, locale: str | None = None) -> str | None:
    """A band's note in the reader's language: ``notes_uk`` when it exists."""
    keys = rule.keys()
    if (locale or get_locale()) == "uk" and "notes_uk" in keys and rule["notes_uk"]:
        return str(rule["notes_uk"])
    return rule["notes"] if "notes" in keys else None


def interpretation_label(interpretation: str | None) -> str:
    """The reader's words for a stored interpretation key (``verdict.*``)."""
    return t(f"verdict.{interpretation or 'unjudged'}")


def rule_requirement(rule) -> dict[str, object] | None:
    """What clinical input a band needs, for the rules list: e.g. the
    cardiovascular risk category it is the goal for."""
    context = _rule_context(rule["context_json"])
    if not _is_gated(context):
        return None
    category = context.get("cv_risk_category")
    return {
        "requires": context.get("requires"),
        "cv_risk_category": category,
        "label": t(f"cv_risk.goal_for_{category}") if category else t("cv_risk.goal_requires"),
    }


def rule_applies_to_context(rule, context: dict[str, object] | None) -> bool:
    """Whether a gated band applies to this person's clinical context --
    the same test _curated_verdict applies, for the rules list's chip."""
    rule_context = _rule_context(rule["context_json"])
    if not _is_gated(rule_context):
        return True
    return _gate(rule_context, context or {}) == "applies"


def _gate(rule_context: dict[str, object], context: dict[str, object]) -> str:
    """``applies`` / ``other`` (a goal for another category) / ``missing:<key>``."""
    requires = rule_context.get("requires")
    keys = [requires] if isinstance(requires, str) else list(requires or ())
    for key in keys:
        if not context.get(key):
            return f"missing:{key}"
        wanted = rule_context.get(key)
        if wanted is not None and wanted != context.get(key):
            return "other"
    return "applies"


def evaluate(
    connection: sqlite3.Connection,
    concept_id: str,
    value_numeric: float | None = None,
    value_text: str | None = None,
    unit: str | None = None,
    age_years: float | None = None,
    sex: str | None = None,
    vendor_low: float | None = None,
    vendor_high: float | None = None,
    vendor_interpretation: str | None = None,
    clinical_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Judge one value.  Curated guidance first, then the laboratory's own range.

    ``clinical_context`` carries inputs a band may require -- the
    cardiovascular risk category from :func:`clinical_context`.  Without it a
    risk-stratified goal never judges.
    """
    if concept_id in NOT_A_MEASUREMENT:
        return _verdict("not_a_measurement", "none")
    rules = curated_rules(connection, concept_id)
    verdict, blocked = _curated_verdict(
        rules, concept_id, value_numeric, value_text, unit, age_years, sex,
        clinical_context=clinical_context or {}, vendor_high=vendor_high,
    )
    if verdict is None:
        # A curated rule that could not be applied (unknown sex, unknown age,
        # a treatment target that needs a risk category) must never be guessed
        # at.  The laboratory's own range speaks instead, and the block stays
        # visible so the interface can explain the gap.
        verdict = _vendor_verdict(
            value_numeric, unit, vendor_low, vendor_high, vendor_interpretation
        )
        if blocked and verdict["interpretation"] == "unjudged":
            verdict["unjudged_reason"] = blocked
    if blocked:
        # A weaker unisex band may still have judged while a more specific
        # sexed or gated rule was skipped.  Keep the reason on the verdict so
        # the interface can say a more specific interval exists, instead of
        # presenting the fallback as the whole answer.
        verdict["curated_blocked"] = blocked
    if _no_universal_target(connection, concept_id):
        # Not a failure state: for most analytes no body has published a
        # universal interval, and the laboratory's own printed range governs.
        verdict["no_universal_target"] = True
    _record_vendor_claim(
        verdict, value_numeric, unit, vendor_low, vendor_high, vendor_interpretation
    )
    return _apply_polarity(verdict, concept_id)


def _record_vendor_claim(
    verdict: dict[str, object],
    value_numeric: float | None,
    unit: str | None,
    vendor_low: float | None,
    vendor_high: float | None,
    vendor_interpretation: str | None,
) -> None:
    """Keep the laboratory's own claim beside the curated one, and flag clashes.

    Two authorities can disagree about the same number.  Showing only the
    reassuring one is worse than showing nothing: a folate of 3.06 ng/mL sits
    inside the ABIM adult interval and below the range the patient's own
    laboratory printed.  Both claims travel with the verdict, and a benign
    curated reading is never allowed to present as reassuring on its own when
    the laboratory disagreed.
    """
    verdict["vendor_low"] = vendor_low
    verdict["vendor_high"] = vendor_high
    verdict["vendor_interpretation"] = vendor_interpretation
    verdict["vendor_range_text"] = (
        range_text(vendor_low, vendor_high, unit)
        if vendor_low is not None or vendor_high is not None
        else None
    )
    # What the laboratory's range says about this value, flag or not. A lab
    # that printed 30-400 and no flag beside a ferritin of 202 still said
    # "within"; reading only the flag reported "No comparison available".
    vendor_status = vendor_interpretation
    if vendor_status is None and value_numeric is not None and (
        vendor_low is not None or vendor_high is not None
    ):
        vendor_status = _vendor_side(float(value_numeric), vendor_low, vendor_high)
    verdict["vendor_status"] = vendor_status
    verdict["conflicts_with_vendor"] = False
    if verdict["authority"] != "curated" or value_numeric is None:
        return
    if vendor_low is None and vendor_high is None:
        return
    vendor_in_range = _contains(float(value_numeric), vendor_low, vendor_high, True, True)
    curated_benign = verdict["interpretation"] in BENIGN_INTERPRETATIONS
    if curated_benign == vendor_in_range:
        return
    verdict["conflicts_with_vendor"] = True
    if curated_benign:
        # Do not render green over a result the laboratory itself called out,
        # and do not hide what the laboratory said behind "Indeterminate"
        # either: name both claims in the chip.
        verdict["interpretation"] = "indeterminate"
        side = vendor_status if vendor_status in {"high", "low"} else "outside"
        verdict["label"] = t(f"verdict.lab_{side}_official_within")


def _vendor_side(value: float, vendor_low: float | None, vendor_high: float | None) -> str:
    """Where a value sits against the laboratory's printed interval."""
    if vendor_high is not None and value > vendor_high:
        return "high"
    if vendor_low is not None and value < vendor_low:
        return "low"
    return "within_vendor_range"


def _no_universal_target(connection: sqlite3.Connection, concept_id: str) -> bool:
    """The library described this analyte but published no band for it.

    That is what ``kind: no_universal_target`` means, and it is the majority
    case: for most analytes no body publishes a universal interval, and the
    laboratory's own printed range is the only thing that governs.
    """
    if curated_rules(connection, concept_id):
        return False
    return _cached(
        ("guided", concept_id),
        lambda: connection.execute(
            "SELECT 1 FROM concept_guidance WHERE concept_id = ?", (concept_id,)
        ).fetchone() is not None,
    )


def _apply_polarity(verdict: dict[str, object], concept_id: str) -> dict[str, object]:
    """Fold analyte polarity into the interpretation.

    For mumps IgG a positive result means immunity.  Leaving it as ``positive``
    would colour it as an abnormal finding and roll the panel up to
    ``attention`` - alarming, and the opposite of what the result means.
    """
    if concept_id in POSITIVE_IS_GOOD and verdict["interpretation"] == "positive":
        verdict["interpretation"] = "optimal"
        verdict["label"] = t("verdict.optimal")
    if concept_id in POSITIVE_IS_GOOD:
        verdict["positive_is_good"] = True
    return verdict


def _rule_source(rule) -> dict[str, object]:
    """Citation for the rule that actually spoke — never a sibling's.

    Building this from ``candidates[0]`` presented a МОЗ України band as an
    EAS/EFLM claim whenever the matched band came from a lower-priority set.
    """
    return {
        "source_id": rule["reference_set_id"],
        "source_name": f"{rule['publisher']}: {rule['set_name']}",
        "source_url": rule["source_url"],
        "official": _official(rule),
    }


#: What a rule that cannot judge this value says about it, beside the block
#: reasons proper: it simply does not describe this person, or it is written
#: for the other sex.  Neither is a block, and both are private sentinels.
_RULE_SKIP = "_skip"
_RULE_OTHER_SEX = "_other_sex"
_GATE_APPLIES = "_applies"


def _gate_rule(context: dict[str, object], clinical_context: dict[str, object]) -> str | None:
    """``None`` for an ungated rule, ``_GATE_APPLIES``, ``_RULE_SKIP`` or a block reason."""
    if not _is_gated(context):
        return None
    # A treatment target that needs a clinical input this record does
    # not hold (e.g. a cardiovascular risk category) must not judge,
    # and a goal written for another category is simply not this
    # person's goal.
    gate = _gate(context, clinical_context)
    if gate.startswith("missing:"):
        if gate.partition(":")[2] == "cv_risk_category":
            return "requires_cv_risk_category"
        return "requires_clinical_context"
    if gate == "other":
        return _RULE_SKIP
    return _GATE_APPLIES


def _vendor_scale_mismatch(context: dict[str, object], vendor_high: float | None) -> bool:
    # A scale calibrated for one assay. ImmunoCAP's class 0 ends at 0.35
    # kUA/L, ALEX² prints its own positivity cut-off of 0.3; a band names
    # the printed laboratory cut-off it belongs with (or must not meet).
    if "vendor_upper" in context and (
        vendor_high is None or abs(float(vendor_high) - float(context["vendor_upper"])) > 1e-9
    ):
        return True
    return "not_vendor_upper" in context and vendor_high is not None and abs(
        float(vendor_high) - float(context["not_vendor_upper"])
    ) <= 1e-9


def _age_miss(rule, age_years: float | None) -> str | None:
    low, high = rule["age_min_years"], rule["age_max_years"]
    if low is None and high is None:
        return None
    if age_years is None:
        return "age_unknown"
    if low is not None and age_years < low:
        return _RULE_SKIP
    if high is not None and age_years >= high:
        return _RULE_SKIP
    return None


def _rule_miss(
    rule, context: dict[str, object], patient_sex: str | None, age_years: float | None,
    vendor_high: float | None,
) -> str | None:
    """Why this rule does not describe this person and assay, or ``None``."""
    if _vendor_scale_mismatch(context, vendor_high):
        return _RULE_SKIP
    rule_sex = (rule["sex"] or "").strip().casefold() or None
    if rule_sex:
        if patient_sex is None:
            return "sex_unknown"
        if rule_sex != patient_sex:
            # Ordinary for the other sex's bands; only meaningful when
            # nothing at all ends up matching (see _curated_verdict).
            return _RULE_OTHER_SEX
    return _age_miss(rule, age_years)


def _converted_for(
    rule, concept_id: str, value_numeric: float | None, unit: str | None
) -> tuple[str | None, float | None]:
    """(block reason, the value in the rule's unit)."""
    if value_numeric is None or rule["interpretation"] == _NO_UNIVERSAL_TARGET:
        return None, None
    converted = convert_value(float(value_numeric), unit, rule["unit"], concept_id)
    if converted is None:
        return "unit_mismatch", None
    return None, converted


def _screen_rules(
    rules, concept_id: str, value_numeric: float | None, unit: str | None,
    age_years: float | None, patient_sex: str | None, clinical_context: dict[str, object],
    vendor_high: float | None,
) -> tuple[list[tuple[sqlite3.Row, dict[str, object], float | None]], str | None, bool, bool]:
    """(candidates, first block reason, a band was for another sex, a gated band applied)."""
    blocked: str | None = None
    sex_skipped = False
    gated_applied = False
    candidates: list[tuple[sqlite3.Row, dict[str, object], float | None]] = []
    for rule in rules:
        context = _rule_context(rule["context_json"])
        gate = _gate_rule(context, clinical_context)
        gated_applied = gated_applied or gate == _GATE_APPLIES
        if gate in (None, _GATE_APPLIES):
            miss = _rule_miss(rule, context, patient_sex, age_years, vendor_high)
        else:
            miss = gate
        converted = None
        if miss is None:
            miss, converted = _converted_for(rule, concept_id, value_numeric, unit)
        if miss is None:
            candidates.append((rule, context, converted))
            continue
        sex_skipped = sex_skipped or miss == _RULE_OTHER_SEX
        if miss not in (_RULE_SKIP, _RULE_OTHER_SEX):
            blocked = blocked or miss
    return candidates, blocked, sex_skipped, gated_applied


def _patient_sex(sex: str | None) -> str | None:
    patient_sex = (sex or "").strip().casefold() or None
    if patient_sex in {"unknown", ""}:
        return None
    return patient_sex


def _curated_verdict(
    rules,
    concept_id: str,
    value_numeric: float | None,
    value_text: str | None,
    unit: str | None,
    age_years: float | None,
    sex: str | None,
    *,
    clinical_context: dict[str, object] | None = None,
    vendor_high: float | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    if not rules:
        return None, None
    clinical_context = clinical_context or {}
    candidates, blocked, sex_skipped, gated_applied = _screen_rules(
        rules, concept_id, value_numeric, unit, age_years, _patient_sex(sex), clinical_context, vendor_high
    )

    if not candidates:
        if blocked is None and sex_skipped:
            # Every published band is for another sex: an intersex profile on
            # an all-sexed concept must read as "the guidance does not cover
            # this sex", never as "nothing is published".
            blocked = "sex_not_covered"
        return None, blocked

    risk = clinical_context if gated_applied else None
    # Bodies that deliberately set no number travel as positions; only when
    # every applicable body declines is the value itself left unjudged.
    declining = [item for item in candidates if item[0]["interpretation"] == _NO_UNIVERSAL_TARGET]
    top = candidates[0][0]
    if len(declining) == len(candidates):
        return (
            _verdict(
                "unjudged",
                "curated",
                band_label=top["label"],
                reason=_NO_UNIVERSAL_TARGET,
                no_universal_target=True,
                note=top["notes"],
                **_rule_source(top),
            ),
            blocked,
        )

    candidates = [item for item in candidates if item not in declining]
    if value_numeric is None:
        return _text_verdict(candidates, value_text), blocked
    return _numeric_verdict(candidates, declining, risk), blocked


def _numeric_verdict(candidates, declining, risk: dict[str, object] | None) -> dict[str, object] | None:
    """Judge a number against the candidate bands that carry bounds."""
    # A band with no bounds states an expected qualitative result ("negative -
    # the expected dipstick result"). It must never swallow a numeric value,
    # or a reactive serology index would be reported as negative.
    numeric_rules = [
        item
        for item in candidates
        if item[2] is not None
        and (item[0]["lower_bound"] is not None or item[0]["upper_bound"] is not None)
    ]
    if not numeric_rules:
        return None
    containing = [
        item
        for item in numeric_rules
        if _contains(
            item[2],
            item[0]["lower_bound"],
            item[0]["upper_bound"],
            bool(item[0]["lower_inclusive"]),
            bool(item[0]["upper_inclusive"]),
        )
    ]
    match = min(containing, key=_band_rank) if containing else None
    rule, _context, converted = match or numeric_rules[0]
    low, high = rule["lower_bound"], rule["upper_bound"]
    positions = _authority_positions(containing + declining)
    if match is not None:
        interpretation = rule["interpretation"]
    elif low is not None and converted < low:
        interpretation = "low"
    else:
        interpretation = "high"
    return _verdict(
        interpretation,
        "curated",
        band_label=rule["label"],
        low=low,
        high=high,
        low_inclusive=bool(rule["lower_inclusive"]),
        high_inclusive=bool(rule["upper_inclusive"]),
        unit=rule["unit"],
        value=converted,
        note=rule["notes"],
        **_target_fields(_target_band(match, numeric_rules)),
        authority_positions=positions,
        risk_context=risk,
        **_rule_source(rule),
    )


def _target_fields(target) -> dict[str, object]:
    """The ``_verdict`` keywords naming the band the bar shades; none without one."""
    if not target:
        return {}
    return {
        "target_low": target[0]["lower_bound"],
        "target_high": target[0]["upper_bound"],
        "target_inclusive": (bool(target[0]["lower_inclusive"]), bool(target[0]["upper_inclusive"])),
        "target_source": {**_rule_source(target[0]), "band_label": target[0]["label"]},
    }


def _target_band(match, numeric_rules):
    """The band the bar shades: the interval the reader should be in.

    * A benign match is its own target -- a result inside "Not low ≥1.0" is not
      "outside the target ≥1.55", and a benign chip beside "above target" is a
      contradiction.
    * Otherwise, when a goal for this person's own risk category applies, that
      goal (the library lists the current one first).
    * Otherwise the healthy band of the body whose band judged the value, then
      of any body -- the loosest, a plain reference interval ahead of an
      aspirational "optimal" sub-band. A band that contains the value is never
      the target of an abnormal verdict ("Above range" over "inside the target
      interval" is the contradiction this replaces), and a risk-gated goal is
      never chosen here.
    """
    if match is not None and match[0]["interpretation"] in BENIGN_INTERPRETATIONS:
        return match
    benign = [item for item in numeric_rules if item[0]["interpretation"] in BENIGN_INTERPRETATIONS]
    goals = [item for item in benign if _is_gated(item[1])]
    if goals:
        return max(goals, key=lambda item: int(item[0]["priority"] or 0))
    population = [
        item for item in benign
        if not _is_gated(item[1])
        and not _contains(
            item[2], item[0]["lower_bound"], item[0]["upper_bound"],
            bool(item[0]["lower_inclusive"]), bool(item[0]["upper_inclusive"]),
        )
    ]
    if match is not None:
        own = [item for item in population if item[0]["reference_set_id"] == match[0]["reference_set_id"]]
        population = own or population
    if not population:
        return None
    return min(
        population,
        key=lambda item: (
            item[0]["interpretation"] != "normal",
            -_looseness(item[0])[0],
            -_looseness(item[0])[1],
        ),
    )


#: Ukrainian result wording folded to its English equivalent, so a curated
#: ``expected_text`` written in English still matches a Ukrainian report.
_ENGLISH_VALUE_KEYS = {
    normalized_key(ukrainian): normalized_key(english)
    for ukrainian, english in VALUE_TRANSLATIONS.items()
}


def _text_keys(text: str | None) -> set[str]:
    key = normalized_key(text or "")
    if not key:
        return set()
    return {key, _ENGLISH_VALUE_KEYS.get(key, key)}


#: Wordings that mean the same qualitative outcome.  This is a language
#: mapping, not a clinical one: a band that declares the expected result is
#: "negative" is satisfied by a report that prints "not detected".
_INTERPRETATION_WORDS = {
    "negative": ("negative", "not detected", "non reactive", "nonreactive", "absent"),
    "positive": ("positive", "detected", "reactive"),
}


def _expected_keys(rule, context) -> set[str]:
    texts = context.get("expected_text") or _INTERPRETATION_WORDS.get(
        rule["interpretation"], ()
    )
    return {item for text in texts for item in _text_keys(str(text))}


def _text_verdict(candidates, value_text: str | None) -> dict[str, object] | None:
    """Compare a qualitative result against the expected values of each band."""
    expecting = [
        item
        for item in candidates
        if item[1].get("expected_text") or item[0]["interpretation"] in _INTERPRETATION_WORDS
    ]
    if not expecting:
        return None
    keys = _text_keys(value_text)
    if not keys:
        return _verdict("unjudged", "none", reason="no_value")
    for rule, context, _ in expecting:
        expected = _expected_keys(rule, context)
        if any(item and any(item == key or item in key for key in keys) for item in expected):
            return _verdict(
                rule["interpretation"],
                "curated",
                band_label=rule["label"],
                note=rule["notes"],
                **_rule_source(rule),
            )
    authored = [item for item in expecting if item[1].get("expected_text")]
    if not authored:
        # The expected wording was inferred from the band's interpretation, so
        # a non-match proves nothing.  Let the laboratory's own report speak.
        return None
    rule = authored[0][0]
    return _verdict(
        "indeterminate",
        "curated",
        band_label=rule["label"],
        note=rule["notes"],
        reason="unexpected_value",
        **_rule_source(rule),
    )


def _vendor_verdict(
    value_numeric: float | None,
    unit: str | None,
    vendor_low: float | None,
    vendor_high: float | None,
    vendor_interpretation: str | None,
) -> dict[str, object]:
    interpretation = _VENDOR_INTERPRETATIONS.get(vendor_interpretation or "")
    if vendor_low is None and vendor_high is None and interpretation is None:
        return _verdict("unjudged", "none", reason="no_rule")
    if interpretation is None and value_numeric is not None:
        # The laboratory printed an interval but no flag of its own, so compare
        # against it here.  ``pipeline.interpretation`` does this at ingest and
        # stores the answer, but it only ever sees bounds the parser accepted:
        # a demographically-qualified range ("чоловіки < 11.2") is refused
        # there and recovered later by applicable_reference_bounds().  Without
        # this the recovered interval was recorded, displayed, and never
        # actually compared to anything -- a urinary leukocyte count of 107.6
        # sat beside its own printed limit of 11.2 and reported "no comparison
        # available".
        value = float(value_numeric)
        if vendor_high is not None and value > vendor_high:
            interpretation = "high"
        elif vendor_low is not None and value < vendor_low:
            interpretation = "low"
        else:
            interpretation = "normal"
    if interpretation is None:
        interpretation = "unjudged"
    return _verdict(
        interpretation,
        "vendor",
        band_label=None,
        low=vendor_low,
        high=vendor_high,
        unit=unit,
        value=float(value_numeric) if value_numeric is not None else None,
    )


# --- curated prose ---------------------------------------------------------


def guidance(connection: sqlite3.Connection, concept_id: str) -> dict[str, object] | None:
    """Curated prose for a concept, in the active locale where a translation exists.

    Falls back to English per field rather than per record, so a partially
    translated entry still shows everything it has instead of reverting whole.
    """
    row = connection.execute(
        """SELECT g.concept_id, g.short_description, g.why_it_matters,
                  g.retest_interval_months, g.retest_rationale, g.panel_id,
                  g.source_id, g.short_description_uk, g.why_it_matters_uk,
                  g.retest_rationale_uk, g.name_uk,
                  s.name AS source_name, s.source_url
           FROM concept_guidance g
           LEFT JOIN reference_sets s ON s.id = g.source_id
           WHERE g.concept_id = ?""",
        (concept_id,),
    ).fetchone()
    return localised_guidance(dict(row)) if row else None


def localised_guidance(item: dict[str, object]) -> dict[str, object]:
    """Swap the curated prose for its translation, field by field.

    Every reader of ``concept_guidance`` goes through here.  The web layer reads
    the whole table at once rather than a row at a time, and when it did the
    substitution itself the Ukrainian columns were simply never consulted: a
    fully translated analyte still explained itself in English.
    """
    if get_locale() != "uk":
        return item
    for field in ("short_description", "why_it_matters", "retest_rationale"):
        translated = item.get(f"{field}_uk")
        if translated:
            item[field] = translated
    return item


def sources_for(connection: sqlite3.Connection, concept_ids) -> list[dict[str, object]]:
    """Reference sets cited by any curated rule for these concepts."""
    ids = list(dict.fromkeys(concept_ids))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"""SELECT DISTINCT s.id, s.name, s.publisher, s.source_url AS url, s.reviewed_at, s.notes
            FROM reference_sets s
            JOIN curated_reference_rules r ON r.reference_set_id = s.id
            WHERE r.concept_id IN ({placeholders})
            ORDER BY s.publisher, s.name""",
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


# --- library loader --------------------------------------------------------

LIBRARY_PATH = resource_path("reference_library.json")
_LIBRARY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"{ID_NAMESPACE_PREFIX}/reference-library")


def load_library(path: Path | None = None) -> dict:
    return json.loads((path or LIBRARY_PATH).read_text(encoding="utf-8"))


def _rule_id(
    set_id: str,
    concept_id: str,
    label: str,
    sex: str | None = None,
    age_min: object = None,
    age_max: object = None,
) -> str:
    """Stable id for one band.

    The demographic qualifiers are part of the identity. Without them a
    publisher that uses the same wording for both sexes -- WHO writes "Severe
    anaemia" for men and women alike -- produces one id for two different
    bands, and the second silently overwrites the first on load. That is how
    haemoglobin lost its entire male reference interval and started reporting a
    healthy 146 g/L as high.
    """
    key = f"rule:{set_id}:{concept_id}:{label}:{sex or 'any'}:{age_min}:{age_max}"
    return str(uuid.uuid5(_LIBRARY_NAMESPACE, key))


def _first(mapping: dict, *keys, default=None):
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return default


def _prune(connection: sqlite3.Connection, table: str, key: str, keep: list[str]) -> None:
    """Delete curated rows the library no longer describes.

    Goes through a temporary table rather than a NOT IN list: the allergen
    class scale alone expands past SQLite's bound-parameter limit.
    """
    if not keep:
        connection.execute(f"DELETE FROM {table}")
        return
    connection.execute("CREATE TEMP TABLE IF NOT EXISTS _library_keep(id TEXT PRIMARY KEY)")
    connection.execute("DELETE FROM _library_keep")
    connection.executemany("INSERT OR IGNORE INTO _library_keep(id) VALUES (?)", [(k,) for k in keep])
    connection.execute(f"DELETE FROM {table} WHERE {key} NOT IN (SELECT id FROM _library_keep)")


def _library_targets(connection: sqlite3.Connection, analyte: dict, named: set[str]) -> list[str]:
    """Concepts an analyte entry applies to.

    An entry whose id starts with ``_`` is a template covering every concept in
    its panel's dynamic categories - the CAP class scale is one published
    scale, not 295 separate ones - minus any concept with its own entry.
    """
    concept_id = analyte["concept_id"]
    if not concept_id.startswith("_"):
        # A device key that is the same measurement (`MEASUREMENT_TWINS`) is
        # judged by the concept's one entry: two copies of a library entry
        # drifted apart once already, one citing a Ukrainian source the other
        # never gained.
        return [concept_id, *device_twins(concept_id, "same")]
    panel = PANEL_BY_ID.get(str(analyte.get("panel") or ""))
    if panel is None or not panel.member_categories:
        return []
    placeholders = ",".join("?" for _ in panel.member_categories)
    rows = connection.execute(
        f"SELECT id FROM concepts WHERE category IN ({placeholders}) ORDER BY id",
        panel.member_categories,
    ).fetchall()
    return [row["id"] for row in rows if row["id"] not in named]


_UPSERT_RULE_SQL = """INSERT INTO curated_reference_rules(
                   id, reference_set_id, concept_id, label, context_json, unit,
                   lower_bound, upper_bound, lower_inclusive, upper_inclusive,
                   interpretation, priority, notes, sex, age_min_years, age_max_years,
                   label_uk, corroborated_by, agreement, divergence_note, notes_uk
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   reference_set_id=excluded.reference_set_id, label=excluded.label,
                   context_json=excluded.context_json, unit=excluded.unit,
                   lower_bound=excluded.lower_bound, upper_bound=excluded.upper_bound,
                   lower_inclusive=excluded.lower_inclusive,
                   upper_inclusive=excluded.upper_inclusive,
                   interpretation=excluded.interpretation, priority=excluded.priority,
                   notes=excluded.notes, sex=excluded.sex,
                   age_min_years=excluded.age_min_years,
                   age_max_years=excluded.age_max_years,
                   label_uk=excluded.label_uk,
                   corroborated_by=excluded.corroborated_by,
                   agreement=excluded.agreement,
                   divergence_note=excluded.divergence_note,
                   notes_uk=excluded.notes_uk"""


def _band_context(analyte: dict, band: dict) -> dict[str, object]:
    context = {
        "kind": analyte.get("kind"),
        **(analyte.get("context") or {}),
        **(band.get("context") or {}),
    }
    if band.get("requires"):
        context["requires"] = band["requires"]
    if band.get("expected_text"):
        context["expected_text"] = list(band["expected_text"])
    return {k: v for k, v in context.items() if v is not None}


def _band_values(
    analyte: dict, band: dict, index: int, band_count: int, concept_id: str
) -> tuple[str, tuple]:
    """(rule id, the ``_UPSERT_RULE_SQL`` parameters) for one band."""
    uk = analyte.get("uk") or {}
    uk_labels = uk.get("band_labels") or {}
    uk_notes = uk.get("band_notes") or {}
    set_id = band.get("source_id") or analyte.get("source_id")
    label = band.get("label") or f"{analyte.get('kind', 'band')} {index + 1}"
    # "any" is how the library spells "applies to everyone"; the matcher
    # reads NULL as unrestricted and an exact string as a requirement.
    band_sex = (band.get("sex") or "").strip().casefold() or None
    age_min = _first(band, "age_min", "age_min_years")
    age_max = _first(band, "age_max", "age_max_years")
    rule_id = _rule_id(set_id, concept_id, label, band_sex, age_min, age_max)
    return rule_id, (
        rule_id,
        set_id,
        concept_id,
        label,
        json.dumps(_band_context(analyte, band)),
        band["unit"] if "unit" in band else analyte.get("unit"),
        band.get("lower"),
        band.get("upper"),
        int(band.get("lower_inclusive", True)),
        int(band.get("upper_inclusive", True)),
        band["interpretation"],
        int(band.get("priority", (band_count - index) * 10)),
        band.get("note") or analyte.get("note"),
        None if band_sex in {None, "any", "all"} else band_sex,
        age_min,
        age_max,
        uk_labels.get(band.get("label") or ""),
        json.dumps(band["corroborated_by"]) if band.get("corroborated_by") else None,
        analyte.get("agreement"),
        analyte.get("divergence_note"),
        # A band's own note first, then the analyte-wide one -- the
        # same fallback the English column uses.  The library writes
        # most band translations beside the note itself (`notes_uk`);
        # reading only `uk.band_notes` left 327 of them unseeded, and a
        # Ukrainian page fell back to the English note.
        band.get("notes_uk") or uk_notes.get(band.get("label") or "") or uk.get("note"),
    )


def _seed_analyte(
    connection: sqlite3.Connection, analyte: dict, concept_id: str, now: str
) -> list[str]:
    """Write one analyte's bands and guidance.  Returns the rule ids written."""
    analyte_set = analyte.get("source_id")
    bands = analyte.get("bands") or []
    # Curated prose and band labels translated by the category researchers. A
    # Ukrainian reader saw English descriptions under a Ukrainian interface
    # until these were carried through.
    uk = analyte.get("uk") or {}
    rule_ids: list[str] = []
    for index, band in enumerate(bands):
        rule_id, values = _band_values(analyte, band, index, len(bands), concept_id)
        rule_ids.append(rule_id)
        connection.execute(_UPSERT_RULE_SQL, values)
    row = connection.execute(
        "SELECT category FROM concepts WHERE id=?", (concept_id,)
    ).fetchone()
    panel = panel_for_concept(concept_id, row["category"] if row else None)
    connection.execute(
        """INSERT INTO concept_guidance(
               concept_id, short_description, why_it_matters, retest_interval_months,
               retest_rationale, panel_id, source_id, updated_at,
               short_description_uk, why_it_matters_uk, retest_rationale_uk, name_uk,
               retest_condition_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(concept_id) DO UPDATE SET
               short_description=excluded.short_description,
               why_it_matters=excluded.why_it_matters,
               retest_interval_months=excluded.retest_interval_months,
               retest_rationale=excluded.retest_rationale,
               panel_id=excluded.panel_id, source_id=excluded.source_id,
               updated_at=excluded.updated_at,
               short_description_uk=excluded.short_description_uk,
               why_it_matters_uk=excluded.why_it_matters_uk,
               retest_rationale_uk=excluded.retest_rationale_uk,
               retest_condition_json=excluded.retest_condition_json,
               -- The prose columns above are JSON-authoritative: clearing a
               -- translation in the library must clear it here too. name_uk
               -- cannot be, because the 295 allergens are seeded from ONE
               -- shared `_allergen_specific_ige` template that has no
               -- per-concept name slot, so `uk.get("name")` is always None for
               -- them and an unconditional assignment wiped all 295 rows on
               -- every app start. COALESCE keeps a name the library cannot
               -- express; a library that does supply one still wins.
               name_uk=COALESCE(excluded.name_uk, concept_guidance.name_uk)""",
        (
            concept_id,
            analyte.get("short_description"),
            analyte.get("why_it_matters"),
            analyte.get("retest_interval_months"),
            analyte.get("retest_rationale"),
            panel.id if panel else analyte.get("panel"),
            analyte_set or (bands[0].get("source_id") if bands else None),
            now,
            uk.get("short_description"),
            uk.get("why_it_matters"),
            uk.get("retest_rationale"),
            uk.get("name"),
            json.dumps(analyte["retest_condition"]) if analyte.get("retest_condition") else None,
        ),
    )
    return rule_ids


def seed_reference_library(
    connection: sqlite3.Connection, library: dict | None = None
) -> dict[str, int]:
    """Load ``data/reference_library.json`` into the curated tables.

    Idempotent: ids are ``uuid5`` of the natural key, so re-seeding updates in
    place, and anything the library no longer describes is pruned.  The JSON is
    the only source of truth for curated guidance.
    """
    library = library or load_library()
    invalidate_rule_cache()
    now = utc_now()
    set_ids: list[str] = []
    rule_ids: list[str] = []
    concept_ids: list[str] = []

    for source in library.get("sources", []):
        set_ids.append(source["id"])
        connection.execute(
            """INSERT INTO reference_sets(
                   id, name, publisher, jurisdiction, version, effective_from,
                   effective_to, source_url, reviewed_at, notes, region, official
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, publisher=excluded.publisher,
                   jurisdiction=excluded.jurisdiction, version=excluded.version,
                   effective_from=excluded.effective_from, effective_to=excluded.effective_to,
                   source_url=excluded.source_url, reviewed_at=excluded.reviewed_at,
                   notes=excluded.notes, region=excluded.region,
                   official=excluded.official""",
            (
                source["id"],
                source["name"],
                source["publisher"],
                source.get("jurisdiction") or source.get("kind"),
                # The library's own edition where it states one, otherwise the
                # date this record was reviewed against the publication.
                _first(source, "version", "reviewed_at", default=now[:10]),
                source.get("effective_from"),
                source.get("effective_to"),
                _first(source, "url", "source_url", default=""),
                _first(source, "reviewed_at", default=now[:10]),
                source.get("notes"),
                source.get("region"),
                None if source.get("official") is None else int(bool(source["official"])),
            ),
        )

    analytes = library.get("analytes", [])
    named = {item["concept_id"] for item in analytes}
    for analyte in analytes:
        for concept_id in _library_targets(connection, analyte, named):
            concept_ids.append(concept_id)
            rule_ids.extend(_seed_analyte(connection, analyte, concept_id, now))

    _prune(connection, "curated_reference_rules", "id", rule_ids)
    _prune(connection, "concept_guidance", "concept_id", concept_ids)
    _prune(connection, "reference_sets", "id", set_ids)
    return {"sources": len(set_ids), "rules": len(rule_ids), "guidance": len(concept_ids)}
