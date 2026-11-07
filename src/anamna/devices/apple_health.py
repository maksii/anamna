from __future__ import annotations

import html
import re
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

from .catalog import HEALTHKIT_METRICS, SLEEP_METRICS, canonical_source_vendor, metric
from .ecg import measure, read_cached
from .models import Aggregate, DeviceEvent, ParsedDeviceExport, Workout
from .timezone import local_day, zone
from .units import convert_quantity, finite_number


ATTRIBUTE = re.compile(rb'\b(\w+)="([^"]*)"')
APPLE_HEALTH = "Apple Health"
APPLE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"
ECG_HEART_RATE = metric("ecg_heart_rate", "ECG heart rate", "device_recovery", "bpm", "latest")
DEVICE_EVENTS = {
    "HKCategoryTypeIdentifierHighHeartRateEvent": "High heart-rate notification",
    "HKCategoryTypeIdentifierLowHeartRateEvent": "Low heart-rate notification",
    "HKCategoryTypeIdentifierIrregularHeartRhythmEvent": "Irregular rhythm notification",
    "HKCategoryTypeIdentifierLowCardioFitnessEvent": "Low cardio-fitness notification",
    "HKCategoryTypeIdentifierMindfulSession": "Mindful session",
    "HKCategoryTypeIdentifierEnvironmentalAudioExposureEvent": "Environmental audio exposure event",
    "HKCategoryTypeIdentifierHeadphoneAudioExposureEvent": "Headphone audio exposure event",
    "HKCategoryTypeIdentifierAudioExposureEvent": "Audio exposure event",
}
RETAINED_SETTING_TYPES = {"HKDataTypeSleepDurationGoal"}
STAND_HOURS = metric("stand_hours", "Stand hours", "device_activity", "hours", "sum")


def _attributes(line: bytes) -> dict[str, str]:
    return {
        key.decode("ascii"): html.unescape(value.decode("utf-8", "replace"))
        for key, value in ATTRIBUTE.findall(line)
    }


def _number(value: str | None) -> float | None:
    return finite_number(value)


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, APPLE_DATE_FORMAT).isoformat()
    except ValueError:
        return value


def _source(source_name: str) -> tuple[str, str]:
    clean = source_name.replace("\u00a0", " ").strip()
    return clean, canonical_source_vendor(clean)


def _plus_seconds(started_at: str, seconds: float) -> str | None:
    """When a recording of this length ended, to the second.

    The length is samples over a measured sampling rate, so it carries a
    fractional tail; an event that ends at 22:53:20.999299 is that arithmetic
    showing through rather than anything the watch recorded.
    """
    if not seconds:
        return None
    try:
        return (datetime.fromisoformat(started_at) + timedelta(seconds=round(seconds))).isoformat()
    except ValueError:
        return None


def _sleep_hours(start: str, end: str) -> float | None:
    try:
        delta = datetime.strptime(end, APPLE_DATE_FORMAT) - datetime.strptime(start, APPLE_DATE_FORMAT)
    except ValueError:
        return None
    seconds = delta.total_seconds()
    return seconds / 3600 if 0 < seconds <= 24 * 3600 else None


class _LocalDays:
    """`local_day` for millions of Apple timestamps, memoised by the hour.

    Apple writes each sample with the phone's offset at export time; the day
    is taken in the person's zone instead, so a sample at 00:30 +0200 that is
    01:30 in Kyiv summer time lands on the day the person lived it.  When the
    offset and the zone are both whole hours the day depends only on the
    hour, which keeps the memo to ~90k entries for ten years of data.
    """

    def __init__(self, tz: tzinfo):
        self.tz = tz
        whole = all((tz.utcoffset(datetime(2024, month, 1)) or timedelta()).seconds % 3600 == 0 for month in (1, 7))
        self.width = 13 if whole else 16
        self.memo: dict[str, str] = {}

    def __call__(self, stamp: str) -> str:
        offset = stamp[19:]
        width = self.width if offset.endswith("00") else 16
        key = stamp[:width] + offset
        day = self.memo.get(key)
        if day is None:
            padded = stamp[:width] + (":00:00" if width == 13 else ":00") + offset
            day = self.memo[key] = local_day(padded, self.tz)
        return day


