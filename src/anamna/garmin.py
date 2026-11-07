"""Garmin Health API (Connect Developer Program, Starter/Enterprise tiers).

`integrations.py` owns getting connected (OAuth2 + PKCE, webhook receipt);
this module owns what a business-tier connection is *for* — taking every
summary Garmin delivers and landing it in the same device tables the file
importers write, so /devices, trends, source-priority resolution and reference
evaluation all apply unchanged. The Personal API (one person's own key, pull
only) lives in `garmin_personal.py` and reuses the mapping and writers here.

Garmin is push-first, and ad-hoc pulls are forbidden: summary endpoints may
only be called from a ping's callback URL. So the windowed recompute that
oura.py runs against the provider runs here against a local mirror
(`garmin_summaries`):

1. the webhook stores the raw delivery in ``provider_events`` and answers 200;
2. :func:`process_pending` resolves pings (fetching their callback URL),
   upserts every summary into the mirror — the latest copy wins — and notes
   which (type, day) pairs it touched;
3. each touched (type, day) is rebuilt from *all* mirrored summaries of that
   type and day, upserted, and this envelope's rows the rebuild no longer
   produces are deleted.

Redeliveries, revisions and out-of-order arrival converge on the same rows.
History arrives the same way: :func:`request_backfill` asks Garmin to replay
the last month, which then comes back through the webhook like any push.

Deregistration and withdrawn permissions are Garmin's to announce
(`deregistrations`, `userPermissionsChange`). Both delete the connection's
Garmin-delivered data for the affected scope, and the profile says so.

Summary types kept as raw archive only (they stay in ``provider_events``):
`epochs` and `activityDetails` are intraday samples whose daily totals arrive
in `dailies`/`activities`; `activityFiles` are FIT downloads; `healthSnapshot`
is a two-minute spot check duplicating fields mapped from their own
summaries. Field names: Garmin Health API 1.2.2 and Activity API 1.2.3,
verified 2026-11-05 — see docs/provider-integrations.md.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable
from typing import Any
from datetime import timedelta, timezone, datetime

from . import integrations
from .config import Settings, log_run
from .db import connect, transaction, utc_now
from .devices import exclusions
from .devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS, metric
from .devices.models import Aggregate, DeviceEvent, MetricDefinition, Workout
from .devices.units import convert_quantity, finite_number
from .ingest.pipeline import ensure_vendor, stable_id
from .integrations import IntegrationError

logger = logging.getLogger("anamna.garmin")

PROVIDER = integrations.PROVIDERS["garmin"]
API_HOST = "apis.garmin.com"
WELLNESS = f"https://{API_HOST}/wellness-api/rest"
SOURCE_NAME = "Garmin"
#: The file importer files blood pressure and scale readings under these
#: names; the APIs use the same ones so a reading present in both lands on one
#: natural key instead of showing twice.
BP_SOURCE_NAME = "Garmin Connect blood pressure"
SCALE_SOURCE_NAME = "Garmin Index Scale"
MANUAL_WEIGHT_SOURCE_NAME = "Garmin Connect user entry"
ADAPTER_KEY = "garmin_api"
EVENT_MOVE_IQ = "Garmin Move IQ"
#: Shared with openwearables.EVENT_CYCLE so cycles from either route read alike.
EVENT_CYCLE = "Menstrual cycle"

#: Garmin replays at most about one month of history per summary type, once
#: (Enterprise tier only); Health types accept 90 days per request and
#: activity types 30, so one 30-day window covers everything on offer.
BACKFILL_DAYS = 30


# --- what each summary type becomes ------------------------------------------

_BY_KEY = {d.key: d for d in {**HEALTHKIT_METRICS, **SLEEP_METRICS}.values()}


def _definition(key: str, name: str, category: str, unit: str, aggregation: str) -> MetricDefinition:
    """The catalog's definition when the key exists there — one spelling of
    name/unit/aggregation per key across every importer — else a new one."""
    return _BY_KEY.get(key) or metric(key, name, category, unit, aggregation)


DEFS = {
    key: _definition(key, name, category, unit, aggregation)
    for key, name, category, unit, aggregation in (
        ("steps", "Daily steps", "device_activity", "steps", "sum"),
        ("walking_running_distance", "Walking and running distance", "device_activity", "km", "sum"),
        ("flights_climbed", "Flights climbed", "device_activity", "flights", "sum"),
        ("active_energy", "Active energy", "device_activity", "kcal", "sum"),
        ("resting_energy", "Resting energy", "device_activity", "kcal", "sum"),
        ("active_minutes", "Active minutes", "device_activity", "min", "sum"),
        ("moderate_activity", "Moderate activity", "device_activity", "min", "sum"),
        ("vigorous_activity", "Vigorous activity", "device_activity", "min", "sum"),
        ("resting_heart_rate", "Resting heart rate", "device_recovery", "bpm", "average"),
        ("daily_heart_rate", "Daily heart rate", "device_recovery", "bpm", "average"),
        # Same keys and spellings as the Garmin file importer (structured.py).
        ("stress_level", "Average stress level", "device_recovery", "score", "latest"),
        ("body_battery_high", "Body Battery high", "device_recovery", "score", "latest"),
        ("body_battery_low", "Body Battery low", "device_recovery", "score", "latest"),
        ("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"),
        ("sleep_deep", "Deep sleep", "device_sleep", "hours", "sum"),
        ("sleep_rem", "REM sleep", "device_sleep", "hours", "sum"),
        ("sleep_core", "Core sleep", "device_sleep", "hours", "sum"),
        ("sleep_awake", "Awake during sleep", "device_sleep", "hours", "sum"),
        ("time_in_bed", "Time in bed", "device_sleep", "hours", "sum"),
        ("sleep_score", "Sleep score", "device_sleep", "score", "latest"),
        ("sleeping_heart_rate", "Average sleeping heart rate", "device_sleep", "bpm", "average"),
        # Garmin's HRV status is the overnight RMSSD, like Oura's — not the
        # SDNN quantity HealthKit exports under heart_rate_variability.
        ("heart_rate_variability_rmssd", "Heart rate variability (RMSSD)", "device_recovery", "ms", "average"),
        ("blood_oxygen", "Blood oxygen saturation", "device_recovery", "%", "average"),
        ("respiratory_rate", "Respiratory rate", "device_recovery", "breaths/min", "average"),
        ("temperature_deviation", "Temperature deviation", "device_recovery", "°C", "latest"),
        ("vo2_max", "Cardio fitness (VO₂ max)", "device_fitness", "mL/kg/min", "average"),
        ("fitness_age", "Fitness age", "device_fitness", "years", "latest"),
        ("body_weight", "Body weight", "device_body", "kg", "latest"),
        ("body_mass_index", "Body mass index", "device_body", "kg/m²", "latest"),
        ("body_fat_percentage", "Body fat", "device_body", "%", "latest"),
        ("body_water_percentage", "Body water", "device_body", "%", "latest"),
        ("bone_mass", "Bone mass", "device_body", "kg", "latest"),
        ("muscle_mass", "Muscle mass", "device_body", "kg", "latest"),
        ("systolic_blood_pressure", "Systolic blood pressure", "device_recovery", "mmHg", "latest"),
        ("diastolic_blood_pressure", "Diastolic blood pressure", "device_recovery", "mmHg", "latest"),
        ("blood_pressure_pulse", "Pulse during blood-pressure reading", "device_recovery", "bpm", "latest"),
    )
}

#: Types Garmin revises in place: one live copy per calendar day.
DAY_TYPES = frozenset({"dailies", "sleeps", "hrv", "stressDetails", "userMetrics", "skinTemp"})

#: Which metric keys each summary type owns — the delete scope of its
#: recompute. A key owned by two types would have each rebuild delete the
#: other's days.
TYPE_KEYS: dict[str, tuple[str, ...]] = {
    "dailies": (
        "steps", "walking_running_distance", "flights_climbed", "active_energy",
        "resting_energy", "moderate_activity", "vigorous_activity",
        "resting_heart_rate", "daily_heart_rate", "stress_level",
    ),
    "sleeps": ("sleep_duration", "sleep_deep", "sleep_rem", "sleep_core", "sleep_awake",
               "time_in_bed", "sleep_score"),
    "hrv": ("heart_rate_variability_rmssd",),
    "stressDetails": ("body_battery_high", "body_battery_low"),
    "userMetrics": ("vo2_max", "fitness_age"),
    "skinTemp": ("temperature_deviation",),
    "bodyComps": ("body_weight", "body_mass_index", "body_fat_percentage",
                  "body_water_percentage", "bone_mass", "muscle_mass"),
    "bloodPressures": ("systolic_blood_pressure", "diastolic_blood_pressure", "blood_pressure_pulse"),
    "pulseox": ("blood_oxygen",),
    "allDayRespiration": ("respiratory_rate",),
}

#: Types that become device_workouts / device_events instead of daily rows.
#: `manuallyUpdatedActivities` is folded into `activities` on arrival: an
#: edit made in Garmin Connect replaces the activity it edits.
WORKOUT_TYPES = frozenset({"activities"})
EVENT_TYPES = {"moveIQActivities": EVENT_MOVE_IQ, "mct": EVENT_CYCLE}
_ALIASES = {"manuallyUpdatedActivities": "activities"}

#: Delivered, archived in provider_events, deliberately not mirrored.
RETAINED_ONLY = frozenset({"epochs", "activityDetails", "activityFiles", "healthSnapshot"})

MIRRORED = frozenset(TYPE_KEYS) | WORKOUT_TYPES | frozenset(EVENT_TYPES)

#: Backfill endpoint per mirrored type (Garmin spells some differently from
#: their push keys). Garmin offers no backfill for Move IQ beyond `moveiq`.
BACKFILL_ENDPOINTS = {
    "dailies": "dailies", "sleeps": "sleeps", "hrv": "hrv", "stressDetails": "stressDetails",
    "userMetrics": "userMetrics", "skinTemp": "skinTemp", "bodyComps": "bodyComps",
    "bloodPressures": "bloodPressures", "pulseox": "pulseOx", "allDayRespiration": "respiration",
    "activities": "activities", "moveIQActivities": "moveiq", "mct": "mct",
}

#: Garmin permission -> the mirrored types it gates. Withdrawing one deletes
#: those types' data, keeping the rest.
PERMISSION_TYPES = {
    "ACTIVITY_EXPORT": frozenset(WORKOUT_TYPES | frozenset(EVENT_TYPES)),
    "HEALTH_EXPORT": frozenset(TYPE_KEYS),
    "MCT_EXPORT": frozenset({"mct"}),
}


# --- small parsing helpers ---------------------------------------------------


def num(value: object) -> float | None:
    return finite_number(value)


def local_time(seconds: object, offset: object) -> datetime | None:
    """A Garmin epoch + display offset as an aware local datetime."""
    start, shift = num(seconds), num(offset)
    if start is None:
        return None
    return datetime.fromtimestamp(start, tz=timezone(timedelta(seconds=int(shift or 0))))


def summary_day(summary: dict) -> str:
    """The local calendar day a summary belongs to — Garmin's own
    `calendarDate` (a cycle's `periodStartDate`) when it sends one, else the
    local date of its start."""
    day = str(summary.get("calendarDate") or summary.get("periodStartDate") or "")[:10]
    if len(day) == 10:
        return day
    moment = observed_at(summary)
    return moment[:10] if moment else ""


def observed_at(summary: dict) -> str:
    for seconds, offset in (("measurementTimeInSeconds", "measurementTimeOffsetInSeconds"),
                            ("startTimeInSeconds", "startTimeOffsetInSeconds"),
                            ("startTimeInSeconds", "offsetInSeconds")):
        moment = local_time(summary.get(seconds), summary.get(offset))
        if moment is not None:
            return moment.isoformat()
    return ""


def record_key(summary_type: str, summary: dict, day: str) -> str:
    if summary_type in DAY_TYPES:
        return day
    if summary_type == "activities":
        # An edit (manuallyUpdatedActivities) keeps the activityId and gets a
        # new summaryId; keying on the id makes the edit replace the original.
        return str(summary.get("activityId") or summary.get("summaryId") or "")
    return str(summary.get("summaryId") or "")


def add(bucket: dict, key: str, day: str, value: float | None, observed: str = "",
        source_name: str = SOURCE_NAME) -> Aggregate | None:
    """Fold one value into its (key, day, source) aggregate."""
    if value is None or len(day) != 10:
        return None
    item = bucket.get((key, day, source_name))
    if item is None:
        item = Aggregate(DEFS[key], day, source_name, SOURCE_NAME)
        bucket[(key, day, source_name)] = item
    item.add(value, observed or day)
    return item


def converted(value: object, source_unit: str, key: str) -> float | None:
    """A value converted from Garmin's unit (named in the field: InGrams,
    InSeconds, InMeters) to the catalog unit through the shared converter."""
    return convert_quantity(num(value), source_unit, DEFS[key].unit)


# --- mapping mirrored summaries into daily aggregates -------------------------


def _map_dailies(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        day = summary_day(summary)
        for field, unit, key in (
            ("steps", "", "steps"),
            ("distanceInMeters", "m", "walking_running_distance"),
            ("floorsClimbed", "", "flights_climbed"),
            # Dailies' active kcal excludes BMR (Health API §7.1).
            ("activeKilocalories", "kcal", "active_energy"),
            ("bmrKilocalories", "kcal", "resting_energy"),
            ("moderateIntensityDurationInSeconds", "s", "moderate_activity"),
            ("vigorousIntensityDurationInSeconds", "s", "vigorous_activity"),
            ("restingHeartRateInBeatsPerMinute", "", "resting_heart_rate"),
        ):
            add(bucket, key, day, converted(summary.get(field), unit, key))
        item = add(bucket, "daily_heart_rate", day, num(summary.get("averageHeartRateInBeatsPerMinute")))
        if item is not None:
            # Garmin averaged the day; its own min/max are the real range.
            low = num(summary.get("minHeartRateInBeatsPerMinute"))
            high = num(summary.get("maxHeartRateInBeatsPerMinute"))
            item.value_min = low if low is not None else item.value_min
            item.value_max = high if high is not None else item.value_max
        stress = num(summary.get("averageStressLevel"))
        # -1 means too little rest-state data to compute stress: no value,
        # not a low one.
        if stress is not None and stress >= 0:
            add(bucket, "stress_level", day, stress)


def _map_sleeps(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        day = summary_day(summary)
        observed = observed_at(summary)
        stages = {key: converted(summary.get(field), "s", key) for field, key in (
            ("deepSleepDurationInSeconds", "sleep_deep"),
            ("lightSleepDurationInSeconds", "sleep_core"),
            ("remSleepInSeconds", "sleep_rem"),
            ("awakeDurationInSeconds", "sleep_awake"),
        )}
        for key, value in stages.items():
            add(bucket, key, day, value, observed)
        asleep = [stages[key] for key in ("sleep_deep", "sleep_core", "sleep_rem") if stages[key] is not None]
        window = converted(summary.get("durationInSeconds"), "s", "time_in_bed")
        # durationInSeconds spans the whole sleep window, awake time included;
        # time asleep is the staged sum whenever Garmin staged the night.
        add(bucket, "sleep_duration", day, sum(asleep) if asleep else window, observed)
        add(bucket, "time_in_bed", day, window, observed)
        score = summary.get("overallSleepScore")
        if isinstance(score, dict):
            add(bucket, "sleep_score", day, num(score.get("value")), observed)


def _map_hrv(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        add(bucket, "heart_rate_variability_rmssd", summary_day(summary), num(summary.get("lastNightAvg")))


def _map_stress_details(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        values = summary.get("timeOffsetBodyBatteryValues")
        levels = [v for v in (num(x) for x in values.values()) if v is not None and v >= 0] if isinstance(values, dict) else []
        if levels:
            add(bucket, "body_battery_high", summary_day(summary), max(levels))
            add(bucket, "body_battery_low", summary_day(summary), min(levels))


def _map_user_metrics(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        add(bucket, "vo2_max", summary_day(summary), num(summary.get("vo2Max")))
        add(bucket, "fitness_age", summary_day(summary), num(summary.get("fitnessAge")))


def _map_skin_temp(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        add(bucket, "temperature_deviation", summary_day(summary), num(summary.get("avgDeviationCelsius")))


def body_composition(bucket: dict, day: str, observed: str, source_name: str, fields: Iterable[tuple[str, object, str]]) -> None:
    """Scale fields; Garmin writes 0 for a quantity the scale cannot measure."""
    for key, value, unit in fields:
        amount = converted(value, unit, key)
        if amount:
            add(bucket, key, day, amount, observed, source_name)


def _map_body_comps(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        day = summary_day(summary)
        body_composition(bucket, day, observed_at(summary), SOURCE_NAME, (
            ("body_weight", summary.get("weightInGrams"), "g"),
            ("body_mass_index", summary.get("bodyMassIndex"), ""),
            ("body_fat_percentage", summary.get("bodyFatInPercent"), ""),
            ("body_water_percentage", summary.get("bodyWaterInPercent"), ""),
            ("bone_mass", summary.get("boneMassInGrams"), "g"),
            ("muscle_mass", summary.get("muscleMassInGrams"), "g"),
        ))


def _map_blood_pressures(summaries: list[dict], bucket: dict) -> None:
    for summary in summaries:
        day = summary_day(summary)
        observed = observed_at(summary)
        for field, key in (("systolic", "systolic_blood_pressure"), ("diastolic", "diastolic_blood_pressure"),
                           ("pulse", "blood_pressure_pulse")):
            add(bucket, key, day, num(summary.get(field)), observed, BP_SOURCE_NAME)


def _map_series(field: str, key: str, low: float, high: float) -> Callable[[list[dict], dict], None]:
    """Offset-keyed sample maps (SpO₂, breaths) averaged into the day. Values
    outside the physiological range are sensor dropouts, not readings."""
    def mapper(summaries: list[dict], bucket: dict) -> None:
        for summary in summaries:
            _add_series_samples(summary, bucket, field, key, low, high)
    return mapper


def _add_series_samples(summary: dict, bucket: dict, field: str, key: str, low: float, high: float) -> None:
    day = summary_day(summary)
    values = summary.get(field)
    if not isinstance(values, dict):
        return
    for offset, raw in values.items():
        value = num(raw)
        if value is None or not low <= value <= high:
            continue
        moment = local_time((num(summary.get("startTimeInSeconds")) or 0) + (num(offset) or 0),
                            summary.get("startTimeOffsetInSeconds"))
        add(bucket, key, day, value, moment.isoformat() if moment else day)


MAPPERS: dict[str, Callable[[list[dict], dict], None]] = {
    "dailies": _map_dailies,
    "sleeps": _map_sleeps,
    "hrv": _map_hrv,
    "stressDetails": _map_stress_details,
    "userMetrics": _map_user_metrics,
    "skinTemp": _map_skin_temp,
    "bodyComps": _map_body_comps,
    "bloodPressures": _map_blood_pressures,
    "pulseox": _map_series("timeOffsetSpo2Values", "blood_oxygen", 50, 100),
    "allDayRespiration": _map_series("timeOffsetEpochToBreaths", "respiratory_rate", 4, 60),
}


def workout(started: datetime | None, activity_type: str, seconds: float | None,
            kcal: float | None, meters: float | None) -> Workout | None:
    if started is None:
        return None
    return Workout(
        source_name=SOURCE_NAME, source_vendor=SOURCE_NAME,
        workout_type=(activity_type or "workout").lower(),
        started_at=started.isoformat(),
        ended_at=(started + timedelta(seconds=seconds)).isoformat() if seconds else None,
        duration_minutes=seconds / 60 if seconds else None,
        energy_kcal=kcal,
        distance_km=convert_quantity(meters, "m", "km"),
    )


def _workout(summary: dict) -> Workout | None:
    return workout(
        local_time(summary.get("startTimeInSeconds"), summary.get("startTimeOffsetInSeconds")),
        str(summary.get("activityType") or ""), num(summary.get("durationInSeconds")),
        num(summary.get("activeKilocalories")), num(summary.get("distanceInMeters")),
    )


def _event(summary: dict) -> DeviceEvent | None:
    if "periodStartDate" in summary:
        # Predicted cycles are Garmin's forecast, not something that happened.
        if summary.get("isPredictedCycle") or not summary_day(summary):
            return None
        return DeviceEvent(
            source_name=SOURCE_NAME, source_vendor=SOURCE_NAME, event_type=EVENT_CYCLE,
            started_at=summary_day(summary),
            value_text=str(summary.get("currentPhaseType") or "").lower() or None,
            value_numeric=num(summary.get("cycleLength")), unit="days",
        )
    started = local_time(summary.get("startTimeInSeconds"), summary.get("offsetInSeconds"))
    if started is None:
        return None
    seconds = num(summary.get("durationInSeconds"))
    return DeviceEvent(
        source_name=SOURCE_NAME, source_vendor=SOURCE_NAME, event_type=EVENT_MOVE_IQ,
        started_at=started.isoformat(),
        ended_at=(started + timedelta(seconds=seconds)).isoformat() if seconds else None,
        value_text=": ".join(p for p in (str(summary.get("activityType") or ""),
                                         str(summary.get("activitySubType") or "")) if p) or None,
        value_numeric=seconds / 60 if seconds else None, unit="min" if seconds else None,
    )


# --- persistence (shared with garmin_personal) ----------------------------------


def _patient_id(db, user_id: str) -> str:
    row = db.execute(
        "SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (user_id,)
    ).fetchone()
    if row is None:
        raise IntegrationError("garmin: no patient profile to attach device data to")
    return str(row["id"])


def ensure_envelope(settings: Settings, user_id: str, adapter_key: str = ADAPTER_KEY) -> str:
    """The one device_imports row all API rows hang from; its metadata_json is
    the sync-state store (backfill progress, last delivery or sync)."""
    import_id = stable_id("device-import", f"{user_id}:{adapter_key}:api")
    with connect(settings) as db:
        patient_id = _patient_id(db, user_id)
        vendor_id = ensure_vendor(db, "Garmin", "https://www.garmin.com/")
        db.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, 'api', 0, 0, 'complete', '{}', ?)
               ON CONFLICT(owner_user_id, adapter_key, source_fingerprint) DO NOTHING""",
            (import_id, user_id, patient_id, vendor_id, adapter_key, f"garmin://{adapter_key}", utc_now()),
        )
    return import_id


