"""Select a coherent view of overlapping device evidence without changing it.

Daily totals from two devices are alternative measurements, not additive parts
of a day. Sleep duration and stages also form one source-specific measurement:
filling an Oura stage gap with Watch stages creates a night neither recorded.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from functools import lru_cache, partial
from collections.abc import Mapping

from .catalog import canonical_source_vendor, source_priority
from .units import is_plausible

SLEEP_FAMILY = frozenset({"sleep_duration", "time_in_bed", "sleep_core", "sleep_deep", "sleep_rem", "sleep_awake"})

#: A device model identifier ("iPhone14,2", "Watch7,5") the bridge appends to
#: the origin's name; it names the hardware, not who recorded the reading.
_MODEL = re.compile(r"^(?:iPhone|iPad|iPod|Watch|AppleTV|Mac)\d+,\d+$")
#: Provider tokens the bridge prefixes, mapped to the vendor whose rules apply
#: when the origin name alone says nothing ("Olena", "Годинник").
_PROVIDERS = {"apple": "Apple Health", "oura": "Oura", "garmin": "Garmin", "zepp": "Zepp Life"}

#: A competing daily total smaller than this share of the largest one that day
#: is a partly worn device (a watch on the charger at noon, a ring left by the
#: sink), not a different opinion about the same day.
LOW_COVERAGE_SHARE = 1 / 3


def preference_group(metric_key: str) -> str:
    return "sleep" if metric_key in SLEEP_FAMILY else metric_key


@lru_cache(maxsize=4096)
def _identity_key(vendor: str, name: str) -> str:
    return hashlib.sha256(f"{vendor}\0{name}".encode()).hexdigest()[:24]


def source_key(row: Mapping) -> str:
    # One page asks this for every stored row and has a handful of sources.
    return _identity_key(str(row["source_vendor"]), str(row["source_name"]))


def source_kind(row: Mapping) -> str:
    return "bridge" if str(row["source_vendor"]).casefold() == "openwearables" else "direct"


def bridge_origin(name: str) -> tuple[str, str]:
    """(origin source name, physical vendor) of an OpenWearables row.

    "OpenWearables · apple · Kitchen phone · iPhone14,2" was recorded by the source
    the direct Apple export calls "Kitchen phone": the transport, the provider token
    and the hardware model are stripped so the two copies are recognised as
    one origin.  An empty origin ("OpenWearables · internal") is unknown.
    """
    parts = [part.strip() for part in str(name).split("·")]
    parts = [part for part in parts if part and part.casefold() != "openwearables"]
    provider = ""
    if parts and parts[0].casefold() in _PROVIDERS:
        provider = _PROVIDERS[parts.pop(0).casefold()]
    elif parts and parts[0].casefold() == "internal":
        parts.pop(0)
    if len(parts) > 1 and _MODEL.match(parts[-1]):
        parts.pop()
    origin = " · ".join(parts)
    if not origin:
        return "", ""
    physical = canonical_source_vendor(origin)
    if physical == origin:
        physical = provider or origin
    return origin, physical


#: The product a bare hardware model identifier names ("Watch7,5").
_PRODUCTS = (("Watch", "Apple Watch"), ("iPhone", "iPhone"), ("iPad", "iPad"))


def _plain(name: str) -> str:
    """A machine spelling made readable: `apple_watch` -> `Apple Watch`,
    `Watch7,5` -> `Apple Watch`; anything else is the source's own name."""
    if _MODEL.match(name):
        return next((product for prefix, product in _PRODUCTS if name.startswith(prefix)), name)
    if name.islower() and ("_" in name or " " not in name) and name.isascii():
        return name.replace("_", " ").title()
    return name


def human_source_label(vendor: str, name: str) -> str:
    """One readable name per source, never a vendor repeated twice.

    "OpenWearables · apple · Kitchen phone · iPhone14,2" -> "Kitchen phone · OpenWearables",
    "Oura · Oura" -> "Oura", "Apple Health · Watch7,5" -> "Apple Health ·
    Apple Watch".  The stored names stay untouched; this is how they read.
    """
    vendor, name = str(vendor or "").strip(), str(name or "").strip()
    if vendor.casefold() == "openwearables":
        origin, _physical = bridge_origin(name)
        return f"{_plain(origin)} · OpenWearables" if origin else "OpenWearables"
    readable = _plain(name)
    if not vendor or readable.casefold().startswith(vendor.casefold()) or vendor.casefold() in readable.casefold():
        return readable or vendor
    return f"{vendor} · {readable}"


def selection_priority(row: Mapping) -> int:
    vendor, name = str(row["source_vendor"]), str(row["source_name"])
    if source_kind(row) == "bridge":
        # A transport does not change which device made the measurement, so a
        # bridge copy ranks one step below the direct copy of the same origin
        # (x10 + 9, direct x10) and above every direct source that origin
        # outranks.  An unknown bridge keeps the low aggregator priority.
        origin, physical = bridge_origin(name)
        if origin and physical != "OpenWearables":
            return source_priority(str(row["metric_key"]), physical, origin) * 10 + 9
    return source_priority(str(row["metric_key"]), vendor, name) * 10