def _sleep_sessions(sleep_intervals, tz: tzinfo | None = None):
    """Assign connected source intervals to their session's local wake date.

    An in-bed interval can connect stages separated by recorded wakefulness;
    adjacent core/REM/deep intervals also establish the same session. We never
    invent sleep across a gap or use a noon cutoff that misdates shift workers.
    Separate naps stay separate intervals even when a daily total includes both.
    """
    by_source: dict[tuple[str, str], set[tuple[datetime, datetime]]] = {}
    for (source_name, source_vendor, _key), (_definition, intervals) in sleep_intervals.items():
        by_source.setdefault((source_name, source_vendor), set()).update(intervals)
    sessions = {}
    for identity, intervals in by_source.items():
        joined = _merge_intervals(intervals)
        sessions[identity] = ([start for start, _ in joined], joined)
    for (source_name, source_vendor, _key), (definition, intervals) in sleep_intervals.items():
        starts, joined = sessions[(source_name, source_vendor)]
        by_day: dict[str, list[tuple[datetime, datetime]]] = {}
        for start, end in intervals:
            session_end = joined[bisect_right(starts, start) - 1][1]
            day = (session_end.astimezone(tz) if tz else session_end).date().isoformat()
            by_day.setdefault(day, []).append((start, end))
        for day, day_intervals in by_day.items():
            # Summary asleep and stage samples can cover the same hour. Union
            # each metric once, while retaining every disjoint recorded nap.
            merged = _merge_intervals(day_intervals)
            for start, end in merged:
                yield definition, day, source_name, source_vendor, start, end