def sync_state(settings: Settings, user_id: str, adapter_key: str = ADAPTER_KEY) -> dict:
    with connect(settings) as db:
        row = db.execute(
            "SELECT metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key=?",
            (user_id, adapter_key),
        ).fetchone()
    try:
        return json.loads(row["metadata_json"]) if row else {}
    except json.JSONDecodeError:
        return {}


def update_state(settings: Settings, user_id: str, adapter_key: str = ADAPTER_KEY, **values: object) -> None:
    with transaction(settings, immediate=True) as db:
        row = db.execute("SELECT metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key=?",
                         (user_id, adapter_key)).fetchone()
        if row is None:
            return
        state = {**json.loads(row[0] or "{}"), **values}
        db.execute(
            """UPDATE device_imports SET metadata_json=?, imported_at=?,
                      raw_record_count=(SELECT COUNT(*) FROM device_metric_days WHERE import_id=device_imports.id)
                WHERE owner_user_id=? AND adapter_key=?""",
            (json.dumps(state, ensure_ascii=False), utc_now(), user_id, adapter_key),
        )


def _marks(items) -> str:
    return ",".join("?" for _ in items)


def replace_metric_days(db, user_id: str, import_id: str, keys: Iterable[str], days: Iterable[str],
                        aggregates: list[Aggregate]) -> int:
    """Make this envelope's rows for (keys, days) exactly ``aggregates``.

    Scoped to ``import_id``: a day the person imported from a Garmin *file
    export* belongs to another envelope and survives; a day both carry flips
    to this envelope on upsert, so the API stays authoritative for what it
    reports.
    """
    keys, days = sorted(set(keys)), sorted(set(days))
    if not keys or not days:
        return 0
    patient_id = _patient_id(db, user_id)
    now = utc_now()
    # An aggregate with no samples had every reading excluded as not the person's.
    wanted = [a for a in aggregates if a.day in set(days) and a.definition.key in set(keys) and a.sample_count]
    db.execute(
        f"""DELETE FROM device_metric_days WHERE owner_user_id=? AND import_id=?
             AND metric_key IN ({_marks(keys)}) AND day IN ({_marks(days)})""",
        (user_id, import_id, *keys, *days),
    )
    db.executemany(
        """INSERT INTO device_metric_days(
               id, owner_user_id, patient_id, import_id, source_name, source_vendor,
               metric_key, metric_name, category, day, aggregation, unit, value,
               value_min, value_max, value_sum, sample_count, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(owner_user_id, source_name, metric_key, day) DO UPDATE SET
               patient_id=excluded.patient_id, import_id=excluded.import_id,
               source_vendor=excluded.source_vendor, metric_name=excluded.metric_name,
               category=excluded.category, aggregation=excluded.aggregation,
               unit=excluded.unit, value=excluded.value, value_min=excluded.value_min,
               value_max=excluded.value_max, value_sum=excluded.value_sum,
               sample_count=excluded.sample_count, created_at=excluded.created_at""",
        [
            (
                stable_id("device-metric-day", f"{user_id}:{a.source_name}:{a.definition.key}:{a.day}"),
                user_id, patient_id, import_id, a.source_name, a.source_vendor,
                a.definition.key, a.definition.name, a.definition.category, a.day,
                a.definition.aggregation, a.definition.unit, a.value,
                a.value_min, a.value_max, a.value_sum, a.sample_count, now,
            )
            for a in wanted
        ],
    )
    return len(wanted)


