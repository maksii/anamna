"""Presentation-only summaries. Clinical interpretation stays in reference.evaluate.

These helpers never classify a result, set a goal, or combine device sources.
They receive the already-selected, owner-scoped catalog from the web layer.
"""
from __future__ import annotations

from datetime import date
from math import isfinite


FOCUS_AREAS = ("blood", "heart", "activity", "sleep")
#: How many area cards the overview leads with.
FOCUS_LIMIT = 4
_PREFERRED = {
    "heart": ("device:resting_heart_rate", "device:heart_rate"),
    "activity": ("device:steps", "device:active_energy"),
    "sleep": ("device:sleep_duration", "device:time_in_bed"),
}


def _sparkline(series: list[dict]) -> str:
    """Exact points on a time axis; no synthetic readings or implied target."""
    points = []
    for item in series:
        try:
            day = date.fromisoformat(str(item["date"])[:10]).toordinal()
            value = float(item["value"])
            if isfinite(value):
                points.append((day, value))
        except (KeyError, ValueError, TypeError):
            continue
    points.sort()
    if len(points) < 2:
        return ""
    low, high = min(v for _, v in points), max(v for _, v in points)
    start, end = points[0][0], points[-1][0]
    return " ".join(
        f"{4 + (day - start) * 212 / max(1, end - start):.2f},"
        f"{36 - (value - low) * 30 / (high - low) if high != low else 21:.2f}"
        for day, value in points
    )


def _representatives(area: dict, catalog: list[dict], limit: int = 2, flagged: frozenset = frozenset()) -> list[dict]:
    """The readings an area card shows: what the verdicts flagged first, then
    the area's everyday signal (resting heart rate, steps, sleep)."""
    candidates = [card for card in catalog if area["id"] in card.get("area_ids", [])]
    preferred = _PREFERRED.get(area["id"], ())
    if not preferred:
        candidates = list(area.get("metrics", [])) or candidates
    candidates.sort(key=lambda c: (
        0 if c.get("id") in flagged else 1,
        preferred.index(c["id"]) if c.get("id") in preferred else len(preferred),
        -int(bool(c.get("latest_date"))),
    ))
    return [{**card, "experience_spark": _sparkline(card.get("series", []))} for card in candidates[:limit]]


def build_overview(areas: list[dict], catalog: list[dict], counts: dict, attention: list[dict] = ()) -> dict:
    """The area cards worth opening first, plus the complete area directory.

    `attention` is the already-judged attention list, most severe first: the
    areas it touches lead, then the everyday four fill the remaining places.
    """
    by_id = {area["id"]: area for area in areas}
    flagged = frozenset(str(card["id"]) for card in attention)
    order = [str(card.get("primary_area_id") or "") for card in attention] + list(FOCUS_AREAS)
    keys = [key for key in dict.fromkeys(order) if key in by_id][:FOCUS_LIMIT]
    focal = [
        {**by_id[key], "featured_metrics": _representatives(by_id[key], catalog, flagged=flagged)}
        for key in keys
    ]
    return {
        "focus": focal,
        "areas": areas,
        # Evidence means something to open: a measurement, or a report
        # conclusion with its document.  An area with neither is not "recorded".
        "recorded_areas": sum(
            bool(area.get("metric_count") or area.get("finding_document_count")) for area in areas
        ),
        "area_count": len(areas),
        "metric_count": len(catalog),
        "latest_medical": counts.get("latest_result"),
        "latest_device": counts.get("latest_device"),
    }


def build_area_experience(area: dict, metrics: list[dict], tracker: dict | None = None) -> dict:
    """Summarize recording coverage, keeping unavailable dates visibly absent."""
    cards = (tracker or {}).get("cards", [])
    tracked_dates = sorted({str(c["latest_day"]) for c in cards if c.get("latest_day")})
    sleep = (tracker or {}).get("sleep")
    if sleep:
        tracked_dates += [str(n["day"]) for n in sleep.get("nights", [])
                          if n.get("asleep") is not None or n.get("has_stages")]
    return {
        "id": area["id"],
        "featured_metrics": _representatives(area, metrics, 3),
        "tracked_metrics": len(cards),
        "latest_device": max(tracked_dates) if tracked_dates else None,
        "has_tracker": bool(cards or sleep),
    }