def _merge_intervals(intervals):
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class _ExportState:
    """Everything one pass over export.xml accumulates, with a method per element kind."""

    def __init__(self, tz: tzinfo):
        self.day_of = _LocalDays(tz)
        self.aggregates: dict[tuple[str, str, str], Aggregate] = {}
        self.sleep_intervals: dict[tuple, tuple[object, list[tuple[datetime, datetime]]]] = {}
        self.workouts: list[Workout] = []
        self.events: list[DeviceEvent] = []
        self.type_counts: Counter[str] = Counter()
        self.source_counts: Counter[str] = Counter()
        self.unknown_types: Counter[str] = Counter()
        self.retained_setting_types: Counter[str] = Counter()
        self.raw_records = 0
        self.duplicate_samples = 0
        self.earliest: str | None = None
        self.latest: str | None = None
        self.seen_samples: set[int] = set()
        self.identity: dict[str, str] = {}
        self.export_date: str | None = None

    def touch(self, day: str) -> None:
        self.earliest = day if self.earliest is None else min(self.earliest, day)
        self.latest = day if self.latest is None else max(self.latest, day)

    def add(self, definition, day: str, source_name: str, source_vendor: str, value: float, observed_at: str) -> None:
        self.touch(day)
        key = (source_name, definition.key, day)
        aggregate = self.aggregates.get(key)
        if aggregate is None:
            aggregate = Aggregate(definition, day, source_name, source_vendor)
            self.aggregates[key] = aggregate
        aggregate.add(value, observed_at)

    def line(self, line: bytes) -> None:
        if line.startswith(b"<Record "):
            self.record(line)
        elif line.startswith(b"<Workout "):
            self.workout(line)
        elif line.startswith(b"<Correlation "):
            self.raw_records += 1
            _, source_vendor = _source(_attributes(line).get("sourceName", APPLE_HEALTH))
            self.source_counts[source_vendor] += 1
        elif line.startswith(b"<ActivitySummary "):
            self.raw_records += 1
            self.source_counts[APPLE_HEALTH] += 1
        elif line.startswith(b"<Me "):
            attrs = _attributes(line)
            self.identity = {
                "date_of_birth": attrs.get("HKCharacteristicTypeIdentifierDateOfBirth", ""),
                "biological_sex": attrs.get("HKCharacteristicTypeIdentifierBiologicalSex", "").removeprefix("HKBiologicalSex").casefold(),
            }
        elif line.startswith(b"<ExportDate "):
            self.export_date = _iso(_attributes(line).get("value"))

    def record(self, line: bytes) -> None:
        self.raw_records += 1
        attrs = _attributes(line)
        healthkit_type = attrs.get("type", "")
        source_name, source_vendor = _source(attrs.get("sourceName", APPLE_HEALTH))
        start = attrs.get("startDate", "")
        end = attrs.get("endDate", start)
        value_text = attrs.get("value", "")
        if start:
            self.touch(start[:10])
        self.type_counts[healthkit_type] += 1
        self.source_counts[source_vendor] += 1
        signature = hash((healthkit_type, source_name, start, end, value_text, attrs.get("unit", "")))
        if signature in self.seen_samples:
            self.duplicate_samples += 1
            return
        self.seen_samples.add(signature)

        definition = HEALTHKIT_METRICS.get(healthkit_type)
        numeric = _number(value_text)
        if definition and numeric is not None and start:
            self.quantity(definition, numeric, attrs, start, source_name, source_vendor)
        elif healthkit_type == "HKCategoryTypeIdentifierSleepAnalysis" and start and end:
            self.sleep(start, end, value_text, source_name, source_vendor)
        elif healthkit_type == "HKCategoryTypeIdentifierAppleStandHour" and start:
            # A stood category contributes one completed stand hour;
            # an idle category is retained in the immutable source
            # but is not a measured hour.
            if value_text.endswith("Stood"):
                self.add(STAND_HOURS, self.day_of(start), source_name, source_vendor, 1.0, start)
        elif healthkit_type in RETAINED_SETTING_TYPES:
            self.retained_setting_types[healthkit_type] += 1
        else:
            self.event(healthkit_type, start, end, value_text, source_name, source_vendor)

    def quantity(self, definition, numeric, attrs, start, source_name, source_vendor) -> None:
        source_unit = attrs.get("unit", "")
        # HealthKit stores BMI as a scalar count; the ledger
        # displays the conventional kg/m² notation for it.
        # https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/bodymassindex
        if definition.key == "body_mass_index" and source_unit == "count":
            source_unit = definition.unit
        numeric = convert_quantity(numeric, source_unit, definition.unit)
        if definition.unit == "%" and abs(numeric) <= 1:
            numeric *= 100
        self.add(definition, self.day_of(start), source_name, source_vendor, numeric, start)

    def sleep(self, start, end, value_text, source_name, source_vendor) -> None:
        hours = _sleep_hours(start, end)
        sleep_definition = SLEEP_METRICS.get(value_text)
        if hours is None or not sleep_definition:
            return
        definitions = [sleep_definition]
        if "Asleep" in value_text and sleep_definition.key != "sleep_duration":
            definitions.append(metric("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"))
        for sleep_metric in definitions:
            _, intervals = self.sleep_intervals.setdefault(
                (source_name, source_vendor, sleep_metric.key), (sleep_metric, [])
            )
            intervals.append((datetime.strptime(start, APPLE_DATE_FORMAT), datetime.strptime(end, APPLE_DATE_FORMAT)))

    def event(self, healthkit_type, start, end, value_text, source_name, source_vendor) -> None:
        event_type = DEVICE_EVENTS.get(healthkit_type)
        if event_type and start:
            self.events.append(
                DeviceEvent(
                    source_name, source_vendor, event_type, _iso(start) or start,
                    _iso(end), value_text=value_text or None,
                )
            )
        elif healthkit_type not in SLEEP_METRICS:
            self.unknown_types[healthkit_type] += 1

    def workout(self, line: bytes) -> None:
        self.raw_records += 1
        attrs = _attributes(line)
        source_name, source_vendor = _source(attrs.get("sourceName", APPLE_HEALTH))
        self.source_counts[source_vendor] += 1
        started = attrs.get("startDate")
        if not started:
            return
        self.touch(started[:10])
        workout_type = attrs.get("workoutActivityType", "Workout").removeprefix("HKWorkoutActivityType")
        self.workouts.append(
            Workout(
                source_name=source_name,
                source_vendor=source_vendor,
                workout_type=re.sub(r"(?<!^)([A-Z])", r" \1", workout_type),
                started_at=_iso(started) or started,
                ended_at=_iso(attrs.get("endDate")),
                duration_minutes=convert_quantity(_number(attrs.get("duration")), attrs.get("durationUnit", "min"), "min"),
                energy_kcal=convert_quantity(_number(attrs.get("totalEnergyBurned")), attrs.get("totalEnergyBurnedUnit", "kcal"), "kcal"),
                distance_km=convert_quantity(_number(attrs.get("totalDistance")), attrs.get("totalDistanceUnit", "km"), "km"),
            )
        )

    def ecg(self, path: Path, tz: tzinfo) -> bool:
        """Add one electrocardiogram file; True when its heart rate was measured."""
        # The waveform is read, not just the header: Apple prints no heart
        # rate in the export, so the rate of every recording would otherwise
        # be lost even though the samples that carry it are right there.
        recording = read_cached(path)
        if recording is None or not recording.recorded_at:
            return False
        started = recording.recorded_at
        rate = measure(recording).get("heart_rate")
        if rate:
            self.add(ECG_HEART_RATE, local_day(started, tz), recording.device, APPLE_HEALTH, float(rate), started)
        self.events.append(
            DeviceEvent(
                source_name=recording.device,
                source_vendor=APPLE_HEALTH,
                event_type="Electrocardiogram",
                started_at=started,
                ended_at=_plus_seconds(started, recording.duration_seconds),
                value_text=recording.classification,
                value_numeric=round(float(rate), 1) if rate else None,
                unit="bpm" if rate else None,
                source_file=str(path.resolve()),
            )
        )
        return bool(rate)