def replace_workouts(db, user_id: str, import_id: str, days: Iterable[str], workouts: list[Workout]) -> int:
    days = sorted(set(days))
    if not days:
        return 0
    patient_id = _patient_id(db, user_id)
    now = utc_now()
    wanted = [w for w in workouts if w.started_at[:10] in set(days)]
    db.execute(
        f"DELETE FROM device_workouts WHERE owner_user_id=? AND import_id=? AND substr(started_at, 1, 10) IN ({_marks(days)})",
        (user_id, import_id, *days),
    )
    db.executemany(
        """INSERT INTO device_workouts(
               id, owner_user_id, patient_id, import_id, source_name, source_vendor,
               workout_type, started_at, ended_at, duration_minutes, energy_kcal,
               distance_km, route_file, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(owner_user_id, source_name, workout_type, started_at) DO UPDATE SET
               patient_id=excluded.patient_id, import_id=excluded.import_id,
               source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
               duration_minutes=excluded.duration_minutes, energy_kcal=excluded.energy_kcal,
               distance_km=excluded.distance_km, created_at=excluded.created_at""",
        [
            (
                stable_id("device-workout", f"{user_id}:{w.source_name}:{w.workout_type}:{w.started_at}"),
                user_id, patient_id, import_id, w.source_name, w.source_vendor, w.workout_type,
                w.started_at, w.ended_at, w.duration_minutes, w.energy_kcal, w.distance_km, None, now,
            )
            for w in wanted
        ],
    )
    return len(wanted)


