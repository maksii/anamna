from __future__ import annotations

import datetime
import json
import math
import sqlite3
from collections import Counter

from ..i18n import t, translate_phrase
from ..health import display_unit, metric_area_ids
from ..panels import PANEL_BY_ID
from .catalog import CORE_METRIC_KEYS, CUMULATIVE_KEYS, DEVICE_CATEGORY_LABELS
from .timezone import today as local_today, user_timezone
from .workout_reconcile import reconcile_workouts
from .reconcile import (
    SLEEP_FAMILY, bridge_origin, human_source_label, preference_group, priority_memo, select_daily,
    select_metrics, selection_priority, sleep_cohorts, source_key, source_kind, source_switches,
)


DEVICE_AREA_BY_CATEGORY = {
    "device_body": "body",
    "device_activity": "activity",
    "device_fitness": "activity",
    "device_mobility": "mobility",
    "device_sleep": "sleep",
    "device_recovery": "sleep",
    "device_environment": "environment",
}

DEVICE_PRIMARY_AREA_BY_METRIC = {
    "systolic_blood_pressure": "heart",
    "diastolic_blood_pressure": "heart",
    "blood_pressure_pulse": "heart",
    "ecg_heart_rate": "heart",
    # Vascular properties the ring derives overnight; their sensor category
    # would file them under sleep, but they are about the vessels, not the night.
    "pulse_wave_velocity": "heart",
    "cardiovascular_age": "heart",
}


