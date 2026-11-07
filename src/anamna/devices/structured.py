from __future__ import annotations

import csv
import json
import struct
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .catalog import metric
from .models import Aggregate, ParsedDeviceExport
from .oura_export import OuraAdapter as OuraAdapter
from .units import finite_number


def _json_records(payload: object) -> Iterable[dict[str, object]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "items", "records", "sleep", "activity", "readiness"):
        value = payload.get(key)
        if isinstance(value, list):
            yield from _json_records(value)
            return
    yield payload


def _rows(source: Path) -> Iterable[dict[str, object]]:
    files = [source] if source.is_file() else sorted(source.rglob("*.json")) + sorted(source.rglob("*.csv"))
    for path in files:
        if path.suffix.casefold() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            yield from _json_records(payload)
        elif path.suffix.casefold() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)


def _float(value: object) -> float | None:
    return finite_number(value)


def _garmin_observed_at(row: dict[str, object]) -> str:
    value: object | None = None
    metadata = row.get("metaData")
    if isinstance(metadata, dict):
        value = metadata.get("calendarDate")
    if value is None:
        value = next((row[key] for key in StructuredAdapter.date_fields if row.get(key)), None)
    if isinstance(value, list) and len(value) >= 3:
        parts = [int(item) for item in value[:6]]
        parts += [0] * (6 - len(parts))
        try:
            return datetime(*parts).isoformat()
        except ValueError:
            return ""
    return str(value or "")


def _fit_message_numbers(data: bytes) -> set[int]:
    """Global message numbers defined in one FIT file; raises on a malformed file."""
    header_size = data[0]
    data_size = struct.unpack_from("<I", data, 4)[0]
    position = header_size
    end = header_size + data_size
    definitions: dict[int, tuple[int, list[tuple[int, int, int]]]] = {}
    message_numbers: set[int] = set()
    while position < end:
        header = data[position]
        position += 1
        if header & 0x80:
            local = (header >> 5) & 0x03
            _, fields = definitions[local]
            position += sum(size for _, size, _ in fields)
            continue
        local = header & 0x0F
        if not header & 0x40:
            _, fields = definitions[local]
            position += sum(size for _, size, _ in fields)
            continue
        position += 1
        architecture = data[position]
        position += 1
        endian = ">" if architecture else "<"
        global_number = struct.unpack_from(endian + "H", data, position)[0]
        position += 2
        field_count = data[position]
        position += 1
        fields = []
        for _ in range(field_count):
            number, size, base_type = data[position : position + 3]
            position += 3
            fields.append((number, size, base_type))
        definitions[local] = (global_number, fields)
        message_numbers.add(global_number)
        if header & 0x20:
            developer_count = data[position]
            position += 1 + developer_count * 3
    return message_numbers


def _fit_archive_counts(path: Path) -> dict[str, int]:
    """Count Garmin wellness FIT message types without treating them as new samples.

    The account export includes the same blood-pressure and scale records in
    JSON and in a ZIP of tiny FIT files. JSON remains the canonical value
    source; FIT definitions are reconciled so a missing export segment is
    visible in metadata rather than silently double-counted.
    """
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if not entry.filename.casefold().endswith(".fit"):
                continue
            data = archive.read(entry)
            try:
                message_numbers = _fit_message_numbers(data)
            except (IndexError, KeyError, struct.error):
                counts["invalid"] += 1
                continue
            counts["entries"] += 1
            if 51 in message_numbers:
                counts["blood_pressure"] += 1
            elif 30 in message_numbers:
                counts["weight_scale"] += 1
            else:
                counts["other"] += 1
    return dict(counts)


class StructuredAdapter:
    key = ""
    vendor_name = ""
    website = ""
    fields: dict[str, tuple[str, str, str, str, float]] = {}
    date_fields = ("day", "date", "calendarDate", "timestamp", "start_datetime", "startTimeLocal")

    def parse(self, source: Path, **_options) -> ParsedDeviceExport:
        aggregates: dict[tuple[str, str], Aggregate] = {}
        raw_count = 0
        earliest: str | None = None
        latest: str | None = None
        for row in _rows(source):
            raw_count += 1
            observed = next((str(row[key]) for key in self.date_fields if row.get(key)), "")
            if len(observed) < 10:
                continue
            day = observed[:10]
            earliest = day if earliest is None else min(earliest, day)
            latest = day if latest is None else max(latest, day)
            for field, (key, name, category, unit, scale) in self.fields.items():
                value = _float(row.get(field))
                if value is None:
                    continue
                definition = metric(key, name, category, unit, "latest")
                aggregate = aggregates.get((key, day))
                if aggregate is None:
                    aggregate = Aggregate(definition, day, self.vendor_name, self.vendor_name)
                    aggregates[(key, day)] = aggregate
                aggregate.add(value * scale, observed)
        return ParsedDeviceExport(
            aggregates=list(aggregates.values()),
            raw_record_count=raw_count,
            export_started_at=earliest,
            export_ended_at=latest,
            metadata={"daily_aggregate_rows": len(aggregates)},
        )