def replace_events(db, user_id: str, import_id: str, event_type: str, days: Iterable[str],
                   events: list[DeviceEvent]) -> int:
    days = sorted(set(days))
    if not days:
        return 0
    patient_id = _patient_id(db, user_id)
    now = utc_now()
    wanted = [e for e in events if e.started_at[:10] in set(days) and e.event_type == event_type]
    db.execute(
        f"""DELETE FROM device_events WHERE owner_user_id=? AND import_id=? AND event_type=?
             AND substr(started_at, 1, 10) IN ({_marks(days)})""",
        (user_id, import_id, event_type, *days),
    )
    db.executemany(
        """INSERT INTO device_events(
               id, owner_user_id, patient_id, import_id, source_name, source_vendor,
               event_type, started_at, ended_at, value_text, value_numeric, unit,
               source_file, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(owner_user_id, event_type, started_at, source_name) DO UPDATE SET
               patient_id=excluded.patient_id, import_id=excluded.import_id,
               source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
               value_text=excluded.value_text, value_numeric=excluded.value_numeric,
               unit=excluded.unit, created_at=excluded.created_at""",
        [
            (
                stable_id("device-event", f"{user_id}:{e.event_type}:{e.started_at}:{e.source_name}"),
                user_id, patient_id, import_id, e.source_name, e.source_vendor, e.event_type,
                e.started_at, e.ended_at, e.value_text, e.value_numeric, e.unit, None, now,
            )
            for e in wanted
        ],
    )
    return len(wanted)