def priority_memo():
    """`selection_priority`, worked out once per source for one pass over many rows.

    Kept for one pass only: the ranking reads the installation's own device
    names, which an edit can change between two pages."""
    seen: dict[tuple[str, str, str], int] = {}

    def priority(row: Mapping) -> int:
        key = (str(row["metric_key"]), str(row["source_vendor"]), str(row["source_name"]))
        if key not in seen:
            seen[key] = selection_priority(row)
        return seen[key]

    return priority


def valid_row(row: Mapping) -> bool:
    """A finite value a human body could have produced.  An implausible body
    measurement (a 0.99 cm waist) stays stored as evidence but is never
    selected, so it is never displayed as the reading, judged, or copied into
    the profile."""
    try:
        if not math.isfinite(float(row["value"])):
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    return is_plausible(str(row.get("metric_key") or ""), row["value"])


def _low_coverage(row: Mapping, peak: float) -> bool:
    """A daily total that is zero or a small share of another source's total
    that day.  Only sums compare this way: two averages or two latest
    readings are alternative readings, not partial ones."""
    if str(row.get("aggregation") or "") != "sum" or peak <= 0:
        return False
    return float(row["value"]) < peak * LOW_COVERAGE_SHARE


def _rank(row: Mapping, preferred: str = "", peak: float = 0.0, priority=selection_priority) -> tuple:
    return (
        1 if _low_coverage(row, peak) else 0,
        0 if preferred and source_key(row) == preferred else 1,
        priority(row),
        -int(row.get("sample_count") or 0),
        str(row["source_vendor"]), str(row["source_name"]), str(row.get("id") or ""),
    )


def _night_hours(values: list[dict]) -> float:
    """The night's length as one source recorded it: time asleep when it has
    one, time in bed otherwise."""
    for metric in ("sleep_duration", "time_in_bed"):
        row = next((r for r in values if r["metric_key"] == metric), None)
        if row is not None:
            return float(row["value"])
    return 0.0


def _cohort_rank(item, *, longest: float, direct_names: set[str], preferred: str) -> tuple:
    key, values = item
    total = next((r for r in values if r["metric_key"] == "sleep_duration"), None)
    representative = total or min(values, key=lambda r: _rank(r, preferred))
    # A fragment (0.2 h in bed beside a 5.9 h night) never hides the
    # night another source recorded, whoever is preferred.
    fragment = longest > 0 and _night_hours(values) < longest * LOW_COVERAGE_SHARE
    # The bridge's copy of a night the direct export also holds is the
    # same night re-served; its "asleep" total (the in-bed span again)
    # is no reason to prefer it over the original (OPS-02).
    shadowed = source_kind(values[0]) == "bridge" and bridge_origin(str(values[0]["source_name"]))[0] in direct_names
    return (1 if fragment else 0, 0 if preferred and key == preferred else 1, 1 if shadowed else 0, 0 if total else 1,
            *_rank(representative), -len({r["metric_key"] for r in values}), key)


def sleep_cohorts(rows: list[dict], preferred: str = "") -> dict[str, str]:
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["metric_key"] in SLEEP_FAMILY and valid_row(row):
            grouped[str(row["day"])][source_key(row)].append(row)
    chosen = {}
    for day, sources in grouped.items():
        longest = max(_night_hours(values) for values in sources.values())
        direct_names = {str(values[0]["source_name"]) for values in sources.values() if source_kind(values[0]) == "direct"}

        rank = partial(_cohort_rank, longest=longest, direct_names=direct_names, preferred=preferred)
        chosen[day] = min(sources.items(), key=rank)[0]
    return chosen


def select_daily(rows: list[dict], preferred: str = "", cohorts: dict[str, str] | None = None) -> list[dict]:
    """One row per day, never a sum or a mean of sources.  A zero or partly
    worn source never hides another source's real day: it ranks below every
    candidate that covered the day, preference included, and still wins when
    it is the only reading of that day."""
    candidates: dict[str, list[dict]] = defaultdict(list)
    for original in rows:
        if not valid_row(original):
            continue
        row = dict(original)
        day = str(row["day"])
        if cohorts is not None and row["metric_key"] in SLEEP_FAMILY and source_key(row) != cohorts.get(day):
            continue
        candidates[day].append(row)
    chosen = []
    priority = priority_memo()
    for day_rows in candidates.values():
        peak = max(float(row["value"]) for row in day_rows)
        chosen.append(min(day_rows, key=partial(_rank, preferred=preferred, peak=peak, priority=priority)))
    return sorted(chosen, key=lambda row: str(row["day"]), reverse=True)


def select_metrics(grouped: dict[str, list[dict]], preferences: dict[str, str]) -> dict[str, list[dict]]:
    cohorts = sleep_cohorts([r for key in SLEEP_FAMILY for r in grouped.get(key, [])], preferences.get("sleep", ""))
    return {key: select_daily(rows, preferences.get(preference_group(key), ""), cohorts if key in SLEEP_FAMILY else None)
            for key, rows in grouped.items()}


def source_switches(rows: list[dict]) -> int:
    ordered = sorted(rows, key=lambda row: str(row["day"]))
    return sum(source_key(a) != source_key(b) for a, b in zip(ordered, ordered[1:]))