_BLOOD_PRESSURE_FIELDS = (
    ("systolic", ("systolic_blood_pressure", "Systolic blood pressure", "device_recovery", "mmHg")),
    ("diastolic", ("diastolic_blood_pressure", "Diastolic blood pressure", "device_recovery", "mmHg")),
    ("pulse", ("blood_pressure_pulse", "Pulse during blood-pressure reading", "device_recovery", "bpm")),
)
# field, metric key, name, unit, scale to the metric unit, plausible low, plausible high
_SCALE_COMPOSITION_FIELDS = (
    ("bmi", "body_mass_index", "Body mass index", "kg/m²", 1, 8, 100),
    ("bodyFat", "body_fat_percentage", "Body fat", "%", 1, 1, 75),
    ("bodyWater", "body_water_percentage", "Body water", "%", 1, 1, 80),
    ("boneMass", "bone_mass", "Bone mass", "kg", 0.001, 0.1, 20),
    ("muscleMass", "muscle_mass", "Muscle mass", "kg", 0.001, 1, 200),
)


class _GarminExportState:
    """Accumulators for one Garmin account export, with a method per record kind."""

    def __init__(self, vendor_name: str, fields: dict[str, tuple[str, str, str, str, float]]):
        self.vendor_name = vendor_name
        self.fields = fields
        self.aggregates: dict[tuple[str, str, str], Aggregate] = {}
        self.earliest: str | None = None
        self.latest: str | None = None
        self.scanned_records = 0
        self.recognized_records = 0
        self.blood_pressure_records = 0
        self.biometric_profile_records = 0
        self.height_records = 0
        self.weight_records = 0
        self.scale_records = 0
        self.missing_measurements = 0
        self.excluded: list[dict[str, object]] = []

    def note_observed(self, observed: str) -> None:
        if len(observed) < 10:
            return
        day = observed[:10]
        self.earliest = day if self.earliest is None else min(self.earliest, day)
        self.latest = day if self.latest is None else max(self.latest, day)

    def add(self, definition, value: float, observed: str, source_name: str) -> None:
        if len(observed) < 10:
            return
        self.note_observed(observed)
        day = observed[:10]
        key = (source_name, definition.key, day)
        aggregate = self.aggregates.get(key)
        if aggregate is None:
            aggregate = Aggregate(definition, day, source_name, self.vendor_name)
            self.aggregates[key] = aggregate
        aggregate.add(value, observed)

    def plausible(self, name: str, value: float, low: float, high: float, observed: str) -> bool:
        if value == 0:
            self.missing_measurements += 1
            return False
        if low <= value <= high:
            return True
        self.excluded.append({"metric": name, "value": value, "observed_at": observed, "reason": f"outside {low}-{high}"})
        return False

    def record(self, row: dict, name: str, observed: str) -> bool:
        """Take one JSON row; True when it contributed a recognised value."""
        if name.startswith("BloodPressureFile_"):
            return self.blood_pressure(row, observed)
        if name.endswith("_userBioMetrics.json"):
            return self.profile(row, observed)
        return self.generic(row, observed)

    def blood_pressure(self, row: dict, observed: str) -> bool:
        pressure = row.get("bloodPressure")
        if not isinstance(pressure, dict):
            return False
        recognized = False
        for field, definition_args in _BLOOD_PRESSURE_FIELDS:
            value = _float(pressure.get(field))
            if value is not None:
                self.add(metric(*definition_args), value, observed, "Garmin Connect blood pressure")
                recognized = True
        if recognized:
            self.blood_pressure_records += 1
        return recognized

    def profile(self, row: dict, observed: str) -> bool:
        self.biometric_profile_records += 1
        recognized = False
        height = _float(row.get("height"))
        weight = row.get("weight")
        if height is not None:
            self.height_records += 1
            if self.plausible("body_height", height, 100, 250, observed):
                self.add(metric("body_height", "Body height", "device_body", "cm", "latest"), height, observed, "Garmin Connect profile")
                recognized = True
        if isinstance(weight, dict):
            self.weight_records += 1
            recognized = self.scale_weight(weight, observed) or recognized
        return recognized

    def scale_weight(self, weight: dict, observed: str) -> bool:
        recognized = False
        source_type = str(weight.get("sourceType") or "Garmin Connect")
        source_name = "Garmin Index Scale" if source_type == "INDEX_SCALE" else "Garmin Connect user entry"
        if source_type == "INDEX_SCALE":
            self.scale_records += 1
        raw_weight = _float(weight.get("weight"))
        weight_is_plausible = False
        if raw_weight is not None:
            recognized = True
            weight_value = raw_weight * 0.001
            weight_is_plausible = self.plausible("body_weight", weight_value, 30, 300, observed)
            if weight_is_plausible:
                self.add(metric("body_weight", "Body weight", "device_body", "kg", "latest"), weight_value, observed, source_name)
        # Composition fields from a scale record with an
        # implausible weight are treated as one bad capture.
        # The source row remains represented in metadata.
        if raw_weight is not None and not weight_is_plausible:
            return recognized
        for field, key, name, unit, scale, low, high in _SCALE_COMPOSITION_FIELDS:
            raw_value = _float(weight.get(field))
            if raw_value is None:
                continue
            value = raw_value * scale
            if self.plausible(key, value, low, high, observed):
                self.add(metric(key, name, "device_body", unit, "latest"), value, observed, source_name)
                recognized = True
        return recognized

    def generic(self, row: dict, observed: str) -> bool:
        if len(observed) < 10:
            return False
        recognized = False
        for field, (key, name, category, unit, scale) in self.fields.items():
            value = _float(row.get(field))
            if value is None:
                continue
            self.add(metric(key, name, category, unit, "latest"), value * scale, observed, self.vendor_name)
            recognized = True
        return recognized

    def finish_row(self, recognized: bool, observed: str) -> None:
        if recognized:
            self.note_observed(observed)
            self.recognized_records += 1