def purge_envelope(db, user_id: str, adapter_key: str, keys: Iterable[str] = (), workouts: bool = False,
                   event_types: Iterable[str] = (), drop_envelope: bool = False) -> int:
    """Delete rows an API envelope owns. File-import rows are another envelope
    and are never touched: the person's own export is theirs to keep."""
    envelope = db.execute("SELECT id FROM device_imports WHERE owner_user_id=? AND adapter_key=?",
                          (user_id, adapter_key)).fetchone()
    if envelope is None:
        return 0
    import_id, removed = envelope[0], 0
    keys, event_types = sorted(set(keys)), sorted(set(event_types))
    if keys:
        removed += db.execute(
            f"DELETE FROM device_metric_days WHERE import_id=? AND metric_key IN ({_marks(keys)})",
            (import_id, *keys),
        ).rowcount
    if workouts:
        removed += db.execute("DELETE FROM device_workouts WHERE import_id=?", (import_id,)).rowcount
    if event_types:
        removed += db.execute(
            f"DELETE FROM device_events WHERE import_id=? AND event_type IN ({_marks(event_types)})",
            (import_id, *event_types),
        ).rowcount
    if drop_envelope:
        for table in ("device_metric_days", "device_workouts", "device_events"):
            removed += db.execute(f"DELETE FROM {table} WHERE import_id=?", (import_id,)).rowcount
        db.execute("DELETE FROM device_imports WHERE id=?", (import_id,))
    return removed


