from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: The person's "not my reading" rules while an aggregation runs, set by
#: ``devices.exclusions.applying``.  Every importer and every OpenWearables
#: mapper adds samples through ``Aggregate.add``, so this is the one predicate.
EXCLUDING: ContextVar = ContextVar("device_exclusions", default=None)


def _instant(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    name: str
    category: str
    unit: str
    aggregation: str


@dataclass
class Aggregate:
    definition: MetricDefinition
    day: str
    source_name: str
    source_vendor: str
    value_min: float | None = None
    value_max: float | None = None
    value_sum: float = 0.0
    value_latest: float | None = None
    latest_at: str = ""
    sample_count: int = 0

    def add(self, value: float, observed_at: str) -> None:
        rules = EXCLUDING.get()
        if rules is not None and rules.excludes(self.source_name, self.definition.key, observed_at):
            return
        self.value_min = value if self.value_min is None else min(self.value_min, value)
        self.value_max = value if self.value_max is None else max(self.value_max, value)
        self.value_sum += value
        self.sample_count += 1
        newer = observed_at >= self.latest_at
        if self.definition.aggregation == "latest" and self.latest_at:
            try:
                newer = _instant(observed_at) >= _instant(self.latest_at)
            except ValueError:
                pass  # Legacy exports may only carry a non-ISO date label.
        if newer:
            self.latest_at = observed_at
            self.value_latest = value

    @property
    def value(self) -> float:
        if self.definition.aggregation == "sum":
            return self.value_sum
        if self.definition.aggregation == "latest":
            return float(self.value_latest or 0.0)
        return self.value_sum / self.sample_count if self.sample_count else 0.0


@dataclass(frozen=True)
class Workout:
    source_name: str
    source_vendor: str
    workout_type: str
    started_at: str
    ended_at: str | None
    duration_minutes: float | None
    energy_kcal: float | None = None
    distance_km: float | None = None
    route_file: str | None = None


@dataclass(frozen=True)
class DeviceEvent:
    source_name: str
    source_vendor: str
    event_type: str
    started_at: str
    ended_at: str | None = None
    value_text: str | None = None
    value_numeric: float | None = None
    unit: str | None = None
    source_file: str | None = None


@dataclass
class ParsedDeviceExport:
    aggregates: list[Aggregate]
    workouts: list[Workout] = field(default_factory=list)
    events: list[DeviceEvent] = field(default_factory=list)
    raw_record_count: int = 0
    export_started_at: str | None = None
    export_ended_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
