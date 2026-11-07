"""Conservative, presentation-only matching of overlapping workout recordings.

Source clocks and activity labels are evidence, not identity. A duplicate needs
compatible activity labels and nearly the same complete interval. Unknown zones
are never guessed. A recording cannot bridge two sessions by transitive overlap.
All original rows survive in the selected record or its ``alternates`` list.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
import re

from .catalog import source_priority


_ALIASES = {
    "walk": "walking", "outdoorwalking": "walking", "indoorwalking": "walking",
    "run": "running", "outdoorrunning": "running", "indoorrunning": "running",
    "cycle": "cycling", "biking": "cycling", "bicycling": "cycling",
    "outdoorcycling": "cycling", "indoorcycling": "cycling",
    "traditionalstrengthtraining": "strength", "functionalstrengthtraining": "strength",
    "strengthtraining": "strength", "weighttraining": "strength", "weightlifting": "strength",
    "highintensityintervaltraining": "hiit", "intervaltraining": "hiit",
    "swim": "swimming", "poolswimming": "swimming", "openwaterswimming": "swimming",
}
_GENERIC = {"", "workout", "other", "unknown", "exercise", "activity"}


def _activity(value: object) -> str:
    text = str(value or "").casefold().removeprefix("hkworkoutactivitytype")
    key = re.sub(r"[\W_]+", "", text)
    return _ALIASES.get(key, key)


_STAIR_CLIMBING = "Stair Climbing"
_STRENGTH_TRAINING = "Strength Training"
_HIIT = "High Intensity Interval Training"
#: The one English label a workout type is shown under; each has a Ukrainian
#: entry in PHRASES.  Types are not merged beyond spelling: Apple's
#: "Traditional" and "Functional" strength training stay two labels because the
#: watch records them as two activities.
_LABEL_NAMES = (
    "Walking", "Running", "Cycling", "Swimming", "Hiking", "Yoga", "Pilates", "Elliptical",
    "Rowing", _STAIR_CLIMBING, "Dance", "Cooldown", "Core Training", "Cardio Training",
    _STRENGTH_TRAINING, "Traditional Strength Training", "Functional Strength Training",
    _HIIT, "Mind and Body", "Trail Running", "Treadmill Running",
    "Indoor Cycling", "Mountain Biking", "Lap Swimming", "Open Water Swimming", "Stretching",
    "Tennis", "Golf", "Soccer", "Basketball", "Boxing", "Skiing", "Snowboarding", "Jump Rope",
    "Kickboxing", "Badminton", "Table Tennis", "Volleyball", "Skating", "Climbing",
    "Mixed Cardio", "Flexibility", "Other", "Workout",
)
_LABELS = {name.replace(" ", "").casefold(): name for name in _LABEL_NAMES}
_LABELS.update({
    "hiit": _HIIT, "intervaltraining": _HIIT,
    "weighttraining": _STRENGTH_TRAINING, "weightlifting": _STRENGTH_TRAINING,
    "walk": "Walking", "run": "Running", "cycle": "Cycling", "biking": "Cycling",
    "bicycling": "Cycling", "swim": "Swimming", "poolswimming": "Lap Swimming",
    "outdoorwalking": "Walking", "indoorwalking": "Walking",
    "outdoorrunning": "Running", "indoorrunning": "Treadmill Running",
    "outdoorcycling": "Cycling", "stairclimber": _STAIR_CLIMBING, "stairs": _STAIR_CLIMBING,
    "mindbody": "Mind and Body",
    "generic": "Workout", "unknown": "Workout", "session": "Workout", "exercise": "Workout",
    "activity": "Workout",
})


def workout_label(value: object) -> str:
    """One Title-case English label for a workout type however a source spelled it.

    Apple sends ``Functional Strength Training``, OpenWearables and Garmin send
    ``strength_training``, Oura sends bare lowercase words.  Rendering them as
    stored put ``walking`` beside ``Walking``.  Display only: the stored value
    is untouched.  An unrecognised type is Title-cased rather than dropped.
    """
    text = str(value or "").strip().removeprefix("HKWorkoutActivityType")
    key = re.sub(r"[\W_]+", "", text.casefold())
    if key in _LABELS:
        return _LABELS[key]
    spaced = re.sub(r"[_\-]+", " ", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text))
    return " ".join(word.capitalize() for word in spaced.split()) or "Workout"


def _moment(value: object) -> datetime | None:
    # A date alone is not a recorded midnight workout.
    text = str(value or "")
    if len(text) < 16:
        return None
    try:
        moment = datetime.fromisoformat(text)
        return moment.astimezone(UTC) if moment.tzinfo else moment
    except (ValueError, OverflowError):
        return None


@dataclass
class _Session:
    row: dict
    start: datetime | None
    end: datetime | None
    kind: str

    @property
    def identity(self) -> tuple[str, str]:
        return str(self.row.get("source_vendor") or ""), str(self.row.get("source_name") or "")

    @property
    def clock(self) -> str:
        if self.start is None:
            return "unknown"
        return "utc" if self.start.tzinfo else "local_unspecified"

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds() if self.start and self.end else 0.0


def _session(row: Mapping) -> _Session:
    copied = dict(row)
    start, end = _moment(copied.get("started_at")), _moment(copied.get("ended_at"))
    if start and end and (bool(start.tzinfo) != bool(end.tzinfo) or end <= start):
        # An explicitly invalid interval is not repaired using a conflicting
        # duration. Its source row remains separately inspectable.
        end = None
    elif start and end is None and not copied.get("ended_at"):
        try:
            minutes = float(copied.get("duration_minutes"))
            if math.isfinite(minutes) and minutes > 0:
                end = start + timedelta(minutes=minutes)
        except (TypeError, ValueError, OverflowError):
            pass
    return _Session(copied, start, end, _activity(copied.get("workout_type")))


def _match(a: _Session, b: _Session) -> str | None:
    if a.clock != b.clock or a.start is None or b.start is None or not a.end or not b.end:
        return None
    for scope in ("owner_user_id", "patient_id"):
        if a.row.get(scope) != b.row.get(scope):
            return None
    if a.kind != b.kind and a.kind not in _GENERIC and b.kind not in _GENERIC:
        return None
    start_gap = abs((a.start - b.start).total_seconds())
    end_gap = abs((a.end - b.end).total_seconds())
    if a.identity == b.identity:
        # Re-imported exact copies can repeat within a source; independently
        # captured sessions from that same source do not prove duplication.
        return "same_source_exact_interval" if start_gap <= 1 and end_gap <= 1 and a.kind == b.kind else None
    longest = max(a.duration, b.duration)
    overlap = max(0.0, (min(a.end, b.end) - max(a.start, b.start)).total_seconds())
    # Both bounds must be close, so a short session contained in a longer one
    # cannot match just because 100% of the short session overlaps it.
    tolerance = min(180.0, max(30.0, longest * 0.10))
    if start_gap > tolerance or end_gap > tolerance or overlap / longest < 0.85:
        return None
    # Generic labels provide less identifying evidence. Require closer timing.
    if a.kind != b.kind and overlap / longest < 0.95:
        return None
    return "cross_source_matching_interval"


def _rank(session: _Session) -> tuple:
    row = session.row
    return (
        source_priority("workout", *session.identity),
        session.identity,
        -sum(row.get(field) is not None for field in ("ended_at", "duration_minutes", "distance_km", "energy_kcal", "route_file")),
        str(row.get("id") or ""),
        repr(sorted((str(key), repr(value)) for key, value in row.items())),
    )


def reconcile_workouts(rows: Iterable[Mapping]) -> list[dict[str, object]]:
    """Return selected sessions, newest first, without mutating any source row.

    Drop-in replacement for ``queries._preferred_workouts``. ``alternates``
    retains every other recording, including repeated imports from one source;
    ``source_count`` counts unique vendor/name pairs and ``record_count`` counts
    every preserved record. ``reconciliation`` carries inspectable reason codes.
    Matching tolerances are data identity heuristics, not clinical thresholds.
    """
    sessions = [_session(row) for row in rows]
    sessions.sort(key=lambda item: (item.clock, item.start.isoformat() if item.start else "", _rank(item)))
    groups: list[list[_Session]] = []
    active: list[list[_Session]] = []
    for item in sessions:
        # No candidate can match a start more than three minutes away. This
        # bounds work to nearby sessions instead of comparing an entire export.
        active = [group for group in active if item.start and group[0].start and item.clock == group[0].clock
                  and (item.start - group[0].start).total_seconds() <= 180]
        candidates = [group for group in active if all(_match(item, member) for member in group)]
        if candidates:
            chosen = min(candidates, key=lambda group, item=item: (
                abs((item.start - group[0].start).total_seconds()), min(_rank(member) for member in group),
            ))
            chosen.append(item)
        else:
            group = [item]
            groups.append(group)
            active.append(group)
    result = []
    for group in groups:
        group.sort(key=_rank)
        selected = group[0]
        chosen = dict(selected.row)
        chosen.update({
            "workout_type": workout_label(selected.row.get("workout_type")),
            "alternates": [dict(item.row) for item in group[1:]],
            "source_count": len({item.identity for item in group}),
            "record_count": len(group),
            "session_minute": selected.start.strftime("%Y-%m-%dT%H:%M") if selected.start else str(chosen.get("started_at") or "")[:16],
            "reconciliation": {
                "method": "compatible_complete_interval",
                "time_basis": selected.clock,
                "reason_codes": sorted({_match(selected, item) for item in group[1:]}),
            },
        })
        result.append(chosen)
    return sorted(result, key=lambda row: (str(row["session_minute"]), str(row.get("id") or "")), reverse=True)