# --- the mirror ---------------------------------------------------------------


def _rebuild(db, user_id: str, import_id: str, summary_type: str, days: set[str]) -> int:
    """Make this envelope's rows for (type, days) match the mirror exactly."""
    if not days:
        return 0
    summaries = [json.loads(row[0]) for row in db.execute(
        f"SELECT payload FROM garmin_summaries WHERE user_id=? AND summary_type=? AND day IN ({_marks(days)}) ORDER BY received_at",
        (user_id, summary_type, *sorted(days)),
    )]
    # The person's "not my reading" rules, read in this write transaction.
    if summary_type in TYPE_KEYS:
        bucket: dict = {}
        with exclusions.applying(db, user_id, ADAPTER_KEY):
            MAPPERS[summary_type](summaries, bucket)
        return replace_metric_days(db, user_id, import_id, TYPE_KEYS[summary_type], days, list(bucket.values()))
    rules = exclusions.matcher(db, user_id, ADAPTER_KEY)
    if summary_type in WORKOUT_TYPES:
        return replace_workouts(db, user_id, import_id, days, kept_workouts(
            [w for w in map(_workout, summaries) if w], rules))
    return replace_events(db, user_id, import_id, EVENT_TYPES[summary_type], days, kept_events(
        [e for e in map(_event, summaries) if e], rules))


def kept_workouts(workouts: list[Workout], rules) -> list[Workout]:
    """Workouts less those the person marked as not theirs."""
    return [w for w in workouts if rules is None
            or not rules.excludes(w.source_name, exclusions.WORKOUTS, w.started_at, w.ended_at)]


def kept_events(events: list[DeviceEvent], rules) -> list[DeviceEvent]:
    return [e for e in events if rules is None
            or not rules.excludes(e.source_name, exclusions.EVENTS, e.started_at, e.ended_at)]


def rebuild_window(settings: Settings, user_id: str, start: str, end: str) -> int:
    """Rewrite every mirrored day in [start, end] under the person's current
    rules, from the local mirror alone (an exclusion was made or undone)."""
    with transaction(settings, immediate=True) as db:
        envelope = db.execute("SELECT id FROM device_imports WHERE owner_user_id=? AND adapter_key=?",
                              (user_id, ADAPTER_KEY)).fetchone()
        if envelope is None:
            return 0
        written = 0
        for summary_type in sorted(MIRRORED):
            days = {str(row[0]) for row in db.execute(
                "SELECT DISTINCT day FROM garmin_summaries WHERE user_id=? AND summary_type=? AND day BETWEEN ? AND ?",
                (user_id, summary_type, start, end))}
            written += _rebuild(db, user_id, str(envelope[0]), summary_type, days)
    return written


