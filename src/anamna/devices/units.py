"""Explicit physical-unit conversion at device import boundaries."""
from __future__ import annotations

import math


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


# Each dimension is expressed in one base unit. Factors are exact definitions,
# not physiological assumptions or reference thresholds.
_DIMENSIONS = (
    {"kg": 1, "g": .001, "mg": .000001, "lb": .45359237, "oz": .028349523125, "st": 6.35029318},
    {"m": 1, "cm": .01, "mm": .001, "km": 1000, "in": .0254, "ft": .3048, "yd": .9144, "mi": 1609.344},
    {"s": 1, "ms": .001, "min": 60, "h": 3600, "hours": 3600},
    {"kcal": 1, "Cal": 1, "cal": .001, "kJ": 1 / 4.184, "J": 1 / 4184},
    {"m/s": 1, "km/h": 1 / 3.6, "mi/hr": .44704, "mi/h": .44704, "mph": .44704, "ft/s": .3048},
    {"mmHg": 1, "kPa": 1000 / 133.322387415},
)
_ML_KG_MIN = "mL/kg/min"
_ALIASES = {
    "count/min": "bpm", "breaths/min": "bpm", "dBASPL": "dBA",
    "degC": "°C", "degF": "°F", "kg/m^2": "kg/m²", "mL/min·kg": _ML_KG_MIN,
    "ml/kg/min": _ML_KG_MIN, "ml/(kg*min)": _ML_KG_MIN,
    "steps": "count", "flights": "count", "MET-like effort": "kcal/hr·kg",
    "km/hr": "km/h", "kg/m2": "kg/m²",
}


#: Existing application input bounds, in the catalog unit. The first three
#: match `patients` CHECK constraints (migration016); percentage is bounded
#: by its definition. These are product validation limits, not medical
#: reference intervals or proof of universal physiological impossibility.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "body_height": (30.0, 280.0),
    "body_weight": (1.0, 700.0),
    "waist_circumference": (20.0, 300.0),
    "lean_body_mass": (1.0, 700.0),
    "body_fat_percentage": (0.0, 100.0),
}
NONNEGATIVE_SLEEP_KEYS = frozenset({
    "sleep_duration", "time_in_bed", "sleep_core", "sleep_deep", "sleep_rem", "sleep_awake",
})
#: A day holds 24 hours. This is the only upper bound on a night: a manual
#: entry spanning a week is not sleep, a 20-hour one may be.
MAX_SLEEP_HOURS = 24.0


def plausible_value(metric_key: str, value: float | None) -> float | None:
    """The value to store, or None when it fails the existing input bounds.

    The caller already converted explicit units. A suspicious magnitude is
    not evidence that a source labelled centimetres actually meant metres.
    """
    if value is None:
        return None
    if metric_key in NONNEGATIVE_SLEEP_KEYS:
        return value if 0 <= value <= MAX_SLEEP_HOURS else None
    bounds = PLAUSIBLE_RANGES.get(metric_key)
    if bounds is None:
        return value
    low, high = bounds
    if low < value < high:
        return value
    return None


def is_plausible(metric_key: str, value: object) -> bool:
    bounds = PLAUSIBLE_RANGES.get(metric_key)
    number = finite_number(value)
    if number is None:
        return False
    if metric_key in NONNEGATIVE_SLEEP_KEYS:
        return 0 <= number <= MAX_SLEEP_HOURS
    return bounds is None or bounds[0] < number < bounds[1]


def plausible_aggregates(aggregates):
    """Aggregates fit to store, without inferring a replacement source unit."""
    kept = []
    for item in aggregates:
        if not item.sample_count:
            continue  # every sample of it was excluded as not this person's
        key = item.definition.key
        if key not in PLAUSIBLE_RANGES and key not in NONNEGATIVE_SLEEP_KEYS:
            kept.append(item)
            continue
        value = plausible_value(key, item.value)
        if value is None:
            continue
        kept.append(item)
    return kept


def convert_quantity(value: float | None, source_unit: str, target_unit: str) -> float | None:
    """Convert compatible quantities; never relabel an unknown unit.

    A missing unit preserves the adapter's existing documented field contract.
    Explicit units always override that contract.
    """
    if value is None:
        return None
    source = _ALIASES.get(source_unit.strip(), source_unit.strip())
    target = _ALIASES.get(target_unit, target_unit)
    if not source or source == target:
        return value
    if target == "°C" and source == "°F":
        return (value - 32) * 5 / 9
    if target == "°C" and source == "K":
        return value - 273.15
    for dimension in _DIMENSIONS:
        if source in dimension and target in dimension:
            return value * dimension[source] / dimension[target]
    raise ValueError(f"Unsupported device unit {source_unit!r} for {target_unit!r}")