def _files_with_suffix(source: Path, suffix: str) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.casefold() == suffix else []
    return sorted(source.rglob(f"*{suffix}"))


def _scan_garmin_json(state: "_GarminExportState", path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    records = list(_json_records(payload))
    state.scanned_records += len(records)
    for row in records:
        observed = _garmin_observed_at(row)
        state.finish_row(state.record(row, path.name, observed), observed)


def _scan_garmin_csv(state: "_GarminExportState", path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            state.scanned_records += 1
            observed = _garmin_observed_at(row)
            state.finish_row(state.generic(row, observed), observed)


def _garmin_fit_counts(source: Path) -> dict[str, int]:
    fit_counts: dict[str, int] = {}
    if not source.is_dir():
        return fit_counts
    for archive in sorted(source.rglob("*.zip")):
        for key, value in _fit_archive_counts(archive).items():
            fit_counts[key] = fit_counts.get(key, 0) + value
    return fit_counts


class GarminAdapter(StructuredAdapter):
    key = "garmin"
    vendor_name = "Garmin"
    website = "https://www.garmin.com/"
    fields = {
        "steps": ("steps", "Daily steps", "device_activity", "steps", 1),
        "totalSteps": ("steps", "Daily steps", "device_activity", "steps", 1),
        "restingHeartRate": ("resting_heart_rate", "Resting heart rate", "device_recovery", "bpm", 1),
        "averageStressLevel": ("stress_level", "Average stress level", "device_recovery", "score", 1),
        "sleepTimeSeconds": ("sleep_duration", "Time asleep", "device_sleep", "hours", 1 / 3600),
        "bodyBatteryHighestValue": ("body_battery_high", "Body Battery high", "device_recovery", "score", 1),
        "bodyBatteryLowestValue": ("body_battery_low", "Body Battery low", "device_recovery", "score", 1),
        "moderateIntensityMinutes": ("moderate_activity", "Moderate activity", "device_activity", "min", 1),
        "vigorousIntensityMinutes": ("vigorous_activity", "Vigorous activity", "device_activity", "min", 1),
        "floorsAscended": ("flights_climbed", "Flights climbed", "device_activity", "flights", 1),
        "weight": ("body_weight", "Body weight", "device_body", "kg", 1),
        "bmi": ("body_mass_index", "Body mass index", "device_body", "kg/m²", 1),
    }

    def parse(self, source: Path, **_options) -> ParsedDeviceExport:
        json_files = _files_with_suffix(source, ".json")
        csv_files = _files_with_suffix(source, ".csv")
        state = _GarminExportState(self.vendor_name, self.fields)

        for path in json_files:
            _scan_garmin_json(state, path)
        for path in csv_files:
            _scan_garmin_csv(state, path)

        fit_counts = _garmin_fit_counts(source)
        reconciliation = {
            "blood_pressure_matches": fit_counts.get("blood_pressure", 0) == state.blood_pressure_records,
            "scale_matches": fit_counts.get("weight_scale", 0) == state.scale_records,
        } if fit_counts else {}
        return ParsedDeviceExport(
            aggregates=list(state.aggregates.values()),
            raw_record_count=state.recognized_records,
            export_started_at=state.earliest,
            export_ended_at=state.latest,
            metadata={
                "daily_aggregate_rows": len(state.aggregates),
                "json_files_scanned": len(json_files),
                "json_records_scanned": state.scanned_records,
                "recognized_health_records": state.recognized_records,
                "blood_pressure_records": state.blood_pressure_records,
                "biometric_profile_records": state.biometric_profile_records,
                "height_records": state.height_records,
                "weight_records": state.weight_records,
                "scale_records": state.scale_records,
                "missing_measurements": state.missing_measurements,
                "excluded_implausible_values": state.excluded,
                "fit_archive_counts": fit_counts,
                "fit_json_reconciliation": reconciliation,
                "source_vendor_counts": {self.vendor_name: state.recognized_records},
            },
        )