def store_summaries(settings: Settings, user_id: str, summary_type: str, summaries: Iterable[dict]) -> int:
    """Mirror a batch of one type's summaries and rebuild the days they touch."""
    summary_type = _ALIASES.get(summary_type, summary_type)
    if summary_type not in MIRRORED:
        return 0
    import_id = ensure_envelope(settings, user_id)
    now = utc_now()
    touched: set[str] = set()
    with transaction(settings, immediate=True) as db:
        # The connection may have gone since the delivery arrived: data for an
        # account no longer linked is not ours to keep.
        if db.execute("SELECT 1 FROM provider_connections WHERE user_id=? AND provider='garmin'",
                      (user_id,)).fetchone() is None:
            return 0
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            day = summary_day(summary)
            key = record_key(summary_type, summary, day)
            if not day or not key:
                continue
            previous = db.execute(
                "SELECT day FROM garmin_summaries WHERE user_id=? AND summary_type=? AND record_key=?",
                (user_id, summary_type, key),
            ).fetchone()
            if previous is not None:
                touched.add(str(previous[0]))  # an edit can move an activity's day
            db.execute(
                """INSERT INTO garmin_summaries(user_id, summary_type, record_key, day, payload, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, summary_type, record_key) DO UPDATE SET
                       day=excluded.day, payload=excluded.payload, received_at=excluded.received_at""",
                (user_id, summary_type, key, day, json.dumps(summary, ensure_ascii=False), now),
            )
            touched.add(day)
        return _rebuild(db, user_id, import_id, summary_type, touched)


def purge(settings: Settings, user_id: str, summary_types: Iterable[str] | None = None) -> int:
    """Delete Garmin-delivered data — all of it, or the named types'."""
    types = set(summary_types) if summary_types is not None else set(MIRRORED)
    with transaction(settings, immediate=True) as db:
        db.execute(
            f"DELETE FROM garmin_summaries WHERE user_id=? AND summary_type IN ({_marks(types)})",
            (user_id, *sorted(types)),
        )
        return purge_envelope(
            db, user_id, ADAPTER_KEY,
            keys=[key for t in types for key in TYPE_KEYS.get(t, ())],
            workouts=bool(types & WORKOUT_TYPES),
            event_types=[EVENT_TYPES[t] for t in types if t in EVENT_TYPES],
            drop_envelope=types >= MIRRORED,
        )


# --- Garmin API calls ----------------------------------------------------------


def _get(settings: Settings, user_id: str, url: str):
    return integrations.authorized_request(settings, user_id, PROVIDER, url)


def parse_permissions(payload: object) -> list[str] | None:
    """Garmin's spec shows a bare list; production answers ``{"permissions": [...]}``."""
    if isinstance(payload, dict):
        payload = payload.get("permissions")
    return sorted(str(p) for p in payload) if isinstance(payload, list) else None


def fetch_permissions(settings: Settings, user_id: str) -> list[str]:
    """The permissions granted at Garmin's consent screen, stored as the
    connection's scopes so the profile can name what is and is not shared."""
    permissions = parse_permissions(_get(settings, user_id, f"{WELLNESS}/user/permissions")) or []
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET scopes=?, updated_at=? WHERE user_id=? AND provider='garmin'",
                   (" ".join(permissions), utc_now(), user_id))
    return permissions


def safe_callback(url: str) -> bool:
    """A ping's callbackURL is fetched with the person's bearer token, so it
    must point at Garmin's API host and nowhere else."""
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST and not parsed.username and parsed.port in (None, 443)


def request_backfill(settings: Settings, user_id: str) -> dict[str, object]:
    """Ask Garmin to replay the last month, once per type, resumably.

    Garmin answers 202 and later pushes the data through the webhook. Progress
    lives in the envelope so a restart resumes. 409 means "already requested"
    and counts as done; 400/403/412 mean this key's tier, the person's consent
    or their settings rule history out for that type — recorded, not retried;
    anything else (429, 5xx, network) pauses until the next attempt.
    """
    ensure_envelope(settings, user_id)
    state = dict(sync_state(settings, user_id).get("backfill") or {})
    end = int(time.time())
    start = end - BACKFILL_DAYS * 86400
    for summary_type, endpoint in BACKFILL_ENDPOINTS.items():
        if (state.get(summary_type) or {}).get("status") in ("done", "unavailable"):
            continue
        url = f"{WELLNESS}/backfill/{endpoint}?" + urllib.parse.urlencode(
            {"summaryStartTimeInSeconds": start, "summaryEndTimeInSeconds": end})
        try:
            _get(settings, user_id, url)
            state[summary_type] = {"status": "done"}
        except IntegrationError as exc:
            if exc.status == 409:
                state[summary_type] = {"status": "done"}
            elif exc.status in (400, 403, 412):
                state[summary_type] = {"status": "unavailable", "error": str(exc)[:200]}
            else:
                state[summary_type] = {"status": "paused", "error": str(exc)[:200]}
                update_state(settings, user_id, backfill=state)
                return state
        update_state(settings, user_id, backfill=state)
    update_state(settings, user_id, backfill=state, last_backfill_at=utc_now())
    return state


# --- processing deliveries ----------------------------------------------------


def _connections(settings: Settings) -> dict[str, tuple[str, str]]:
    """Garmin user id -> (our user id, when that connection was made)."""
    with connect(settings) as db:
        return {
            str(row["external_user_id"]): (str(row["user_id"]), str(row["connected_at"]))
            for row in db.execute(
                "SELECT user_id, external_user_id, connected_at FROM provider_connections WHERE provider='garmin' AND external_user_id<>''"
            )
        }


def _handle_deregistration(settings: Settings, user_id: str) -> None:
    """The person removed this application at Garmin Connect (or it was
    removed for them): the tokens are dead and Garmin's data goes with them."""
    purge(settings, user_id)
    with connect(settings) as db:
        db.execute("DELETE FROM provider_connections WHERE user_id=? AND provider='garmin'", (user_id,))
    logger.info("garmin: account deregistered at Garmin; connection and Garmin-delivered data removed")


