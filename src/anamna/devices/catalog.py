from __future__ import annotations

import functools

from ..config import local_overrides
from .models import MetricDefinition


def metric(key: str, name: str, category: str, unit: str, aggregation: str = "average") -> MetricDefinition:
    return MetricDefinition(key, name, category, unit, aggregation)


HEALTHKIT_METRICS: dict[str, MetricDefinition] = {
    "HKQuantityTypeIdentifierHeight": metric("body_height", "Body height", "device_body", "cm", "latest"),
    "HKQuantityTypeIdentifierBodyMass": metric("body_weight", "Body weight", "device_body", "kg", "latest"),
    "HKQuantityTypeIdentifierBodyMassIndex": metric("body_mass_index", "Body mass index", "device_body", "kg/m²", "latest"),
    "HKQuantityTypeIdentifierBodyFatPercentage": metric("body_fat_percentage", "Body fat", "device_body", "%", "latest"),
    "HKQuantityTypeIdentifierLeanBodyMass": metric("lean_body_mass", "Lean body mass", "device_body", "kg", "latest"),
    "HKQuantityTypeIdentifierWaistCircumference": metric("waist_circumference", "Waist circumference", "device_body", "cm", "latest"),
    "HKQuantityTypeIdentifierHeartRate": metric("daily_heart_rate", "Daily heart rate", "device_recovery", "bpm"),
    "HKQuantityTypeIdentifierRestingHeartRate": metric("resting_heart_rate", "Resting heart rate", "device_recovery", "bpm"),
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": metric("walking_heart_rate", "Walking heart rate", "device_fitness", "bpm"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": metric("heart_rate_variability", "Heart rate variability (SDNN)", "device_recovery", "ms"),
    "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute": metric("heart_rate_recovery", "One-minute heart-rate recovery", "device_fitness", "bpm"),
    "HKQuantityTypeIdentifierOxygenSaturation": metric("blood_oxygen", "Blood oxygen saturation", "device_recovery", "%"),
    "HKQuantityTypeIdentifierRespiratoryRate": metric("respiratory_rate", "Respiratory rate", "device_recovery", "breaths/min"),
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": metric("sleeping_wrist_temperature", "Sleeping wrist temperature", "device_recovery", "°C"),
    "HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances": metric("breathing_disturbances", "Sleeping breathing disturbances", "device_recovery", "count"),
    "HKQuantityTypeIdentifierVO2Max": metric("vo2_max", "Cardio fitness (VO₂ max)", "device_fitness", "mL/kg/min"),
    "HKQuantityTypeIdentifierBloodPressureSystolic": metric("systolic_blood_pressure", "Systolic blood pressure", "device_recovery", "mmHg", "latest"),
    "HKQuantityTypeIdentifierBloodPressureDiastolic": metric("diastolic_blood_pressure", "Diastolic blood pressure", "device_recovery", "mmHg", "latest"),
    "HKQuantityTypeIdentifierStepCount": metric("steps", "Daily steps", "device_activity", "steps", "sum"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": metric("walking_running_distance", "Walking and running distance", "device_activity", "km", "sum"),
    "HKQuantityTypeIdentifierDistanceCycling": metric("cycling_distance", "Cycling distance", "device_activity", "km", "sum"),
    "HKQuantityTypeIdentifierDistanceSwimming": metric("swimming_distance", "Swimming distance", "device_activity", "m", "sum"),
    "HKQuantityTypeIdentifierSwimmingStrokeCount": metric("swimming_strokes", "Swimming strokes", "device_activity", "count", "sum"),
    "HKQuantityTypeIdentifierFlightsClimbed": metric("flights_climbed", "Flights climbed", "device_activity", "flights", "sum"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": metric("active_energy", "Active energy", "device_activity", "kcal", "sum"),
    "HKQuantityTypeIdentifierBasalEnergyBurned": metric("resting_energy", "Resting energy", "device_activity", "kcal", "sum"),
    "HKQuantityTypeIdentifierAppleExerciseTime": metric("exercise_minutes", "Exercise time", "device_activity", "min", "sum"),
    "HKQuantityTypeIdentifierAppleStandTime": metric("stand_minutes", "Stand time", "device_activity", "min", "sum"),
    "HKQuantityTypeIdentifierPhysicalEffort": metric("physical_effort", "Physical effort", "device_activity", "MET-like effort"),
    "HKQuantityTypeIdentifierWalkingSpeed": metric("walking_speed", "Walking speed", "device_mobility", "km/h"),
    "HKQuantityTypeIdentifierWalkingStepLength": metric("walking_step_length", "Walking step length", "device_mobility", "cm"),
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": metric("walking_double_support", "Walking double-support time", "device_mobility", "%"),
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage": metric("walking_asymmetry", "Walking asymmetry", "device_mobility", "%"),
    "HKQuantityTypeIdentifierAppleWalkingSteadiness": metric("walking_steadiness", "Walking steadiness", "device_mobility", "%"),
    "HKQuantityTypeIdentifierStairAscentSpeed": metric("stair_ascent_speed", "Stair ascent speed", "device_mobility", "m/s"),
    "HKQuantityTypeIdentifierStairDescentSpeed": metric("stair_descent_speed", "Stair descent speed", "device_mobility", "m/s"),
    "HKQuantityTypeIdentifierSixMinuteWalkTestDistance": metric("six_minute_walk", "Six-minute walk distance", "device_mobility", "m"),
    "HKQuantityTypeIdentifierTimeInDaylight": metric("time_in_daylight", "Time in daylight", "device_environment", "min", "sum"),
    "HKQuantityTypeIdentifierEnvironmentalAudioExposure": metric("environmental_audio", "Environmental sound exposure", "device_environment", "dBA"),
    "HKQuantityTypeIdentifierHeadphoneAudioExposure": metric("headphone_audio", "Headphone sound exposure", "device_environment", "dBA"),
    "HKQuantityTypeIdentifierEnvironmentalSoundReduction": metric("environmental_sound_reduction", "Environmental sound reduction", "device_environment", "dBA"),
}

SLEEP_METRICS = {
    "HKCategoryValueSleepAnalysisAsleep": metric("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisAsleepUnspecified": metric("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisAsleepCore": metric("sleep_core", "Core sleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisAsleepDeep": metric("sleep_deep", "Deep sleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisAsleepREM": metric("sleep_rem", "REM sleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisAwake": metric("sleep_awake", "Awake during sleep", "device_sleep", "hours", "sum"),
    "HKCategoryValueSleepAnalysisInBed": metric("time_in_bed", "Time in bed", "device_sleep", "hours", "sum"),
}

#: The device metrics a person actually came to read, in the order a clinician
#: would want them: heart first, then breathing, sleep, activity, body.  Forty
#: further metrics exist -- walking asymmetry, headphone exposure -- and they
#: are real, but they are not what a summary leads with.
CORE_METRIC_KEYS = (
    "ecg_heart_rate",
    "systolic_blood_pressure",
    "diastolic_blood_pressure",
    "resting_heart_rate",
    "heart_rate_variability",
    "blood_oxygen",
    "respiratory_rate",
    "sleep_duration",
    "steps",
    "exercise_minutes",
    "vo2_max",
    "body_weight",
    "body_fat_percentage",
)

#: Running daily totals: the number grows through the day, so the day still in
#: progress is a partial reading, not a low one.  Sleep nights are summed too
#: but are dated by the wake day and complete once the person is up.
CUMULATIVE_KEYS = frozenset(
    {d.key for d in HEALTHKIT_METRICS.values() if d.aggregation == "sum"}
    | {"active_minutes", "sedentary_minutes", "light_activity", "total_energy", "elevation",
       "moderate_activity", "vigorous_activity", "stand_hours", "intensity_minutes",
       "high_activity_time", "medium_activity_time", "low_activity_time", "stress_high_time",
       "recovery_high_time"}
)

DEVICE_CATEGORY_LABELS = {
    "device_body": "Body composition",
    "device_activity": "Daily activity",
    "device_fitness": "Fitness",
    "device_mobility": "Mobility",
    "device_sleep": "Sleep",
    "device_recovery": "Recovery and vitals",
    "device_environment": "Environment and hearing",
}


@functools.lru_cache(maxsize=4096)
def canonical_source_vendor(source_name: str) -> str:
    """The vendor whose rules apply to a source, from its name alone.

    Apple Health names a reading's source after the device that took it, and a
    device its owner renamed ("Kitchen phone") carries no vendor in its name;
    an installation lists those under `apple_device_names` in its
    `local_overrides.json` (see config).  Cached: an export asks once per record.
    """
    folded = source_name.casefold().replace("\u00a0", " ")
    if "openwearables" in folded:
        return "OpenWearables"
    if "oura" in folded:
        return "Oura"
    if folded == "connect" or "garmin" in folded:
        return "Garmin"
    if (
        "apple" in folded or "iphone" in folded or "watch" in folded
        or folded in {"health", "clock"} or folded in _own_apple_devices()
    ):
        return "Apple Health"
    if "zepp" in folded:
        return "Zepp Life"
    return source_name


def _own_apple_devices() -> set[str]:
    return {name.casefold().replace("\u00a0", " ") for name in local_overrides().get("apple_device_names", ())}


def _first_tier(*tiers: tuple[bool, int]) -> int:
    """The rank of the first tier whose condition holds; 10 (unknown source) otherwise."""
    return next((rank for holds, rank in tiers if holds), 10)


def source_priority(metric_key: str, source_vendor: str, source_name: str) -> int:
    """Which row wins when several sources measured the same metric that day.

    An aggregation server re-serves what the devices themselves recorded, so
    it sits below every named vendor and above the unknown bucket: on a day a
    direct export covers, that export shows; on a day only the server covers \u2014
    everything since the last manual export \u2014 the server's row shows.
    """
    vendor = source_vendor.casefold()
    name = source_name.casefold().replace("\u00a0", " ")
    # OpenWearables is a transport: its daily summary can repeat a reading
    # already held from the device's own export.  A named direct source always
    # outranks that bridge, even when the source is new to this catalog.
    if vendor == "openwearables":
        return 90
    if metric_key == "ecg_heart_rate":
        return _first_tier((vendor in {"kardia", "alivecor"}, 0), ("watch" in name, 1))
    if metric_key in {"systolic_blood_pressure", "diastolic_blood_pressure", "blood_pressure_pulse"}:
        return _first_tier((vendor == "garmin", 0), (vendor == "apple health", 1))
    if metric_key == "lowest_sleeping_heart_rate":
        return _first_tier((vendor == "oura", 0))
    if metric_key in {
        "sleep_score", "readiness_score", "activity_score", "recovery_score",
        "stress_high_time", "recovery_high_time", "resilience_score",
    }:
        return _first_tier((vendor == "oura", 0))
    if metric_key.startswith("sleep_") or metric_key in {"sleep_duration", "time_in_bed", "respiratory_rate"}:
        return _first_tier((vendor == "oura", 0), ("watch" in name, 1))
    if metric_key in {"body_weight", "body_mass_index", "body_fat_percentage", "lean_body_mass"}:
        return _first_tier((vendor == "garmin", 0), (vendor == "zepp life", 1))
    return _first_tier(("watch" in name, 0), (vendor == "oura", 1), ("iphone" in name, 2))
