"""Undated current estimates from explicitly entered profile measurements.

A profile has no measurement date. Its current weight can support a BMI
estimate, but never a historical observation or a point dated to today.
The caller decides where to show the estimate alongside dated measurements.
"""

from __future__ import annotations

from datetime import date, datetime

from .devices.units import convert_quantity, finite_number, is_plausible
from .health import age_on
from .reference import canonical_unit

PROFILE_BMI_METHOD = "derived_profile_bmi"
BMI_SOURCE_URL = "https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html"


def profile_bmi(patient, measured=None, *, today: date | None = None) -> dict | None:
    """Return a provisional, explicitly undated BMI for a manual profile weight.

    ``patient`` is a profile dict or SQLite Row: ``weight_kg`` and ``height_cm``
    are already in their named units. ``measured`` follows the web profile's
    measured-body contract, whose ``height_cm`` entry has ``value``, ``day``
    and ``source``. A dated height may be carried into an undated estimate
    only if it is not in the future and the person was already an adult at
    that measurement. This is a conservative reuse policy, not a claim that
    adults' heights never change. An optional explicit ``unit`` is converted physically;
    without one, that named field is centimetres. A measured weight belongs
    to the dated device calculation path and suppresses this estimate.

    Inputs are returned in the same shape as device calculation provenance.
    An input's date never becomes a measurement date for the undated weight.
    No input is mutated, persisted or labelled verified by this function.
    """
    if patient is None:
        return None
    patient = dict(patient)
    measured = dict(measured or {})
    if "weight_kg" in measured:
        return None
    weight = finite_number(patient.get("weight_kg"))
    if not is_plausible("body_weight", weight):
        return None

    patient_id = patient.get("id")
    weight_input = {
        "input_kind": "profile_weight", "input_id": patient_id,
        "input_day": None, "input_value": weight, "input_unit": "kg", "input_source": None,
    }
    if "height_cm" in measured:
        reading = dict(measured["height_cm"] or {})
        if reading.get("ambiguous"):
            return None
        for field in ("patient_id", "owner_user_id"):
            if reading.get(field) is not None and reading[field] != patient.get("id" if field == "patient_id" else field):
                return None
        try:
            written_day = str(reading.get("day"))
            height_day = (date.fromisoformat(written_day) if len(written_day) == 10 else
                          datetime.fromisoformat(written_day.replace("Z", "+00:00")).date())
            born = date.fromisoformat(str(patient.get("date_of_birth")))
        except ValueError:
            return None
        current = today if today is not None else date.today()
        if height_day > current or (age_on(born.isoformat(), height_day.isoformat()) or 0) < 20:
            return None
        input_kind = reading.get("input_kind", "device_height")
        if input_kind not in {"device_height", "observation_height"}:
            return None
        if input_kind == "observation_height" and (
            reading.get("verification_status") not in {"verified", "corrected"}
            or reading.get("comparator")
            or str(reading.get("extraction_method") or "").startswith("derived_")
        ):
            return None
        unit = canonical_unit(reading.get("unit", "cm"))
        try:
            height = convert_quantity(finite_number(reading.get("value")), unit, "cm") if unit else None
        except ValueError:
            return None
        height_input = {
            "input_kind": input_kind, "input_id": reading.get("id"),
            "input_day": height_day.isoformat(), "input_value": height,
            "input_unit": "cm", "input_source": reading.get("source"),
        }
    else:
        height = finite_number(patient.get("height_cm"))
        height_input = {
            "input_kind": "profile_height", "input_id": patient_id,
            "input_day": None, "input_value": height, "input_unit": "cm", "input_source": None,
        }
    if not is_plausible("body_height", height):
        return None

    return {
        "value": round(weight / (height / 100) ** 2, 2),
        "unit": "kg/m²", "method": PROFILE_BMI_METHOD, "extraction_method": PROFILE_BMI_METHOD,
        "observed_at": None, "day": None, "verification_status": "extracted",
        "source_url": BMI_SOURCE_URL, "calculation_inputs": [weight_input, height_input],
    }