class AppleHealthAdapter:
    key = "apple_health"
    vendor_name = APPLE_HEALTH
    website = "https://www.apple.com/health/"

    def parse(self, source: Path, tz: tzinfo | None = None) -> ParsedDeviceExport:
        tz = tz or zone(None)
        export = source / "export.xml" if source.is_dir() else source
        if not export.is_file():
            raise FileNotFoundError(f"Apple Health export.xml not found under {source}")

        state = _ExportState(tz)
        with export.open("rb", buffering=16 * 1024 * 1024) as handle:
            for raw_line in handle:
                state.line(raw_line.lstrip())

        for definition, day, source_name, source_vendor, start, end in _sleep_sessions(state.sleep_intervals, tz):
            state.add(definition, day, source_name, source_vendor, (end - start).total_seconds() / 3600, end.isoformat())

        export_root = export.parent
        ecg_dir = export_root / "electrocardiograms"
        ecg_files = sorted(ecg_dir.glob("*.csv")) if ecg_dir.is_dir() else []
        measured_ecgs = sum(state.ecg(path, tz) for path in ecg_files)

        route_dir = export_root / "workout-routes"
        routes = sorted(route_dir.glob("*.gpx")) if route_dir.is_dir() else []
        return ParsedDeviceExport(
            aggregates=list(state.aggregates.values()),
            workouts=state.workouts,
            events=state.events,
            raw_record_count=state.raw_records,
            export_started_at=state.earliest,
            export_ended_at=state.latest,
            metadata={
                "healthkit_export_version": 14,
                "type_counts": dict(state.type_counts),
                "source_vendor_counts": dict(state.source_counts),
                "unknown_type_counts": dict(state.unknown_types),
                "retained_setting_type_counts": dict(state.retained_setting_types),
                "deduplicated_samples": state.duplicate_samples,
                "daily_aggregate_rows": len(state.aggregates),
                "ecg_files": len(ecg_files),
                "ecg_rate_measured": measured_ecgs,
                "workout_route_files": len(routes),
                "cda_file": str((export_root / "export_cda.xml").resolve()) if (export_root / "export_cda.xml").is_file() else None,
                "identity": state.identity,
                "export_date": state.export_date,
            },
        )