def _handle_permissions(settings: Settings, user_id: str, permissions: list[str]) -> None:
    for permission, types in PERMISSION_TYPES.items():
        if permission not in permissions:
            purge(settings, user_id, types)
    with connect(settings) as db:
        db.execute("UPDATE provider_connections SET scopes=?, updated_at=? WHERE user_id=? AND provider='garmin'",
                   (" ".join(sorted(permissions)), utc_now(), user_id))


def _event_owner(connections: dict[str, tuple[str, str]], received_at: str, item: object) -> str:
    user_id, connected_at = connections.get(str((item or {}).get("userId") or "") if isinstance(item, dict) else "", ("", ""))
    # A lifecycle notice that arrived before the current connection was
    # made belongs to the previous one (Garmin delivers stale
    # deregistrations after a reconnect).
    if user_id and received_at and connected_at and received_at < connected_at:
        return ""
    return user_id


def _collect_summaries(settings: Settings, connections: dict[str, tuple[str, str]],
                       items: list) -> dict[str, list[dict]]:
    """Group a delivery's summaries by local user, following ping callbacks."""
    per_user: dict[str, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        user_id, _ = connections.get(str(item.get("userId") or ""), ("", ""))
        if not user_id:
            continue  # not one of ours (or disconnected since): never stored
        callback = str(item.get("callbackURL") or "")
        if not callback:
            per_user.setdefault(user_id, []).append(item)
        elif not safe_callback(callback):
            logger.warning("garmin: ignored a ping whose callback is not %s", API_HOST)
        else:
            pulled = _get(settings, user_id, callback)
            per_user.setdefault(user_id, []).extend(s for s in (pulled or []) if isinstance(s, dict))
    return per_user


def process_event(settings: Settings, payload: dict, connections: dict[str, tuple[str, str]],
                  received_at: str = "") -> set[str]:
    """One delivery. Returns the local users it touched. Raises
    IntegrationError when a ping could not be resolved — the event stays
    pending and is retried, because Garmin does not redeliver a 200."""
    touched: set[str] = set()

    for summary_type, items in payload.items():
        if isinstance(items, list):
            touched |= _process_summary_type(settings, summary_type, items, connections, received_at)
    return touched


def _process_summary_type(settings: Settings, summary_type: str, items: list,
                          connections: dict[str, tuple[str, str]], received_at: str) -> set[str]:
    touched: set[str] = set()
    if summary_type == "deregistrations":
        for item in items:
            if user_id := _event_owner(connections, received_at, item):
                _handle_deregistration(settings, user_id)
                touched.add(user_id)
    elif summary_type == "userPermissionsChange":
        for item in items:
            user_id = _process_permissions_item(settings, connections, received_at, item)
            if user_id:
                touched.add(user_id)
    else:
        for user_id, summaries in _collect_summaries(settings, connections, items).items():
            store_summaries(settings, user_id, summary_type, summaries)
            touched.add(user_id)
    return touched


def _process_permissions_item(settings: Settings, connections: dict[str, tuple[str, str]],
                              received_at: str, item: Any) -> str:
    permissions = parse_permissions(item) if isinstance(item, dict) else None
    user_id = _event_owner(connections, received_at, item)
    if not user_id or permissions is None:
        return ""
    _handle_permissions(settings, user_id, permissions)
    return user_id


def process_pending(settings: Settings) -> int:
    """Turn archived deliveries into rows, oldest first, and mark them done.
    A delivery that fails stays pending for the next run."""
    with connect(settings) as db:
        rows = db.execute(
            "SELECT id, payload, received_at FROM provider_events WHERE provider='garmin' AND processed_at IS NULL ORDER BY id"
        ).fetchall()
    if not rows:
        return 0
    connections = _connections(settings)
    done: list[int] = []
    touched: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            payload = {}
        try:
            touched |= process_event(settings, payload if isinstance(payload, dict) else {}, connections,
                                     str(row["received_at"] or ""))
        except IntegrationError as exc:
            logger.warning("garmin: delivery %s failed, will retry: %s", row["id"], exc)
            continue
        done.append(int(row["id"]))
    now = utc_now()
    with connect(settings) as db:
        db.executemany("UPDATE provider_events SET processed_at=? WHERE id=?", [(now, i) for i in done])
    for user_id in touched:
        update_state(settings, user_id, last_delivery_at=now)
    return len(done)


# --- background entry points (the oura/paperless thread pattern) ---------------

_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def spawn(name: str, target, *args) -> None:
    with _inflight_lock:
        if name in _inflight:
            return
        _inflight.add(name)

    def run() -> None:
        try:
            started = time.monotonic()
            # "garmin-connect-<user id>" is logged as "garmin-connect": no identifiers.
            log_run(logger, "-".join(name.split("-")[:2]), started, target(*args))
        except Exception:  # noqa: BLE001 — background work must never take the request down
            logger.warning("garmin: background %s failed", name, exc_info=True)
        finally:
            with _inflight_lock:
                _inflight.discard(name)

    threading.Thread(target=run, name=f"anamna-{name}", daemon=True).start()


def connect_tasks(settings: Settings, user_id: str) -> None:
    ensure_envelope(settings, user_id)
    try:
        fetch_permissions(settings, user_id)
    except IntegrationError as exc:
        logger.warning("garmin: permission lookup failed: %s", exc)
    process_pending(settings)
    request_backfill(settings, user_id)


def start_connect_tasks(settings: Settings, user_id: str) -> None:
    """After the OAuth callback, and the profile's sync button: permissions,
    pending deliveries, then the month of history Garmin will replay."""
    spawn(f"garmin-connect-{user_id}", connect_tasks, settings, user_id)


def start_processing(settings: Settings) -> None:
    spawn("garmin-process", process_pending, settings)