def _preferred_days(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return select_daily(rows)


def source_preferences(connection, owner_user_id: str) -> dict[str, str]:
    # Read-only corpus tooling can inspect a pre-migration backup too.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_source_preferences'").fetchone():
        return {}
    return dict(connection.execute(
        "SELECT preference_group, source_key FROM device_source_preferences WHERE owner_user_id=?", (owner_user_id,)
    ))


def _selected_metric(connection, owner_user_id: str, metric_key: str, raw: list[dict]) -> list[dict]:
    preferences = source_preferences(connection, owner_user_id)
    cohorts = None
    if metric_key in SLEEP_FAMILY:
        rows = [dict(row) for row in connection.execute(
            f"SELECT * FROM device_metric_days WHERE owner_user_id=? AND metric_key IN ({','.join('?' for _ in SLEEP_FAMILY)})",
            (owner_user_id, *sorted(SLEEP_FAMILY)),
        )]
        cohorts = sleep_cohorts(rows, preferences.get("sleep", ""))
    return select_daily(raw, preferences.get(preference_group(metric_key), ""), cohorts)


def _policy(metric_key: str, preferences: dict[str, str], selected: list[dict], overlap: int = 0) -> dict:
    group = preference_group(metric_key)
    preference = preferences.get(group, "")
    return {
        "group": group, "mode": "preferred" if preference else "automatic",
        "preferred_source_key": preference,
        "description": t("source_policy.sleep" if group == "sleep" else "source_policy.daily"),
        "source_switches": source_switches(selected), "overlapping_days": overlap,
    }


def _utc_minute(started_at: str) -> str:
    """The minute a workout began, in UTC — the one thing two records of it
    agree on.  A naive timestamp is read as UTC rather than dropped: it is the
    only reading available, and the alternative is listing the session twice.
    """
    try:
        moment = datetime.datetime.fromisoformat(started_at)
    except ValueError:
        return started_at[:16]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M")


def _preferred_workouts(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    return reconcile_workouts(rows)


def device_metric_source_values(
    connection: sqlite3.Connection, owner_user_id: str, metric_key: str
) -> list[dict[str, object]]:
    """Every stored source row for a metric, with no display deduplication."""
    return [
        dict(row)
        for row in connection.execute(
            """SELECT * FROM device_metric_days
               WHERE owner_user_id=? AND metric_key=?
               ORDER BY day DESC, sample_count DESC, source_vendor, source_name""",
            (owner_user_id, metric_key),
        )
    ]


def _disambiguated_labels(identities: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    labels = {identity: human_source_label(*identity) for identity in identities}
    # Four watches bridged under one name are four sources: where readable
    # labels collide, the hardware model tells them apart again.
    counts = Counter(labels.values())
    for identity, label in labels.items():
        model = identity[1].rsplit("·", 1)[-1].strip()
        if counts[label] > 1 and model and model not in label:
            labels[identity] = f"{label} ({model})"
    return labels


def _comparison_day(
    metric_key: str, day: str, rows: list[dict[str, object]],
    labels: dict[tuple[str, str], str], tz, *, priority=selection_priority,
) -> dict[str, object]:
    rows.sort(key=lambda item: (
        0 if item["selected"] else 1,
        priority(item),
        str(item["source_name"]),
    ))
    for item in rows:
        item["source_label"] = labels[(str(item["source_vendor"]), str(item["source_name"]))]
    numeric = [float(item["value"]) for item in rows]
    return {
        "day": day,
        "partial": is_partial_day(metric_key, day, tz),
        "rows": rows,
        "source_count": len(rows),
        "minimum": min(numeric),
        "maximum": max(numeric),
        "spread": max(numeric) - min(numeric),
    }


def _comparison_source(
    identity: tuple[str, str], rows: list[dict[str, object]], source_id: str, label: str
) -> dict[str, object]:
    return {
        "id": source_id,
        "source_key": source_key(rows[0]),
        "label": label,
        "vendor": identity[0],
        "name": identity[1],
        "kind": "bridge" if identity[0].casefold() == "openwearables" else "direct",
        "day_count": len({str(row["day"]) for row in rows}),
        "sample_count": sum(int(row["sample_count"] or 0) for row in rows),
        "selected_days": sum(1 for row in rows if row["selected"]),
        "first_day": str(rows[-1]["day"]),
        "last_day": str(rows[0]["day"]),
        "latest_value": float(rows[0]["value"]),
        "priority": selection_priority(rows[0]),
        "rows": rows,
    }


def device_metric_comparison(
    connection: sqlite3.Connection, owner_user_id: str, metric_key: str
) -> dict[str, object] | None:
    """Selected daily history plus every competing provider row.

    The selected series is useful for trends and correlations, where two
    values for one date would double-weight that date.  It is never allowed to
    erase provenance from the detail view: `days` and `sources` carry every
    stored row and explicitly mark the row used by the combined series.
    """
    raw = device_metric_source_values(connection, owner_user_id, metric_key)
    if not raw:
        return None
    preferred = _selected_metric(connection, owner_user_id, metric_key, raw)
    selected = {(str(row["day"]), source_key(row)) for row in preferred}
    identities = sorted({(str(row["source_vendor"]), str(row["source_name"])) for row in raw})
    source_ids = {identity: f"source-{index + 1}" for index, identity in enumerate(identities)}

    source_rows: dict[tuple[str, str], list[dict[str, object]]] = {identity: [] for identity in identities}
    by_day: dict[str, list[dict[str, object]]] = {}
    for row in raw:
        identity = (str(row["source_vendor"]), str(row["source_name"]))
        item = dict(row)
        item["source_id"] = source_ids[identity]
        item["selected"] = (str(item["day"]), source_key(item)) in selected
        item["source_kind"] = source_kind(item)
        item["source_key"] = source_key(item)
        source_rows[identity].append(item)
        by_day.setdefault(str(item["day"]), []).append(item)

    labels = _disambiguated_labels(identities)
    tz = user_timezone(connection, owner_user_id)
    priority = priority_memo()
    days = [
        _comparison_day(metric_key, day, rows, labels, tz, priority=priority)
        for day, rows in sorted(by_day.items(), reverse=True)
    ]
    sources = [
        _comparison_source(identity, source_rows[identity], source_ids[identity], labels[identity])
        for identity in identities
    ]
    sources.sort(key=lambda item: (int(item["priority"]), -int(item["day_count"]), str(item["name"])))
    overlap = [day for day in days if int(day["source_count"]) > 1]
    return {
        "preferred": preferred,
        "days": days,
        "sources": sources,
        "source_count": len(sources),
        "stored_row_count": len(raw),
        "overlap_days": len(overlap),
        "latest_overlap_day": overlap[0]["day"] if overlap else None,
        "policy": _policy(metric_key, source_preferences(connection, owner_user_id), preferred, len(overlap)),
        "has_selected_values": bool(preferred),
    }


def device_metric_values(
    connection: sqlite3.Connection, owner_user_id: str, metric_key: str
) -> list[dict[str, object]]:
    rows = device_metric_source_values(connection, owner_user_id, metric_key)
    return _selected_metric(connection, owner_user_id, metric_key, rows)


#: How far back the device cards read rows: enough for the 90-point card
#: sparkline and the trend, a small fraction of a ten-year history (PERF-02).
CARD_WINDOW_DAYS = 120


def is_partial_day(metric_key: str, day: object, tz=None) -> bool:
    """True for a running daily total of the day still in progress, in the
    person's zone: 3,000 steps at noon is a day not finished, not a low day."""
    return metric_key in CUMULATIVE_KEYS and str(day or "")[:10] >= local_today(tz)


def _complete(metric_key: str, rows: list[dict], tz) -> list[dict]:
    """Rows without today's partial total, unless that is all there is."""
    complete = [row for row in rows if not is_partial_day(metric_key, row["day"], tz)]
    return complete or rows


def _metric_summaries(connection, owner_user_id: str) -> dict[str, dict[str, object]]:
    """Whole-history facts per metric in two aggregate passes, never as rows."""
    summary = {
        str(row["metric_key"]): dict(row)
        for row in connection.execute(
            """SELECT metric_key, MAX(day) last_day, COUNT(DISTINCT day) day_count,
                      MAX(ABS(value)) peak, SUM(sample_count) samples,
                      GROUP_CONCAT(DISTINCT source_vendor) vendors,
                      COUNT(DISTINCT source_vendor || char(0) || source_name) source_count
               FROM device_metric_days WHERE owner_user_id=? GROUP BY metric_key""",
            (owner_user_id,),
        )
    }
    for row in connection.execute(
        """SELECT metric_key, COUNT(*) overlap FROM (
               SELECT metric_key, day FROM device_metric_days WHERE owner_user_id=?
               GROUP BY metric_key, day HAVING COUNT(*) > 1)
           GROUP BY metric_key""",
        (owner_user_id,),
    ):
        if str(row["metric_key"]) in summary:
            summary[str(row["metric_key"])]["overlap_days"] = int(row["overlap"])
    return summary


_DEVICE_DATA_LABEL = "Device data"
_AREA_NAMES = {
    "body": "Body composition",
    "activity": "Activity & fitness",
    "mobility": "Mobility & gait",
    "sleep": "Sleep & recovery",
    "environment": "Hearing & environment",
}
#: Two consecutive daily values closer than this are the same number written
#: twice; it only absorbs float noise from the averaging, far below any
#: reporting precision of a wearable (the finest metric is 0.01).
_FLAT_DELTA_TOLERANCE = 1e-9


def _card_trend(values: list[dict[str, object]]) -> dict[str, object] | None:
    if len(values) < 2:
        return None
    delta = float(values[0]["value"]) - float(values[1]["value"])
    if math.isclose(delta, 0, abs_tol=_FLAT_DELTA_TOLERANCE):
        direction = "flat"
    elif delta > 0:
        direction = "up"
    else:
        direction = "down"
    return {"direction": direction, "delta": delta}


def _card_area_ids(metric_key: str, latest: dict[str, object], area_id: str) -> list[str]:
    # A device metric can be evidence for a body system other than the one
    # its vendor category names: blood oxygen and respiratory rate belong on
    # the lungs page, which otherwise shows no measurements at all.
    area_ids = [area_id]
    for related in metric_area_ids(str(latest["metric_name"]), str(latest["category"]), metric_key=metric_key):
        if related not in area_ids:
            area_ids.append(related)
    return area_ids


def _metric_card(
    metric_key: str,
    facts: dict[str, object],
    values: list[dict[str, object]],
    vendors: list[str],
    preferences,
    tz,
) -> dict[str, object]:
    latest = values[0]
    category = str(latest["category"])
    area_id = DEVICE_PRIMARY_AREA_BY_METRIC.get(metric_key, DEVICE_AREA_BY_CATEGORY.get(category, "activity"))
    label = human_source_label(str(latest["source_vendor"]), str(latest["source_name"]))
    return {
        "id": f"device:{metric_key}",
        "url": f"/devices/metrics/{metric_key}",
        "name": translate_phrase(str(latest["metric_name"])),
        "category": category,
        "category_label": translate_phrase(DEVICE_CATEGORY_LABELS.get(category, _DEVICE_DATA_LABEL)),
        "area_id": area_id,
        "primary_area_id": area_id,
        "area_ids": _card_area_ids(metric_key, latest, area_id),
        "area_name": translate_phrase(_AREA_NAMES.get(area_id, _DEVICE_DATA_LABEL)),
        "count": int(facts["day_count"]),
        "latest_date": latest["day"],
        "latest_numeric": latest["value"],
        "latest_text": None,
        "partial_day": is_partial_day(metric_key, latest["day"], tz),
        "unit": display_unit(str(latest["unit"]) if latest["unit"] else None),
        "vendor": label,
        "source_name": label,
        "source_policy": _policy(metric_key, preferences, values)["description"],
        "series": [{"date": str(item["day"]), "value": float(item["value"]), "source": str(item["source_name"])} for item in reversed(values[:90])],
        "status": "information",
        "status_label": t("device.measurement"),
        "trend": _card_trend(values),
        "aliases": vendors,
        "source_count": int(facts["source_count"]),
        "overlap_days": int(facts.get("overlap_days") or 0),
        "evidence_count": int(facts["samples"] or 0),
        "is_device": True,
    }


def device_metric_catalog(
    connection: sqlite3.Connection,
    owner_user_id: str,
    query: str = "",
    limit: int | None = None,
) -> list[dict[str, object]]:
    tz = user_timezone(connection, owner_user_id)
    summary = _metric_summaries(connection, owner_user_id)
    grouped: dict[str, list[dict[str, object]]] = {}
    for metric_key, facts in summary.items():
        # A metric the source never filled (every night "0 naps") is a
        # capability gap, not a measurement: no card (OPS-09).
        if not facts["peak"]:
            continue
        since = (datetime.date.fromisoformat(str(facts["last_day"])[:10])
                 - datetime.timedelta(days=CARD_WINDOW_DAYS)).isoformat()
        grouped[metric_key] = [dict(row) for row in connection.execute(
            "SELECT * FROM device_metric_days WHERE owner_user_id=? AND metric_key=? AND day>=? ORDER BY day DESC",
            (owner_user_id, metric_key, since),
        )]
    needle = query.casefold().strip()
    preferences = source_preferences(connection, owner_user_id)
    selected_metrics = select_metrics(grouped, preferences)
    cards: list[dict[str, object]] = []
    for metric_key in grouped:
        facts = summary[metric_key]
        selected = selected_metrics[metric_key]
        if not selected:
            continue
        values = _complete(metric_key, selected, tz)
        latest = values[0]
        vendors = sorted({vendor for vendor in str(facts["vendors"] or "").split(",") if vendor})
        searchable = " ".join(
            [
                str(latest["metric_name"]), str(latest["category"]),
                DEVICE_CATEGORY_LABELS.get(str(latest["category"]), ""),
                "device wearable tracker Apple Health Oura Garmin Kardia AliveCor ECG blood pressure",
                *vendors,
            ]
        ).casefold()
        if needle and needle not in searchable:
            continue
        cards.append(_metric_card(metric_key, facts, values, vendors, preferences, tz))
    cards.sort(key=lambda item: (str(item["latest_date"]), int(item["count"])), reverse=True)
    return cards[:limit] if limit is not None else cards


def _bucket_stats(rows: list[dict[str, object]]) -> dict[str, object]:
    """Mean, range and coverage of a set of already-deduplicated daily rows.

    The range is taken across the *daily* values, never from `value_min` /
    `value_max`: on a `sum` metric those describe the smallest and largest
    individual sample, so a month of walking would report its step range as
    "4-162" instead of "1,091-18,400".
    """
    values = [float(row["value"]) for row in rows]
    return {
        "days": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "samples": sum(int(row["sample_count"] or 0) for row in rows),
        "first_day": str(rows[-1]["day"]),
        "last_day": str(rows[0]["day"]),
    }


def device_history_summary(
    connection: sqlite3.Connection, owner_user_id: str, *, months: int = 12
) -> list[dict[str, object]]:
    """Every device metric compressed to a history a reader can hold in mind.

    Fifty-eight thousand daily rows over ten years cannot travel in a prompt,
    an export, or anything a person reads.  Each metric collapses to its latest
    reading, the most recent `months` calendar months as monthly means, and one
    row per earlier calendar year.  The raw day and sample counts travel with
    it, so the compression is visible rather than silent.

    Months are counted back from the newest day in the record, not from today:
    an export taken after a gap in syncing should still describe the last year
    that was actually measured.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in connection.execute(
        "SELECT * FROM device_metric_days WHERE owner_user_id=? ORDER BY day DESC",
        (owner_user_id,),
    ):
        grouped.setdefault(str(row["metric_key"]), []).append(dict(row))
    if not grouped:
        return []

    newest = max(str(rows[0]["day"]) for rows in grouped.values())
    year, month = int(newest[:4]), int(newest[5:7])
    recent_months = set()
    for step in range(months):
        offset = month - 1 - step
        recent_months.add(f"{year + offset // 12:04d}-{offset % 12 + 1:02d}")

    summaries: list[dict[str, object]] = []
    selected_metrics = select_metrics(grouped, source_preferences(connection, owner_user_id))
    for metric_key, raw_rows in grouped.items():
        days = selected_metrics[metric_key]
        if not days:
            continue
        monthly: dict[str, list[dict[str, object]]] = {}
        yearly: dict[str, list[dict[str, object]]] = {}
        for row in days:
            day = str(row["day"])
            if day[:7] in recent_months:
                monthly.setdefault(day[:7], []).append(row)
            else:
                yearly.setdefault(day[:4], []).append(row)
        latest = days[0]
        summaries.append(
            {
                "metric_key": metric_key,
                "name": translate_phrase(str(latest["metric_name"])),
                "category": str(latest["category"]),
                "category_label": translate_phrase(
                    DEVICE_CATEGORY_LABELS.get(str(latest["category"]), _DEVICE_DATA_LABEL)
                ),
                "unit": display_unit(str(latest["unit"]) if latest["unit"] else None),
                "aggregation": str(latest["aggregation"]),
                "vendors": sorted({str(item["source_vendor"]) for item in raw_rows}),
                "latest_day": str(latest["day"]),
                "latest_value": float(latest["value"]),
                "day_count": len(days),
                "row_count": len(raw_rows),
                "first_day": str(days[-1]["day"]),
                # Newest first: a reader and a model both start at the present.
                "recent_days": [
                    {"day": str(row["day"]), "value": float(row["value"])} for row in days[:14]
                ],
                "months": [
                    {"period": key, **_bucket_stats(rows)}
                    for key, rows in sorted(monthly.items(), reverse=True)
                ],
                "years": [
                    {"period": key, **_bucket_stats(rows)}
                    for key, rows in sorted(yearly.items(), reverse=True)
                ],
            }
        )
    summaries.sort(key=lambda item: (str(item["latest_day"]), int(item["day_count"])), reverse=True)
    return summaries


# The areas whose measurements come from a wearable rather than a laboratory,
# and therefore read as a tracker dashboard: days, weekly and monthly averages,
# and a month-on-month comparison, the way Apple Health or Oura present them.
TRACKER_AREA_IDS = frozenset({"activity", "mobility", "sleep"})

# Stacked bottom-to-top in depth order: the three asleep stages are one ordered
# scale (deep is the most asleep), awake is the qualitative outlier on top.
SLEEP_STAGE_KEYS = ("sleep_deep", "sleep_core", "sleep_rem", "sleep_awake")

# Covered by the stacked stage chart; a bar card each would say it twice.
_SLEEP_STACK_KEYS = frozenset({*SLEEP_STAGE_KEYS, "sleep_duration", "time_in_bed"})

_BAR_DAYS = 14


def _day_range(last_day: str, days: int) -> list[str]:
    """`days` consecutive ISO dates ending on `last_day`, oldest first."""
    end = datetime.date.fromisoformat(last_day)
    return [(end - datetime.timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def _window_mean(by_day: dict[str, float], days: list[str]) -> float | None:
    """Mean over the days the device actually recorded.

    An unworn day is unknown, not zero: averaging it in as 0 would report a
    quiet week for someone whose watch spent it in a drawer.
    """
    values = [by_day[day] for day in days if day in by_day]
    return sum(values) / len(values) if values else None


def _delta_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or math.isclose(previous, 0.0, abs_tol=1e-12):
        return None
    return (current - previous) / abs(previous) * 100.0


#: Where a category nobody mapped ends up — the same default
#: `DEVICE_AREA_BY_CATEGORY.get(category, ...)` applies in Python.
_DEFAULT_DEVICE_AREA = "activity"


def _area_row_predicate(area_id: str) -> tuple[str, list[str]]:
    """SQL for "this row belongs to `area_id`", derived from the two maps.

    The same rule as the Python classification, moved into the query so a page
    reads its own area rather than the whole device history: a metric named in
    `DEVICE_PRIMARY_AREA_BY_METRIC` goes where that map says, anything else
    follows its category, and a category the map does not know falls to
    activity — which is why the default area's arm also admits categories that
    are not in the map at all. Both columns are `NOT NULL`, so no row escapes
    through a NULL comparison.

    It is generated from the dicts rather than written out, so a metric moved
    between areas cannot leave a stale copy of the rule behind here.
    """
    marks = lambda values: ",".join("?" * len(values))  # noqa: E731 - one expression
    keys = sorted(key for key, area in DEVICE_PRIMARY_AREA_BY_METRIC.items() if area == area_id)
    elsewhere = sorted(set(DEVICE_PRIMARY_AREA_BY_METRIC) - set(keys))
    categories = sorted(name for name, area in DEVICE_AREA_BY_CATEGORY.items() if area == area_id)
    params: list[str] = []
    if not categories:
        by_category = "0"
    elif area_id == _DEFAULT_DEVICE_AREA:
        known = sorted(DEVICE_AREA_BY_CATEGORY)
        by_category = f"(category IN ({marks(categories)}) OR category NOT IN ({marks(known)}))"
        params += [*categories, *known]
    else:
        by_category = f"category IN ({marks(categories)})"
        params += categories
    if elsewhere:
        by_category = f"(metric_key NOT IN ({marks(elsewhere)}) AND {by_category})"
        params = [*elsewhere, *params]
    if keys:
        return f"(metric_key IN ({marks(keys)}) OR {by_category})", [*keys, *params]
    return by_category, params


def _tracker_summary(
    connection: sqlite3.Connection, owner_user_id: str, area_clause: str, area_params: list[str]
) -> dict[str, tuple[int, str]]:
    """Per metric of the area: (days ever recorded, last recorded day)."""
    return {
        str(row["metric_key"]): (int(row["day_count"]), str(row["last_day"]))
        for row in connection.execute(
            f"""SELECT metric_key, COUNT(DISTINCT day) day_count, MAX(day) last_day
                FROM device_metric_days WHERE owner_user_id=? AND {area_clause}
                GROUP BY metric_key""",
            (owner_user_id, *area_params),
        )
    }


def _tracker_grouped(
    connection: sqlite3.Connection,
    owner_user_id: str,
    summary: dict[str, tuple[int, str]],
    window_start: str,
    area_clause: str,
    area_params: list[str],
    tz,
) -> dict[str, list[dict[str, object]]]:
    """Daily rows per metric inside the comparison window, plus the last reading of any
    metric that stopped before it."""
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in connection.execute(
        f"""SELECT * FROM device_metric_days
            WHERE owner_user_id=? AND day >= ? AND {area_clause} ORDER BY day DESC""",
        (owner_user_id, window_start, *area_params),
    ):
        # Today's running totals are a day not finished: a quarter-day of
        # steps drawn as the newest bar reads as a collapse (UX-11).
        if is_partial_day(str(row["metric_key"]), row["day"], tz):
            continue
        grouped.setdefault(str(row["metric_key"]), []).append(dict(row))
    # A metric that stopped before the window still shows a card, and that card
    # prints its last reading — one small keyed read each, and only for those.
    # Newest first, so metrics keep the order the single scan used to give them.
    for metric_key, (_, last_day) in sorted(summary.items(), key=lambda item: item[1][1], reverse=True):
        if metric_key in grouped:
            continue
        last_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM device_metric_days WHERE owner_user_id=? AND metric_key=? AND day=?",
                (owner_user_id, metric_key, last_day),
            )
            if not is_partial_day(metric_key, row["day"], tz)
        ]
        if last_rows:
            grouped[metric_key] = last_rows
    return grouped


def _tracker_card(
    metric_key: str,
    days: list[dict[str, object]],
    source_rows: list[dict[str, object]],
    day_count: int,
    windows: dict[str, list[str]],
) -> dict[str, object]:
    bar_days = windows["bars"]
    by_day = {str(row["day"]): float(row["value"]) for row in days}
    window = [by_day.get(day) for day in bar_days]
    peak = max((value for value in window if value is not None), default=0.0)
    latest = days[0]
    average_30 = _window_mean(by_day, windows["last_30"])
    previous = _window_mean(by_day, windows["previous_30"])
    source_day_counts = Counter(str(row["day"]) for row in source_rows)
    return {
        "metric_key": metric_key,
        "name": translate_phrase(str(latest["metric_name"])),
        "unit": display_unit(str(latest["unit"]) if latest["unit"] else None),
        "url": f"/devices/metrics/{metric_key}",
        "aggregation": str(latest["aggregation"]),
        "latest_day": str(latest["day"]),
        "latest_value": float(latest["value"]),
        "bars": [
            {
                "day": day,
                "value": value,
                "frac": round(value / peak, 4) if value is not None and peak > 0 else 0.0,
            }
            for day, value in zip(bar_days, window)
        ],
        "avg7": _window_mean(by_day, windows["last_7"]),
        "avg30": average_30,
        "prev30": previous,
        "delta_pct": _delta_percent(average_30, previous),
        # Every day ever recorded, not only those inside the window:
        # this orders the cards the panel does not name, and it must
        # not change with how far back the page happens to read.
        "day_count": day_count,
        # The window is anchored on the whole area's newest day, so a
        # metric that stopped recording (phone swapped, sensor died)
        # would otherwise render fourteen empty stubs and two dashes
        # with nothing saying why. `latest_day` is its own last
        # reading, which is what the page explains instead.
        "dormant": all(value is None for value in window),
        "source_count": len({
            (str(row["source_vendor"]), str(row["source_name"])) for row in source_rows
        }),
        "selected_vendor": str(latest["source_vendor"]),
        "selected_source": str(latest["source_name"]),
        "selected_label": human_source_label(str(latest["source_vendor"]), str(latest["source_name"])),
        "overlap_days": sum(1 for count in source_day_counts.values() if count > 1),
    }


def _stage_fraction(by_day: dict[str, float], day: str, peak: float) -> float:
    return round(by_day[day] / peak, 4) if peak > 0 and day in by_day else 0.0


def _sleep_night(
    day: str,
    peak: float,
    stage_by_day: dict[str, dict[str, float]],
    asleep_by_day: dict[str, float],
    in_bed_by_day: dict[str, float],
    fallback: float | None,
    sleep_rows: list[dict[str, object]],
    cohorts: dict[str, str],
) -> dict[str, object]:
    staged = [
        {
            "key": key,
            "value": stage_by_day[key].get(day),
            "frac": _stage_fraction(stage_by_day[key], day, peak),
        }
        for key in SLEEP_STAGE_KEYS
    ]
    day_rows = [row for row in sleep_rows if str(row["day"]) == day]
    chosen = [row for row in day_rows if source_key(row) == cohorts.get(day)]
    return {
        "day": day,
        "stages": staged,
        "asleep": asleep_by_day.get(day),
        "in_bed": in_bed_by_day.get(day),
        "source": str(chosen[0]["source_name"]) if chosen else None,
        "vendor": str(chosen[0]["source_vendor"]) if chosen else None,
        "source_count": len({source_key(row) for row in day_rows}),
        "alternates": [
            {"source": str(row["source_name"]), "vendor": str(row["source_vendor"]), "asleep": float(row["value"])}
            for row in day_rows if row["metric_key"] == "sleep_duration" and source_key(row) != cohorts.get(day)
        ],
        "has_stages": any(segment["value"] is not None for segment in staged),
        # A night recorded without a stage breakdown (an older
        # tracker, another vendor) still happened: it draws as one
        # unstaged block rather than as an empty column.
        "asleep_frac": (
            round(fallback / peak, 4) if fallback is not None and peak > 0 else 0.0
        ),
    }


def _sleep_legend(
    nights: list[dict[str, object]],
    metrics: dict[str, list[dict[str, object]]],
    stage_by_day: dict[str, dict[str, float]],
    last_30: list[str],
) -> list[dict[str, object]]:
    stage_names = {
        key: translate_phrase(str(metrics[key][0]["metric_name"]))
        for key in SLEEP_STAGE_KEYS
        if key in metrics
    }
    legend = [
        {
            "key": key,
            "name": stage_names[key],
            "url": f"/devices/metrics/{key}",
            "avg30": _window_mean(stage_by_day[key], last_30),
        }
        for key in SLEEP_STAGE_KEYS
        if key in stage_names
    ]
    # An unstaged night draws in a colour of its own, and colour may never
    # be the only carrier of meaning: it earns a legend row, but only while
    # such a night is actually on screen. There is no metric page and no
    # separate series behind it, so the row carries neither link nor mean.
    if any(not night["has_stages"] and night["asleep_frac"] > 0 for night in nights):
        legend.append(
            {
                "key": "unstaged",
                "name": t("tracker.stage_unstaged"),
                "url": None,
                "avg30": None,
                "hint": t("tracker.stage_unstaged_hint"),
            }
        )
    return legend


def _sleep_tracker(
    metrics: dict[str, list[dict[str, object]]],
    grouped: dict[str, list[dict[str, object]]],
    preferences: dict[str, str],
    windows: dict[str, list[str]],
) -> dict[str, object] | None:
    bar_days, last_30 = windows["bars"], windows["last_30"]
    stage_by_day = {
        key: {str(row["day"]): float(row["value"]) for row in metrics.get(key, [])}
        for key in SLEEP_STAGE_KEYS
    }
    asleep_by_day = {str(row["day"]): float(row["value"]) for row in metrics.get("sleep_duration", [])}
    in_bed_by_day = {str(row["day"]): float(row["value"]) for row in metrics.get("time_in_bed", [])}
    sleep_rows = [row for key in SLEEP_FAMILY for row in grouped.get(key, [])]
    cohorts = sleep_cohorts(sleep_rows, preferences.get("sleep", ""))
    # What a night without stages actually draws, so the peak that scales
    # the chart is measured on the same quantity. Leaving the durations out
    # of `totals` made a record of asleep-only nights (an iPhone without a
    # watch, an older export) scale every column against a peak of zero.
    fallback_by_day = {
        day: asleep_by_day[day] if day in asleep_by_day else in_bed_by_day.get(day)
        for day in bar_days
    }
    peak = max(
        (
            sum(stage_by_day[key].get(day, 0.0) for key in SLEEP_STAGE_KEYS)
            or fallback_by_day[day]
            or 0.0
            for day in bar_days
        ),
        default=0.0,
    )
    nights = [
        _sleep_night(day, peak, stage_by_day, asleep_by_day, in_bed_by_day,
                     fallback_by_day[day], sleep_rows, cohorts)
        for day in bar_days
    ]
    legend = _sleep_legend(nights, metrics, stage_by_day, last_30)
    if not any(night["has_stages"] or night["asleep"] is not None for night in nights):
        return None
    return _sleep_summary(
        nights, legend, metrics, grouped, preferences, windows, asleep_by_day, in_bed_by_day
    )


def _sleep_summary(
    nights: list[dict[str, object]],
    legend: list[dict[str, object]],
    metrics: dict[str, list[dict[str, object]]],
    grouped: dict[str, list[dict[str, object]]],
    preferences: dict[str, str],
    windows: dict[str, list[str]],
    asleep_by_day: dict[str, float],
    in_bed_by_day: dict[str, float],
) -> dict[str, object]:
    last_7, last_30 = windows["last_7"], windows["last_30"]
    asleep_30 = _window_mean(asleep_by_day, last_30)
    asleep_previous = _window_mean(asleep_by_day, windows["previous_30"])
    sleep_source_rows = [
        row for key in (*SLEEP_STAGE_KEYS, "sleep_duration", "time_in_bed")
        for row in grouped.get(key, [])
    ]
    sleep_day_metric_counts = Counter(
        (str(row["day"]), str(row["metric_key"])) for row in sleep_source_rows
    )
    return {
        "nights": nights,
        "policy": _policy("sleep_duration", preferences, metrics.get("sleep_duration", []))["description"],
        "source_switches": source_switches(metrics.get("sleep_duration", [])),
        "legend": legend,
        "unit": display_unit("hours"),
        "asleep_avg7": _window_mean(asleep_by_day, last_7),
        "asleep_avg30": asleep_30,
        "asleep_delta_pct": _delta_percent(asleep_30, asleep_previous),
        "in_bed_avg30": _window_mean(in_bed_by_day, last_30),
        "source_count": len({
            (str(row["source_vendor"]), str(row["source_name"])) for row in sleep_source_rows
        }),
        "overlap_days": len({
            day for (day, _metric), count in sleep_day_metric_counts.items() if count > 1
        }),
    }


def area_tracker(
    connection: sqlite3.Connection, owner_user_id: str, area_id: str
) -> dict[str, object] | None:
    """Tracker dashboard data for a device-driven health area.

    Per metric: the last 14 calendar days as bars (a missing day stays a
    visible gap, never an invented zero), the 7- and 30-day means, and the
    30-day mean against the previous 30 days. All windows are anchored on the
    newest recorded day in the area, not on today: an export imported after a
    sync gap should describe the last month that was actually measured.
    """
    if area_id not in TRACKER_AREA_IDS:
        return None
    area_clause, area_params = _area_row_predicate(area_id)
    tz = user_timezone(connection, owner_user_id)
    # One aggregate pass answers everything that needs the whole history: which
    # metrics this area has, how many days each has ever recorded (the card
    # order) and when each last recorded (the anchor). It counts in SQLite
    # rather than building 58 000 dicts to throw nearly all of them away.
    summary = _tracker_summary(connection, owner_user_id, area_clause, area_params)
    if not summary:
        return None

    anchor = max(last_day for _, last_day in summary.values())
    previous_30 = _day_range(anchor, 60)[:30]
    windows = {
        "bars": _day_range(anchor, _BAR_DAYS),
        "last_7": _day_range(anchor, 7),
        "last_30": _day_range(anchor, 30),
        "previous_30": previous_30,
    }

    # Every value the page computes comes from the comparison window, whose
    # oldest day is the first of the previous 30 — so that is the whole read.
    grouped = _tracker_grouped(
        connection, owner_user_id, summary, previous_30[0], area_clause, area_params, tz
    )
    preferences = source_preferences(connection, owner_user_id)
    metrics = {key: days for key, days in select_metrics(grouped, preferences).items() if days}
    if not metrics:
        return None

    # The panel definition already states the order a person reads these in
    # (steps before flights, speed before asymmetry); anything the panel does
    # not name follows, most-recorded first.
    panel = PANEL_BY_ID.get(area_id)
    preferred = list(panel.device_members) if panel else []
    rank = {key: index for index, key in enumerate(preferred)}

    cards = [
        _tracker_card(metric_key, days, grouped[metric_key], summary[metric_key][0], windows)
        for metric_key, days in metrics.items()
        if not (area_id == "sleep" and metric_key in _SLEEP_STACK_KEYS)
    ]
    cards.sort(key=lambda card: (rank.get(card["metric_key"], 99), -int(card["day_count"])))

    sleep = _sleep_tracker(metrics, grouped, preferences, windows) if area_id == "sleep" else None
    return {"anchor_day": anchor, "cards": cards, "sleep": sleep}


#: The adapters a person can feed, and the envelope keys of the linked
#: accounts that write under each one.
_VENDOR_ADAPTERS = (
    ("apple_health", "Apple Health", ()),
    ("oura", "Oura", ("oura_api",)),
    ("garmin", "Garmin", ("garmin_personal_api", "garmin_api")),
    ("kardia", "Kardia", ()),
    ("openwearables", "OpenWearables", ("openwearables_api",)),
)
_PROVIDER_BY_ENVELOPE = {
    "oura_api": "oura", "garmin_api": "garmin", "garmin_personal_api": "garmin_personal",
    "openwearables_api": "openwearables",
}


def _overview_imports(connection: sqlite3.Connection, owner_user_id: str) -> list[dict[str, object]]:
    imports = [
        dict(row)
        for row in connection.execute(
            """SELECT di.*, v.canonical_name vendor FROM device_imports di
               JOIN vendors v ON v.id=di.vendor_id WHERE di.owner_user_id=?
               ORDER BY di.imported_at DESC, di.rowid DESC""",
            (owner_user_id,),
        )
    ]
    # What each import still contributes.  A cumulative export superseded by
    # a newer one owns nothing any more (the newer copy took every row), and a
    # linked account's envelope has no export dates: both are described by
    # the rows they own, not by the header they were saved with (OPS-12).
    owned = {
        str(row["import_id"]): dict(row)
        for row in connection.execute(
            """SELECT import_id, COUNT(*) rows_owned, MIN(day) first_day, MAX(day) last_day
               FROM device_metric_days WHERE owner_user_id=? GROUP BY import_id""",
            (owner_user_id,),
        )
    }
    for item in imports:
        try:
            metadata = json.loads(str(item["metadata_json"]))
        except json.JSONDecodeError:
            metadata = {}
        item["metadata"] = metadata
        facts = owned.get(str(item["id"]), {})
        item["rows_owned"] = int(facts.get("rows_owned") or 0)
        item["first_day"] = facts.get("first_day") or item.get("export_started_at")
        item["last_day"] = facts.get("last_day") or item.get("export_ended_at")
        item["is_account"] = str(item["adapter_key"]) in _PROVIDER_BY_ENVELOPE
        item["last_sync_at"] = metadata.get("last_sync_at") if item["is_account"] else None
        item["superseded"] = not item["is_account"] and not item["rows_owned"]
    return imports


def _vendor_status(live: list, accounts: list, files: list, via_bridge: object) -> str:
    if live:
        return t("devices.status_api")
    if accounts:
        return t("devices.status_api_paused")
    if files:
        return t("devices.status_direct")
    if via_bridge:
        return t("devices.status_bridged")
    return t("devices.status_ready")


def _overview_vendors(
    imports: list[dict[str, object]], connected: set[str], bridged: dict[str, list[int | str]]
) -> list[dict[str, object]]:
    by_adapter: dict[str, list[dict[str, object]]] = {}
    for item in imports:
        by_adapter.setdefault(str(item["adapter_key"]), []).append(item)
    return [
        _vendor_row(key, name, envelopes, by_adapter, connected, bridged)
        for key, name, envelopes in _VENDOR_ADAPTERS
    ]


def _latest_of(items: list[dict[str, object]], field: str) -> str | None:
    return max((str(item[field]) for item in items if item[field]), default=None)


def _vendor_row(
    key: str,
    name: str,
    envelopes: tuple[str, ...],
    by_adapter: dict[str, list[dict[str, object]]],
    connected: set[str],
    bridged: dict[str, list[int | str]],
) -> dict[str, object]:
    accounts = [item for envelope in envelopes for item in by_adapter.get(envelope, [])]
    files = [item for item in by_adapter.get(key, []) if not item["superseded"]]
    live = [item for item in accounts if _PROVIDER_BY_ENVELOPE[str(item["adapter_key"])] in connected]
    rows = sum(int(item["rows_owned"]) for item in accounts + files)
    last_day = _latest_of(accounts + files, "last_day")
    last_sync = _latest_of(accounts, "last_sync_at")
    via_bridge = None if (accounts or files) else bridged.get(name)
    if via_bridge:
        rows, last_day = int(via_bridge[0]), str(via_bridge[1]) or None
    return {
        "key": key,
        "name": name,
        "status": _vendor_status(live, accounts, files, via_bridge),
        "record_count": rows,
        "latest_date": last_day,
        "last_sync_at": last_sync,
        "import_id": (accounts or files)[0]["id"] if (accounts or files) else None,
    }


def _overview_overlap(overlap_rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    overlap_metrics: dict[str, dict[str, object]] = {}
    for row in overlap_rows:
        item = overlap_metrics.setdefault(str(row["metric_key"]), {
            "metric_key": str(row["metric_key"]),
            "name": translate_phrase(str(row["metric_name"])),
            "days": 0,
            "latest_day": str(row["day"]),
            "max_sources": 0,
            "vendors": set(),
            "url": f"/devices/metrics/{row['metric_key']}",
        })
        item["days"] = int(item["days"]) + 1
        item["max_sources"] = max(int(item["max_sources"]), int(row["source_count"]))
        item["vendors"].update(str(row["vendors"] or "").split(","))  # type: ignore[union-attr]
    overlap_list = sorted(
        overlap_metrics.values(), key=lambda item: (str(item["latest_day"]), int(item["days"])), reverse=True
    )
    for item in overlap_list:
        item["vendors"] = sorted(vendor for vendor in item["vendors"] if vendor)
    return overlap_list


def device_overview(
    connection: sqlite3.Connection, owner_user_id: str, cards: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    imports = _overview_imports(connection, owner_user_id)
    connected = {
        str(row[0])
        for row in connection.execute(
            "SELECT provider FROM provider_connections WHERE user_id=?", (owner_user_id,)
        )
    }
    # Rows a vendor's device recorded but only the OpenWearables bridge
    # carried: "Apple Health · through the bridge" rather than "not set up".
    bridged: dict[str, list[int | str]] = {}
    for row in connection.execute(
        """SELECT source_name, COUNT(*) rows_held, MAX(day) last_day FROM device_metric_days
           WHERE owner_user_id=? AND source_vendor='OpenWearables' GROUP BY source_name""",
        (owner_user_id,),
    ):
        _origin, physical = bridge_origin(str(row["source_name"]))
        entry = bridged.setdefault(physical, [0, ""])
        entry[0] = int(entry[0]) + int(row["rows_held"])
        entry[1] = max(str(entry[1]), str(row["last_day"]))
    vendors = _overview_vendors(imports, connected, bridged)
    # The caller may already hold this scan of every stored day.
    if cards is None:
        cards = device_metric_catalog(connection, owner_user_id)
    by_key = {str(item["id"]).removeprefix("device:"): item for item in cards}
    core_metrics = [by_key[key] for key in CORE_METRIC_KEYS if key in by_key]
    # Read more rows than are shown, because several of them are the same
    # session seen twice; `counts.workouts` below still reports rows held, not
    # sessions, so the number on the page and the number in the table agree.
    workouts = _preferred_workouts(
        connection.execute(
            "SELECT * FROM device_workouts WHERE owner_user_id=? ORDER BY started_at DESC LIMIT 40",
            (owner_user_id,),
        ).fetchall()
    )[:12]
    for workout in workouts:
        workout["source_label"] = human_source_label(str(workout["source_vendor"]), str(workout["source_name"]))
        for alternate in workout.get("alternates") or []:
            alternate["source_label"] = human_source_label(str(alternate["source_vendor"]), str(alternate["source_name"]))
    events = [
        dict(row, source_label=human_source_label(str(row["source_vendor"]), str(row["source_name"])))
        for row in connection.execute(
            """SELECT de.*, d.id document_id FROM device_events de
               LEFT JOIN documents d ON d.owner_user_id=de.owner_user_id AND d.source_path=de.source_file
               WHERE de.owner_user_id=? ORDER BY de.started_at DESC LIMIT 16""",
            (owner_user_id,),
        )
    ]
    counts = dict(
        connection.execute(
            """SELECT
                 (SELECT COUNT(*) FROM device_metric_days WHERE owner_user_id=?) daily_rows,
                 (SELECT COUNT(*) FROM device_workouts WHERE owner_user_id=?) workouts,
                 (SELECT COUNT(*) FROM device_events WHERE owner_user_id=?) events,
                 (SELECT MAX(day) FROM device_metric_days WHERE owner_user_id=?) latest_day""",
            (owner_user_id,) * 4,
        ).fetchone()
    )
    overlap_rows = connection.execute(
        """SELECT metric_key, MAX(metric_name) metric_name, day,
                  COUNT(*) source_count,
                  GROUP_CONCAT(DISTINCT source_vendor) vendors
           FROM device_metric_days WHERE owner_user_id=?
           GROUP BY metric_key, day HAVING COUNT(*) > 1
           ORDER BY day DESC""",
        (owner_user_id,),
    ).fetchall()
    overlap_list = _overview_overlap(overlap_rows)
    return {
        "imports": imports,
        "active_import_count": sum(1 for item in imports if not item["superseded"]),
        "vendors": vendors,
        "core_metrics": core_metrics,
        "workouts": workouts,
        "events": events,
        "counts": counts,
        "source_overlap": {
            "metric_count": len(overlap_list),
            # Calendar days with any overlap, not metric-days: 38 metrics
            # overlapping on the same day is one day, not 38 (UX-33).
            "day_count": len({str(row["day"]) for row in overlap_rows}),
            "metrics": overlap_list[:12],
        },
    }
