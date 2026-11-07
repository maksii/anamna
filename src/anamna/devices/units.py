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


#: Physically possible values for a body measurement, open interval, in the
#: catalog unit.  The first three are exactly the `patients` CHECK constraints
#: (migrations/016) so a device value and a typed value face one rule; the
#: percentage is bounded by its definition.  These are not reference ranges:
#: they reject numbers no human body can produce, nothing else.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "body_height": (30.0, 280.0),
    "body_weight": (1.0, 700.0),
    "waist_circumference": (20.0, 300.0),
    "lean_body_mass": (1.0, 700.0),
    "body_fat_percentage": (0.0, 100.0),
    # A night, in hours: up to 16 h (the cut-off the Oura export already used,
    # OPS-04).  A manual Apple Health entry of 21 h arrived through the bridge
    # as a "night"; zero stays possible (a missing night is handled elsewhere).
    "sleep_duration": (-1e-9, 16.0 + 1e-9),
    "time_in_bed": (-1e-9, 16.0 + 1e-9),
    "sleep_core": (-1e-9, 16.0 + 1e-9),
    "sleep_deep": (-1e-9, 16.0 + 1e-9),
    "sleep_rem": (-1e-9, 16.0 + 1e-9),
    "sleep_awake": (-1e-9, 16.0 + 1e-9),
}
_CENTIMETRE_KEYS = frozenset({"body_height", "waist_circumference"})


def plausible_value(metric_key: str, value: float | None) -> float | None:
    """The value to store, or None when no body could have produced it.

    One recovery is made, and only one: a centimetre measurement that is
    impossible as centimetres but possible as metres (OpenWearables served a
    99 cm waist as `0.99` labelled `cm`) is the metre value it evidently is.
    """
    if value is None:
        return None
    bounds = PLAUSIBLE_RANGES.get(metric_key)
    if bounds is None:
        return value
    low, high = bounds
    if low < value < high:
        return value
    if metric_key in _CENTIMETRE_KEYS and low < value * 100 < high:
        return value * 100
    return None


def is_plausible(metric_key: str, value: object) -> bool:
    bounds = PLAUSIBLE_RANGES.get(metric_key)
    number = finite_number(value)
    if number is None:
        return False
    return bounds is None or bounds[0] < number < bounds[1]


def _rescale(item, scale: float) -> None:
    item.value_latest = item.value_latest * scale if item.value_latest is not None else None
    item.value_sum *= scale
    item.value_min = item.value_min * scale if item.value_min is not None else None
    item.value_max = item.value_max * scale if item.value_max is not None else None


def plausible_aggregates(aggregates):
    """Aggregates fit to store: implausible body values dropped, metres-as-cm
    rescaled.  Every device writer passes its aggregates through here."""
    kept = []
    for item in aggregates:
        if not item.sample_count:
            continue  # every sample of it was excluded as not this person's
        key = item.definition.key
        if key not in PLAUSIBLE_RANGES:
            kept.append(item)
            continue
        value = plausible_value(key, item.value)
        if value is None:
            continue
        if value != item.value:
            _rescale(item, value / item.value)
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
