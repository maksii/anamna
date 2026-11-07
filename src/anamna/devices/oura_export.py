"""Importer for Oura JSON exports and the official semicolon CSV Takeout.

The Takeout is not the public API serialized to CSV.  It is an ``App Data``
directory containing public datasets, raw sensor streams, product settings and
internal algorithm tables.  This adapter normalizes the public health datasets
into the same metric/workout/event model as :mod:`anamna.oura`, retains
the source directory as the lossless record, and reports every populated table
that is intentionally retained or is not yet understood.  That last distinction
turns export-format drift into something the validator can fail on instead of a
silent partial import.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Iterable

from .catalog import canonical_source_vendor, metric
from .models import Aggregate, DeviceEvent, ParsedDeviceExport, Workout
from .timezone import local_day, zone
from .units import finite_number


SOURCE_NAME = "Oura"

# Kept in the five-item shape used by the older structured adapters and by the
# panel-coverage test.  File-specific code below supplies the correct daily
# aggregation; the final item is the unit scale.
FIELDS = {
    "sleep_score": ("sleep_score", "Sleep score", "device_sleep", "score", 1),
    "readiness_score": ("readiness_score", "Readiness score", "device_recovery", "score", 1),
    "activity_score": ("activity_score", "Activity score", "device_activity", "score", 1),
    "steps": ("steps", "Daily steps", "device_activity", "steps", 1),
    "total_sleep_duration": ("sleep_duration", "Time asleep", "device_sleep", "hours", 1 / 3600),
    "deep_sleep_duration": ("sleep_deep", "Deep sleep", "device_sleep", "hours", 1 / 3600),
    "rem_sleep_duration": ("sleep_rem", "REM sleep", "device_sleep", "hours", 1 / 3600),
    "light_sleep_duration": ("sleep_core", "Core sleep", "device_sleep", "hours", 1 / 3600),
    "awake_time": ("sleep_awake", "Awake during sleep", "device_sleep", "hours", 1 / 3600),
    "time_in_bed": ("time_in_bed", "Time in bed", "device_sleep", "hours", 1 / 3600),
    "efficiency": ("sleep_efficiency", "Sleep efficiency", "device_sleep", "%", 1),
    "average_hrv": ("heart_rate_variability_rmssd", "Heart rate variability (RMSSD)", "device_recovery", "ms", 1),
    "lowest_heart_rate": ("lowest_sleeping_heart_rate", "Lowest sleeping heart rate", "device_recovery", "bpm", 1),
    "average_breath": ("respiratory_rate", "Respiratory rate", "device_recovery", "breaths/min", 1),
    "temperature_deviation": ("temperature_deviation", "Temperature deviation", "device_recovery", "°C", 1),
    "active_calories": ("active_energy", "Active energy", "device_activity", "kcal", 1),
    "resting_calories": ("resting_energy", "Resting energy", "device_activity", "kcal", 1),
    "medium_activity_time": ("moderate_activity", "Moderate activity", "device_activity", "min", 1 / 60),
    "high_activity_time": ("vigorous_activity", "Vigorous activity", "device_activity", "min", 1 / 60),
    "spo2_percentage": ("blood_oxygen", "Blood oxygen saturation", "device_recovery", "%", 1),
    "breathing_disturbance_index": (
        "breathing_disturbance_index", "Breathing disturbance index", "device_recovery", "per hour", 1,
    ),
    "stress_high": ("stress_high_time", "High stress time", "device_recovery", "min", 1 / 60),
    "recovery_high": ("recovery_high_time", "High recovery time", "device_recovery", "min", 1 / 60),
    "vascular_age": ("cardiovascular_age", "Cardiovascular age", "device_recovery", "years", 1),
    "pulse_wave_velocity": ("pulse_wave_velocity", "Pulse wave velocity", "device_recovery", "m/s", 1),
    "vo2_max": ("vo2_max", "Cardio fitness (VO₂ max)", "device_fitness", "mL/kg/min", 1),
    "bpm": ("daily_heart_rate", "Daily heart rate", "device_recovery", "bpm", 1),
}

_AGGREGATION = {
    "sleep_duration": "sum",
    "sleep_deep": "sum",
    "sleep_rem": "sum",
    "sleep_core": "sum",
    "sleep_awake": "sum",
    "time_in_bed": "sum",
    "steps": "sum",
    "active_energy": "latest",
    "resting_energy": "latest",
    "moderate_activity": "latest",
    "vigorous_activity": "latest",
    "sleep_score": "latest",
    "readiness_score": "latest",
    "activity_score": "latest",
    "temperature_deviation": "latest",
    "sleep_efficiency": "latest",
    "stress_high_time": "latest",
    "recovery_high_time": "latest",
    "cardiovascular_age": "latest",
    "pulse_wave_velocity": "latest",
    "vo2_max": "latest",
}

# Takeout table names, written once: they key the manifest, the normalized-schema
# pin and the parser below.
_APPLICATIONDEBUGSTATE_CSV = "applicationdebugstate.csv"
_DAILYACTIVITY_CSV = "dailyactivity.csv"
_DAILYCARDIOVASCULARAGE_CSV = "dailycardiovascularage.csv"
_DAILYREADINESS_CSV = "dailyreadiness.csv"
_DAILYSLEEP_CSV = "dailysleep.csv"
_DAILYSPO2_CSV = "dailyspo2.csv"
_DAILYSTRESS_CSV = "dailystress.csv"
_ENHANCEDTAG_CSV = "enhancedtag.csv"
_HEARTRATE_CSV = "heartrate.csv"
_IMPORTEDHEARTRATE_CSV = "importedheartrate.csv"
_IMPORTEDSTEPCOUNT_CSV = "importedstepcount.csv"
_RINGBATTERYLEVEL_CSV = "ringbatterylevel.csv"
_SESSION_CSV = "session.csv"
_RINGCONFIGURATION_CSV = "ringconfiguration.csv"
_SLEEPMODEL_CSV = "sleepmodel.csv"
_TIMEZONE_CSV = "timezone.csv"
_WORKOUT_CSV = "workout.csv"
_VO2MAX_CSV = "vo2max.csv"
_ANY_CSV = "*.csv"

# The complete App Data manifest observed in the official 2026 Takeout.  A new
# populated table is not guessed at: it is surfaced as unsupported by coverage
# metadata and the validator fails.  Empty tables are still recognized so an
# export is not reported as incomplete merely because the feature was unused.
KNOWN_APP_DATA_FILES = {
    "activitypredictionsegment.csv", "adaptiveprofilegroupenrollment.csv",
    _APPLICATIONDEBUGSTATE_CSV, "behaviorcoachingevent.csv", "behaviorcoachingsession.csv",
    "bloodglucose.csv", "bloodpressure.csv", "cardioeffortbaselines.csv",
    "cardioeffortsettings.csv", _DAILYACTIVITY_CSV, "dailybloodpressuresignals.csv",
    _DAILYCARDIOVASCULARAGE_CSV, "dailycyclemappingdsr.csv", "dailymetabolicscore.csv",
    _DAILYREADINESS_CSV, "dailyresilience.csv", _DAILYSLEEP_CSV,
    "dailysmoothedcardiovascularage.csv", _DAILYSPO2_CSV, _DAILYSTRESS_CSV,
    "dailyvo2maxestimate.csv", "daytimestress.csv", _ENHANCEDTAG_CSV, "fooditem.csv",
    "glp1settings.csv", _HEARTRATE_CSV, "hormonalcontraceptionusage.csv",
    _IMPORTEDHEARTRATE_CSV, "importedlocation.csv", _IMPORTEDSTEPCOUNT_CSV,
    "labtestresult.csv", "labtestresultinsights.csv", "meal.csv",
    "medicationadministrationlog.csv", "medicationprofile.csv", "motion.csv",
    "nonhormonalcontraceptionusage.csv", "otherreproductivehormone.csv",
    "periodstartdsr.csv", "rawlocation.csv", "reproductivecyclepredictiondsr.csv",
    "restmodeperiod.csv", _RINGBATTERYLEVEL_CSV, _RINGCONFIGURATION_CSV, _SESSION_CSV,
    _SLEEPMODEL_CSV, "sleepstorysession.csv", "sleeptime.csv", "stepcount.csv",
    "surveyresponse.csv", "temperature.csv", _TIMEZONE_CSV, "travelperiod.csv",
    "userconsentsettings.csv", "usermetabolicsettings.csv", "uservo2maxsettings.csv",
    _VO2MAX_CSV, "vo2maxworkoutestimate.csv", _WORKOUT_CSV,
    "workoutheartratesession.csv", "workoutpacedistance.csv",
}

NORMALIZED_FILES = {
    _APPLICATIONDEBUGSTATE_CSV, _DAILYACTIVITY_CSV, _DAILYCARDIOVASCULARAGE_CSV,
    _DAILYREADINESS_CSV, _DAILYSLEEP_CSV, _DAILYSPO2_CSV, _DAILYSTRESS_CSV,
    _ENHANCEDTAG_CSV, _HEARTRATE_CSV, _IMPORTEDHEARTRATE_CSV, _IMPORTEDSTEPCOUNT_CSV,
    _RINGBATTERYLEVEL_CSV, _RINGCONFIGURATION_CSV, _SESSION_CSV, _SLEEPMODEL_CSV,
    _TIMEZONE_CSV, _VO2MAX_CSV, _WORKOUT_CSV,
}

# Every column in a normalized table is either consumed above or deliberately
# retained in the immutable source.  Pinning the observed schema makes a newly
# added Oura column visible instead of silently treating it as supported.
NORMALIZED_FILE_COLUMNS = {
    _APPLICATIONDEBUGSTATE_CSV: {"id", "ring_debug_information"},
    _DAILYACTIVITY_CSV: {
        "id", "active_calories", "average_met_minutes", "class_5_min", "contributors", "day",
        "equivalent_walking_distance", "high_activity_met_minutes", "high_activity_time",
        "inactivity_alerts", "low_activity_met_minutes", "low_activity_time",
        "medium_activity_met_minutes", "medium_activity_time", "met", "meters_to_target",
        "non_wear_time", "resting_time", "score", "sedentary_met_minutes", "sedentary_time",
        "steps", "target_calories", "target_meters", "timestamp", "total_calories",
    },
    _DAILYCARDIOVASCULARAGE_CSV: {"id", "day", "pulse_wave_velocity", "vascular_age"},
    _DAILYREADINESS_CSV: {
        "id", "contributors", "day", "score", "temperature_deviation",
        "temperature_trend_deviation", "timestamp",
    },
    _DAILYSLEEP_CSV: {"id", "contributors", "day", "score", "timestamp"},
    _DAILYSPO2_CSV: {"id", "breathing_disturbance_index", "day", "spo2_percentage"},
    _DAILYSTRESS_CSV: {"id", "day", "day_summary", "recovery_high", "stress_high"},
    _ENHANCEDTAG_CSV: {
        "id", "comment", "custom_name", "custom_tag_name", "end_day", "end_time",
        "start_day", "start_time", "tag_type_code",
    },
    _HEARTRATE_CSV: {"timestamp", "bpm", "source"},
    _IMPORTEDHEARTRATE_CSV: {"timestamp", "bpm", "imported_from", "origin_source"},
    _IMPORTEDSTEPCOUNT_CSV: {"timestamp", "end_time", "imported_from", "origin_source", "steps"},
    _RINGBATTERYLEVEL_CSV: {"timestamp", "charging", "in_charger", "level"},
    _RINGCONFIGURATION_CSV: {
        "id", "color", "design", "firmware_version", "hardware_type", "set_up_at", "size",
    },
    _SESSION_CSV: {
        "id", "day", "end_datetime", "heart_rate", "heart_rate_variability", "mood",
        "motion_count", "start_datetime", "type",
    },
    _SLEEPMODEL_CSV: {
        "id", "average_breath", "average_heart_rate", "average_hrv", "awake_time",
        "bedtime_end", "bedtime_start", "day", "deep_sleep_duration", "efficiency",
        "heart_rate", "hrv", "latency", "light_sleep_duration", "low_battery_alert",
        "lowest_heart_rate", "movement_30_sec", "period", "readiness",
        "readiness_score_delta", "rem_sleep_duration", "restless_periods",
        "sleep_algorithm_version", "sleep_analysis_reason", "sleep_phase_30_sec",
        "sleep_phase_5_min", "sleep_score_delta", "time_in_bed", "total_sleep_duration", "type",
    },
    _TIMEZONE_CSV: {"timestamp", "identifier", "offset"},
    _VO2MAX_CSV: {"id", "day", "timestamp", "vo2_max"},
    _WORKOUT_CSV: {
        "id", "activity", "calories", "day", "distance", "end_datetime", "intensity",
        "label", "source", "start_datetime",
    },
}

RETAINED_REASONS = {
    "activitypredictionsegment.csv": "internal activity predictions; confirmed workouts are normalized",
    "dailyresilience.csv": "manufacturer category without a numeric measurement contract",
    "dailysmoothedcardiovascularage.csv": "internal smoothed duplicate of normalized daily cardiovascular age",
    "daytimestress.csv": "raw stress samples; normalized daily stress and recovery durations are used",
    "motion.csv": "raw accelerometer stream; derived activity and sleep measures are normalized",
    "rawlocation.csv": "raw precise location is retained only in the private source export",
    "stepcount.csv": "raw step stream; the vendor daily total is normalized",
    "temperature.csv": "raw skin temperature stream; Oura's baseline deviation is normalized",
    "sleeptime.csv": "bedtime recommendation rather than a measurement",
    "workoutheartratesession.csv": "internal workout-detection candidates; confirmed workouts are normalized",
}

# These tables were populated in the audited Takeout but intentionally remain
# raw for the reasons above.  Any other previously-empty known table becoming
# populated is format drift and is reported as unsupported until it receives a
# semantic mapping or an explicit retention decision.
AUDITED_RETAINED_FILES = set(RETAINED_REASONS) | {
    "cardioeffortsettings.csv", "dailybloodpressuresignals.csv", "glp1settings.csv",
    "reproductivecyclepredictiondsr.csv", "usermetabolicsettings.csv",
    "uservo2maxsettings.csv", "vo2maxworkoutestimate.csv",
}

_SLEEP_TYPES = {"long_sleep", "sleep", "late_nap"}

#: Every metric a night of sleep produces -- the set a quarantined night loses.
SLEEP_KEYS = (
    "sleep_duration", "sleep_deep", "sleep_rem", "sleep_core", "sleep_awake",
    "time_in_bed", "sleep_efficiency", "lowest_sleeping_heart_rate",
    "heart_rate_variability_rmssd", "respiratory_rate",
)

#: More sleep (or time in bed) than this in one day is not a night anybody
#: slept; it is periods attributed to the wrong day.  The first Takeout adapter
#: grouped periods by their bedtime date and published 14.6 h "nights" beside
#: 0.1 h ones; a value past this is withheld and named in the import metadata
#: rather than charted.
SLEEP_QUARANTINE_HOURS = 16.0


def quarantine_sleep(aggregates: list[Aggregate]) -> tuple[list[Aggregate], list[dict[str, object]]]:
    """Drop every sleep metric of a (source, day) whose summed sleep or time
    in bed exceeds :data:`SLEEP_QUARANTINE_HOURS`; return what is kept and
    what was withheld.  Shared by the export importer and the API sync."""
    over: dict[tuple[str, str], dict[str, float]] = {}
    for item in aggregates:
        if item.definition.key in ("sleep_duration", "time_in_bed") and item.value > SLEEP_QUARANTINE_HOURS:
            over.setdefault((item.source_name, item.day), {})[item.definition.key] = round(item.value, 2)
    if not over:
        return aggregates, []
    kept = [item for item in aggregates
            if not (item.definition.key in SLEEP_KEYS and (item.source_name, item.day) in over)]
    withheld = [{"day": day, "source": source, **hours} for (source, day), hours in sorted(over.items())]
    return kept, withheld


def _float(value: object) -> float | None:
    return finite_number(value)


def _json_value(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = handle.readline()
        handle.seek(0)
        delimiter = ";" if first.count(";") > first.count(",") else ","
        yield from csv.DictReader(handle, delimiter=delimiter)


def _csv_header(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = handle.readline()
        handle.seek(0)
        delimiter = ";" if first.count(";") > first.count(",") else ","
        return set(csv.DictReader(handle, delimiter=delimiter).fieldnames or ())


def _json_records(payload: object) -> Iterable[dict[str, object]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "items", "records", "sleep", "activity", "readiness"):
        nested = payload.get(key)
        if isinstance(nested, list):
            yield from _json_records(nested)
            return
    yield payload


def _duration_minutes(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end.replace("Z", "+00:00"))
                - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def _legacy_records(files: list[Path]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in files:
        if path.suffix.casefold() == ".json":
            try:
                records.extend(_json_records(json.loads(path.read_text(encoding="utf-8-sig"))))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        elif path.suffix.casefold() == ".csv":
            records.extend(_csv_rows(path))
    return records


def _hours(value: float | None) -> float | None:
    return value / 3600 if value is not None else None


def _minutes(value: float | None) -> float | None:
    return value / 60 if value is not None else None


class _TakeoutParse:
    """Mutable state of one Takeout import: the buckets, the day range and the
    set of tables that were actually consumed."""

    def __init__(self, paths: dict[str, Path], tz: tzinfo) -> None:
        self.paths = paths
        self.tz = tz
        self.bucket: dict[tuple[str, str, str], Aggregate] = {}
        self.workouts: list[Workout] = []
        self.events: list[DeviceEvent] = []
        self.earliest: str | None = None
        self.latest: str | None = None
        self.normalized: set[str] = set()
        self.imported_vendors: Counter[str] = Counter()
        self.ring: dict[str, object] = {}
        self.timezone_history: list[dict[str, str | None]] = []

    def rows(self, name: str) -> list[dict[str, str]]:
        path = self.paths.get(name)
        if path is None:
            return []
        self.normalized.add(name)
        return list(_csv_rows(path))

    def stream(self, name: str) -> Iterable[dict[str, str]]:
        path = self.paths.get(name)
        if path is None:
            return ()
        self.normalized.add(name)
        return _csv_rows(path)

    def touch(self, observed: str) -> str:
        # A bare `day` is Oura's own local day and passes through; a
        # timestamp (heart rate is UTC `Z`) is cut at the person's midnight.
        day = local_day(observed, self.tz)
        if len(day) == 10:
            self.earliest = day if self.earliest is None else min(self.earliest, day)
            self.latest = day if self.latest is None else max(self.latest, day)
        return day

    def add(self, key: str, value: float | None, observed: str, *, source_name: str = SOURCE_NAME,
            source_vendor: str = SOURCE_NAME, day_override: str | None = None) -> None:
        day = self.touch(day_override or observed)
        if value is None or len(day) != 10:
            return
        spec = next((item for item in FIELDS.values() if item[0] == key), None)
        if spec is None:
            raise KeyError(key)
        _, name, category, unit, _ = spec
        definition = metric(key, name, category, unit, _AGGREGATION.get(key, "average"))
        item = self.bucket.setdefault(
            (source_name, key, day), Aggregate(definition, day, source_name, source_vendor)
        )
        item.add(value, observed)

    def parse_daily_scores(self) -> None:
        # File-specific score mapping is essential: all three tables call the
        # column simply `score`.
        for row in self.rows(_DAILYSLEEP_CSV):
            self.add("sleep_score", _float(row.get("score")), row.get("day") or "")
        for row in self.rows(_DAILYREADINESS_CSV):
            observed = row.get("day") or ""
            self.add("readiness_score", _float(row.get("score")), observed)
            self.add("temperature_deviation", _float(row.get("temperature_deviation")), observed)
        for row in self.rows(_DAILYACTIVITY_CSV):
            observed = row.get("day") or ""
            active = _float(row.get("active_calories"))
            total = _float(row.get("total_calories"))
            self.add("steps", _float(row.get("steps")), observed)
            self.add("activity_score", _float(row.get("score")), observed)
            self.add("active_energy", active, observed)
            resting = total - active if total is not None and active is not None and total >= active else None
            self.add("resting_energy", resting, observed)
            self.add("moderate_activity", _minutes(_float(row.get("medium_activity_time"))), observed)
            self.add("vigorous_activity", _minutes(_float(row.get("high_activity_time"))), observed)

    def parse_sleep(self) -> None:
        # A period belongs to its own `day` -- Oura's wake date, exactly what
        # the API mapper (oura._map_sleep) groups by -- never to the date its
        # bedtime falls on: an evening bedtime is the *next* day's night.
        sleep_by_day: dict[str, list[dict[str, str]]] = {}
        for row in self.rows(_SLEEPMODEL_CSV):
            day = self.touch(row.get("day") or local_day(row.get("bedtime_end") or "", self.tz))
            if len(day) == 10 and (row.get("type") or "") != "deleted":
                sleep_by_day.setdefault(day, []).append(row)
        for day, periods in sleep_by_day.items():
            self._add_sleep_day(day, periods)

    def _add_sleep_day(self, day: str, periods: list[dict[str, str]]) -> None:
        asleep = [row for row in periods if (row.get("type") or "") in _SLEEP_TYPES]
        for row in asleep:
            observed = row.get("bedtime_start") or day
            for field, key in (
                ("total_sleep_duration", "sleep_duration"), ("deep_sleep_duration", "sleep_deep"),
                ("rem_sleep_duration", "sleep_rem"), ("light_sleep_duration", "sleep_core"),
                ("awake_time", "sleep_awake"),
            ):
                self.add(key, _hours(_float(row.get(field))), observed, day_override=day)
        for row in periods:
            self.add("time_in_bed", _hours(_float(row.get("time_in_bed"))),
                     row.get("bedtime_start") or day, day_override=day)
        lows = [value for value in (_float(row.get("lowest_heart_rate")) for row in asleep) if value]
        if lows:
            self.add("lowest_sleeping_heart_rate", min(lows), day)
        main = max(asleep, key=lambda row: _float(row.get("total_sleep_duration")) or 0, default=None)
        if main:
            self.add("heart_rate_variability_rmssd", _float(main.get("average_hrv")), day)
            self.add("respiratory_rate", _float(main.get("average_breath")), day)
            self.add("sleep_efficiency", _float(main.get("efficiency")), day)

    def parse_daily_physiology(self) -> None:
        for row in self.rows(_DAILYSPO2_CSV):
            observed = row.get("day") or ""
            percentage = _json_value(row.get("spo2_percentage"))
            average = _float(percentage.get("average")) if isinstance(percentage, dict) else _float(percentage)
            self.add("blood_oxygen", average, observed)
            self.add("breathing_disturbance_index", _float(row.get("breathing_disturbance_index")), observed)
        for row in self.rows(_DAILYSTRESS_CSV):
            observed = row.get("day") or ""
            self.add("stress_high_time", _minutes(_float(row.get("stress_high"))), observed)
            self.add("recovery_high_time", _minutes(_float(row.get("recovery_high"))), observed)
        for row in self.rows(_DAILYCARDIOVASCULARAGE_CSV):
            observed = row.get("day") or ""
            self.add("cardiovascular_age", _float(row.get("vascular_age")), observed)
            self.add("pulse_wave_velocity", _float(row.get("pulse_wave_velocity")), observed)
        for row in self.rows(_VO2MAX_CSV):
            self.add("vo2_max", _float(row.get("vo2_max")), row.get("day") or row.get("timestamp") or "")
        for row in self.stream(_HEARTRATE_CSV):
            self.add("daily_heart_rate", _float(row.get("bpm")), row.get("timestamp") or "")

    def parse_imported(self) -> None:
        for name, field, key in (
            (_IMPORTEDHEARTRATE_CSV, "bpm", "daily_heart_rate"),
            (_IMPORTEDSTEPCOUNT_CSV, "steps", "steps"),
        ):
            for row in self.stream(name):
                origin = row.get("origin_source") or row.get("imported_from") or "Imported source"
                vendor = canonical_source_vendor(origin)
                self.imported_vendors[vendor] += 1
                self.add(key, _float(row.get(field)), row.get("timestamp") or "",
                         source_name=f"Oura import · {origin}", source_vendor=vendor)

    def parse_workouts(self) -> None:
        for row in self.rows(_WORKOUT_CSV):
            started = row.get("start_datetime") or ""
            if not started:
                continue
            ended = row.get("end_datetime") or None
            distance = _float(row.get("distance"))
            self.workouts.append(Workout(
                SOURCE_NAME, SOURCE_NAME, row.get("activity") or row.get("label") or "workout",
                started, ended, _duration_minutes(started, ended) if ended else None,
                _float(row.get("calories")), distance / 1000 if distance is not None else None,
            ))
            self.touch(started)

    def parse_sessions(self) -> None:
        for row in self.rows(_SESSION_CSV):
            started = row.get("start_datetime") or ""
            if not started:
                continue
            ended = row.get("end_datetime") or None
            self.workouts.append(Workout(
                SOURCE_NAME, SOURCE_NAME, row.get("type") or "session", started, ended,
                _duration_minutes(started, ended) if ended else None,
            ))
            self.touch(started)

    def parse_tags(self) -> None:
        for row in self.rows(_ENHANCEDTAG_CSV):
            started = row.get("start_time") or row.get("start_day") or ""
            if not started:
                continue
            label = row.get("custom_name") or row.get("custom_tag_name") or row.get("tag_type_code") or "tag"
            text = ": ".join(value for value in (label, row.get("comment") or "") if value)
            self.events.append(DeviceEvent(
                SOURCE_NAME, SOURCE_NAME, "Oura tag", started,
                row.get("end_time") or row.get("end_day") or None, text,
            ))
            self.touch(started)

    def parse_ring(self) -> None:
        ring_rows = self.rows(_RINGCONFIGURATION_CSV)
        if ring_rows:
            newest = ring_rows[-1]
            self.ring = {key: newest.get(key) for key in
                         ("hardware_type", "color", "design", "size", "firmware_version", "set_up_at")
                         if newest.get(key)}
        battery_rows = self.rows(_RINGBATTERYLEVEL_CSV)
        if battery_rows:
            newest = battery_rows[-1]
            self.ring["last_battery_level"] = _float(newest.get("level"))
            self.ring["last_battery_at"] = newest.get("timestamp") or ""
        self.timezone_history = [
            {key: row.get(key) for key in ("timestamp", "identifier", "offset")}
            for row in self.rows(_TIMEZONE_CSV)
        ]
        debug_rows = self.rows(_APPLICATIONDEBUGSTATE_CSV)
        if debug_rows:
            debug = _json_value(debug_rows[-1].get("ring_debug_information"))
            if isinstance(debug, list) and debug and isinstance(debug[-1], dict):
                self.ring["last_synced_at"] = debug[-1].get("ring_last_synced")


def _add_legacy_row(
    bucket: dict[tuple[str, str, str], Aggregate], row: dict[str, object], day: str, observed: str
) -> None:
    for field, (key, name, category, unit, scale) in FIELDS.items():
        value = _float(row.get(field))
        if value is None:
            continue
        definition = metric(key, name, category, unit, _AGGREGATION.get(key, "average"))
        item = bucket.setdefault((SOURCE_NAME, key, day), Aggregate(definition, day, SOURCE_NAME, SOURCE_NAME))
        item.add(value * scale, observed)


class OuraAdapter:
    key = "oura"
    vendor_name = SOURCE_NAME
    website = "https://ouraring.com/"
    fields = FIELDS

    def _legacy_parse(self, source: Path, tz: tzinfo) -> ParsedDeviceExport:
        """Keep support for the older API-shaped JSON/CSV exports."""
        files = [source] if source.is_file() else sorted(source.rglob("*.json")) + sorted(source.rglob(_ANY_CSV))
        records = _legacy_records(files)
        bucket: dict[tuple[str, str, str], Aggregate] = {}
        days: list[str] = []
        for row in records:
            observed = next((str(row.get(key) or "") for key in
                             ("day", "date", "timestamp", "start_datetime") if row.get(key)), "")
            day = local_day(observed, tz)
            if len(day) != 10:
                continue
            days.append(day)
            _add_legacy_row(bucket, row, day, observed)
        earliest, latest = (min(days), max(days)) if days else (None, None)
        aggregates, quarantined = quarantine_sleep(list(bucket.values()))
        return ParsedDeviceExport(
            aggregates=aggregates, raw_record_count=len(records),
            export_started_at=earliest, export_ended_at=latest,
            metadata={"daily_aggregate_rows": len(aggregates), "export_format": "legacy_json_or_csv",
                      "source_vendor_counts": {SOURCE_NAME: len(records)},
                      "quarantined_sleep_days": quarantined},
        )

    def parse(self, source: Path, *, tz: tzinfo | None = None) -> ParsedDeviceExport:
        """`tz` is the person's zone: a timestamped sample (heart rate,
        imported steps) belongs to the calendar day they lived it in."""
        tz = tz or zone(None)
        app_data = source / "App Data" if source.is_dir() and (source / "App Data").is_dir() else source
        is_takeout = app_data.is_dir() and any(
            path.name.casefold() in KNOWN_APP_DATA_FILES for path in app_data.glob(_ANY_CSV)
        )
        if not is_takeout:
            return self._legacy_parse(source, tz)

        paths = {path.name.casefold(): path for path in app_data.glob(_ANY_CSV)}
        file_rows: dict[str, int] = {}
        file_columns: dict[str, set[str]] = {}
        for name, path in paths.items():
            file_rows[name] = sum(1 for _ in _csv_rows(path))
            file_columns[name] = _csv_header(path)

        state = _TakeoutParse(paths, tz)
        state.parse_daily_scores()
        state.parse_sleep()
        state.parse_daily_physiology()
        state.parse_imported()
        state.parse_workouts()
        state.parse_sessions()
        state.parse_tags()
        state.parse_ring()

        aggregates, quarantined = quarantine_sleep(list(state.bucket.values()))
        metadata = _takeout_metadata(source, app_data, paths, file_rows, file_columns, state,
                                     len(aggregates), quarantined)
        return ParsedDeviceExport(
            aggregates=aggregates, workouts=state.workouts, events=state.events,
            raw_record_count=sum(file_rows.values()), export_started_at=state.earliest,
            export_ended_at=state.latest, metadata=metadata,
        )


def _takeout_metadata(source: Path, app_data: Path, paths: dict[str, Path],
                      file_rows: dict[str, int], file_columns: dict[str, set[str]],
                      state: _TakeoutParse, aggregate_rows: int, quarantined: list[dict[str, object]]) -> dict[str, object]:
    populated = {name for name, count in file_rows.items() if count}
    unsupported = sorted(
        (populated - KNOWN_APP_DATA_FILES)
        | (populated - NORMALIZED_FILES - AUDITED_RETAINED_FILES)
    )
    unexpected_columns = {
        name: sorted(file_columns.get(name, set()) - expected)
        for name, expected in NORMALIZED_FILE_COLUMNS.items()
        if file_rows.get(name, 0) and file_columns.get(name, set()) - expected
    }
    normalized_populated = sorted(populated & state.normalized)
    retained = sorted(populated & AUDITED_RETAINED_FILES)
    retained_reasons = {
        name: RETAINED_REASONS.get(name, "non-measurement product/account data retained in the source export")
        for name in retained
    }
    recognized = sum(file_rows[name] for name in normalized_populated)
    imported_count = sum(state.imported_vendors.values())
    source_counts = Counter({SOURCE_NAME: max(0, recognized - imported_count)})
    source_counts.update(state.imported_vendors)
    excluded_file_count = sum(
        1 for path in source.rglob("*") if path.is_file() and app_data not in path.parents
    ) if source.is_dir() else 0
    return {
        "export_format": "oura_takeout_csv",
        "daily_aggregate_rows": aggregate_rows,
        "quarantined_sleep_days": quarantined,
        "app_data_files": len(paths),
        "app_data_rows": sum(file_rows.values()),
        "file_rows": dict(sorted(file_rows.items())),
        "normalized_populated_files": normalized_populated,
        "retained_populated_files": retained,
        "retained_file_reasons": retained_reasons,
        "empty_known_files": sorted(
            name for name, count in file_rows.items() if name in KNOWN_APP_DATA_FILES and count == 0
        ),
        "missing_known_files": sorted(KNOWN_APP_DATA_FILES - set(paths)),
        "unsupported_populated_files": unsupported,
        "unexpected_normalized_columns": unexpected_columns,
        "excluded_non_health_files": excluded_file_count,
        "recognized_health_records": recognized,
        "source_vendor_counts": dict(source_counts),
        "ring": state.ring,
        "timezone_history": state.timezone_history,
    }
