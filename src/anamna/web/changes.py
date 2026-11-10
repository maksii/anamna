"""What changed: the latest result episode set beside the readings before it.

A new upload adds values to forty metric pages at once; reading them one page
at a time is how a person misses the one that crossed its interval.  This page
gathers result dates into episodes (one laboratory order arrives over several
days), shows one episode as one report, compares each test with its result
from before the episode, and sorts the comparison into a handful of buckets a
person reads in a glance.  A selector reaches earlier episodes or merges any
date range into one report the same way.

Nothing here judges a value.  Every verdict comes from `_reading_verdict`, the
same call `_lab_card` makes, so the two pages cannot disagree about a number.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import date
from typing import Annotated

from fastapi import Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import ai
from ..db import connect, utc_now
from ..i18n import (
    EN_MONTHS_SHORT,
    UK_MONTHS_SHORT,
    format_date_localized,
    format_number_localized,
    get_locale,
    t,
)
from ..panels import (
    ATTENTION_INTERPRETATIONS,
    BORDERLINE_INTERPRETATIONS,
    DISPLAY_SUPPRESSED,
    HOME_MONITORING_TYPES,
    NORMAL_INTERPRETATIONS,
)
from ..reference import canonical_unit

#: Display order.  The first four are what a person came to read and are shown
#: open; the rest collapse behind a count.
BUCKETS = ("new", "resolved", "still", "borderline", "first", "stable", "unjudged")
OPEN_BUCKETS = ("new", "resolved", "still", "borderline")
#: Readings a change row's chart shows: this one and up to four before it.
TREND_POINTS = 5
#: The chart's viewBox: wide and short, so a row stays one line tall.
_TW, _TH, _PAD_X, _PAD_TOP, _PAD_BOTTOM = 300.0, 74.0, 22.0, 17.0, 15.0
#: The AI state covers the newest dates only: it is a "where do I stand now",
#: not a history.  ponytail: fixed window, make it a choice if anyone asks.
AI_GROUPS = 4
AI_FEATURE = "changes_summary"
AI_ERRORS = ("disabled", "budget", "provider_error", "in_progress")
_DIRECTION_RANK = {"worse": 0, None: 1, "same": 1, "better": 2}
_DECIMALS = re.compile(r"[.,](\d+)$")

# Home monitoring PDFs (HOME_MONITORING_TYPES) are device readings, read on
# their metric pages and /devices.  Near-daily home blood pressure would
# otherwise chain separate lab visits into one month-long "episode" and bury
# the laboratory results this page is for, so this page leaves them out.

_DOCUMENTS_SQL = """SELECT d.id, d.title, d.clinical_type, d.original_filename, d.report_date,
                           d.imported_at, d.vendor_id, d.order_identifier, v.canonical_name vendor
                      FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                     WHERE d.owner_user_id=?"""


def verdict_state(verdict: dict | None) -> str:
    """Out of range, on its edge, inside it, or not judged at all."""
    reading = str((verdict or {}).get("interpretation") or "unjudged")
    if reading in ATTENTION_INTERPRETATIONS:
        return "out"
    if reading in BORDERLINE_INTERPRETATIONS:
        return "edge"
    if reading in NORMAL_INTERPRETATIONS:
        return "in"
    return "none"


def classify(verdict: dict, previous: dict | None) -> str:
    """The bucket for one result, from its verdict and the previous one's.

    ``previous`` is None when this is the first time the test was measured.
    """
    now = verdict_state(verdict)
    before = verdict_state(previous) if previous is not None else None
    if now == "none":
        return "unjudged"
    if now == "out":
        return "still" if before == "out" else "new"
    if now == "edge":
        return "borderline"
    if before is None:
        return "first"
    return "resolved" if before in ("out", "edge") else "stable"


def _distance(value: float, low, high) -> float:
    if high is not None and value > float(high):
        return value - float(high)
    if low is not None and value < float(low):
        return float(low) - value
    return 0.0


def direction(value, previous_value, verdict: dict) -> str | None:
    """Whether a result still outside its interval moved towards it or away.

    Measured as distance from the interval the current verdict shades, so a
    value that crossed from below to above is read as the distance it now sits
    out, not as "it went up".  None when there is no numeric bound to measure.
    """
    low, high = verdict.get("target_low"), verdict.get("target_high")
    if value is None or previous_value is None or (low is None and high is None):
        return None
    now = _distance(float(value), low, high)
    before = _distance(float(previous_value), low, high)
    if abs(now - before) <= 0.02 * max(now, before, 1e-9):
        return "same"
    return "better" if now < before else "worse"


def _change(web, row, previous, unit_source, previous_unit_source, unit) -> dict | None:
    """The delta to the previous reading, or why there is none."""
    if previous is None:
        return None
    current, before = row["value_numeric"], previous["value_numeric"]
    if current is None or before is None:
        return None
    if canonical_unit(unit_source) != canonical_unit(previous_unit_source):
        return {"comparable": False, "text": t("changes.units_differ")}
    # A difference is worth as many decimals as the readings carry: 0.32 and
    # 0.26 differ by 0.06, which a per-unit rounding would print as 0.1.
    decimals = max(
        len(match.group(1)) if (match := _DECIMALS.search(web.format_measured(float(value), unit))) else 0
        for value in (current, before)
    )
    delta = float(current) - float(before)
    amount = format_number_localized(abs(delta), decimals)
    if not re.search(r"[1-9]", amount):
        return {"comparable": True, "direction": "flat", "text": t("changes.no_change")}
    sign = "+" if delta > 0 else "−"
    amount = f"{sign}{amount} {unit}".strip() if unit else f"{sign}{amount}"
    percent = None
    if float(before):
        share = abs(delta / float(before) * 100)
        percent = t("changes.percent", value=f"{sign}{format_number_localized(share, 0 if share >= 10 else 1)}")
    return {
        "comparable": True,
        "direction": "up" if delta > 0 else "down",
        "text": t("changes.delta", amount=amount, percent=percent) if percent else amount,
    }


def _month(value: object) -> str:
    """«вер. 2025» / "Sep 2025": a chart axis needs the month, not the day."""
    text = str(value or "")[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", text):
        return ""
    months = UK_MONTHS_SHORT if get_locale() == "uk" else EN_MONTHS_SHORT
    return f"{months[int(text[5:7]) - 1]} {text[:4]}"


def _trend(web, history: list[dict], unit_source, unit: str, verdict: dict) -> dict | None:
    """This reading and the few before it as one small chart, oldest first.

    Only readings in the same unit as this one: a chart that mixes µmol/L with
    mg/dL draws a jump that never happened.  Fewer than two such readings is no
    trend, and the row keeps its plain values instead.
    """
    same = canonical_unit(unit_source)
    series = [
        item for item in history
        if item["value_numeric"] is not None
        and canonical_unit(item["preferred_unit"] or item["unit_raw"]) == same
    ][:TREND_POINTS][::-1]
    if len(series) < 2:
        return None
    values = [float(item["value_numeric"]) for item in series]
    # The band the reader should be in, as the metric page's sparkline shades it.
    band_low = verdict.get("target_low", verdict.get("low"))
    band_high = verdict.get("target_high", verdict.get("high"))
    bounds = [float(value) for value in (band_low, band_high) if value is not None]
    # Scaled to the readings, not to the band: a 3-13 px wiggle under a band
    # that stretched the axis showed no change at all (`web.fit_domain`).
    low, high = web.fit_domain(values, bounds)
    plot_top, plot_bottom = _PAD_TOP, _TH - _PAD_BOTTOM

    def y(value: float) -> float:
        return round(plot_bottom - (value - low) / (high - low) * (plot_bottom - plot_top), 1)

    step = (_TW - 2 * _PAD_X) / (len(series) - 1)
    points = []
    for index, item in enumerate(series):
        value = float(item["value_numeric"])
        points.append({
            "x": round(_PAD_X + index * step, 1),
            "y": y(value),
            "value": web.format_measured(value, unit),
            "month": _month(item.get("observed_at")),
            "date": web.format_date(item.get("observed_at")),
            "current": index == len(series) - 1,
        })
    band = None
    if bounds:
        # Clipped to the plot: a bound the axis no longer reaches is off-chart.
        top = y(float(band_high)) if band_high is not None else plot_top
        bottom = y(float(band_low)) if band_low is not None else plot_bottom
        top, bottom = (min(max(edge, plot_top), plot_bottom) for edge in (top, bottom))
        if bottom > top:
            band = {"y": top, "height": round(bottom - top, 1)}
    return {
        "width": _TW,
        "height": _TH,
        "baseline": plot_bottom,
        "points": points,
        "path": " ".join(f"{point['x']},{point['y']}" for point in points),
        "band": band,
        "label": t(
            "changes.trend_label",
            values=", ".join(f"{point['date']}: {point['value']}" for point in points),
            unit=unit or "",
        ),
    }


def _entry(web, connection, concept_id, row, previous, document_id, observation_id, age, sex, history=None):
    unit_source, verdict = web._reading_verdict(connection, concept_id, row, age, sex)
    unit = web.display_unit(unit_source)
    previous_info = previous_verdict = previous_unit_source = None
    if previous is not None:
        previous_unit_source, previous_verdict = web._reading_verdict(
            connection, concept_id, previous, age, sex
        )
        previous_unit = web.display_unit(previous_unit_source)
        previous_info = {
            "date_text": web.format_date(previous.get("observed_at")),
            "value_text": web.format_reading(previous, previous_unit),
            "unit": previous_unit,
            "verdict": previous_verdict,
        }
    bucket = classify(verdict, previous_verdict if previous is not None else None)
    change = _change(web, row, previous, unit_source, previous_unit_source, unit)
    moved = None
    if bucket == "still" and change and change.get("comparable"):
        moved = direction(row["value_numeric"], previous["value_numeric"], verdict)
    name, category = str(row["canonical_name"]), str(row["category"])
    panel = web.panel_for_concept(concept_id, category)
    area_ids = web.metric_area_ids(name, category)
    area = web.AREA_BY_ID.get(area_ids[0] if area_ids else "other", {})
    status = str(row.get("verification_status") or "extracted")
    entry = {
        "concept_id": concept_id,
        "url": f"/metrics/{concept_id}",
        "name": web.concept_display_name(name),
        "context": web.translate_phrase(panel.name) if panel else web.translate_phrase(
            str(area.get("name", "Other results"))
        ),
        "panel_url": f"/panels/{panel.id}" if panel else None,
        "value_text": web.precise_at_edges(row["value_numeric"], web.format_reading(row, unit), verdict),
        "unit": unit,
        "verdict": verdict,
        "previous": previous_info,
        "change": change,
        "bucket": bucket,
        "direction": moved,
        "document_id": document_id,
        "source_url": f"/documents/{document_id}#observation-{observation_id}",
        "unverified": status not in ("verified", "corrected"),
        "verification_label": web.status_label(status),
        "same_day_count": int(row.get("same_day_count") or 1),
        "trend": _trend(web, history or [row], unit_source, unit, verdict),
        "value_numeric": row["value_numeric"],
    }
    entry["label"] = bucket_label(entry)
    return entry


def _sort_key(entry: dict) -> tuple:
    return (BUCKETS.index(entry["bucket"]), _DIRECTION_RANK.get(entry["direction"], 1), entry["name"].casefold())


#: Days between two result dates that still count as one result episode.  A
#: laboratory order arrives in parts -- the blood count on day 1, the
#: biochemistry on day 3, a culture or an allergy panel a week later -- and a
#: reader wants that as one report, not as four.  A week covers the slowest
#: routine part (cultures, extended panels) without welding two separate visits
#: together.  ponytail: fixed constant, make it a setting if anyone asks.
EPISODE_GAP_DAYS = 7


def _day(row) -> str:
    return str(row.get("observed_at") or "")[:10]


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def group_episodes(days: set[str], orders: dict[object, set[str]] | None = None) -> list[tuple[str, str]]:
    """Result dates as (first, last) episodes, oldest first.

    Two neighbouring dates belong to one episode when they are at most
    `EPISODE_GAP_DAYS` apart, or when one laboratory order (``orders``: order
    key -> the dates it delivered on) has results on both sides of the gap.
    """
    ordered = sorted(day for day in days if _parse_day(day))
    spans = [(min(found), max(found)) for found in (orders or {}).values() if found]
    episodes: list[list[str]] = []
    for day in ordered:
        if episodes:
            previous = episodes[-1][1]
            gap = (date.fromisoformat(day) - date.fromisoformat(previous)).days
            if gap <= EPISODE_GAP_DAYS or any(low <= previous and high >= day for low, high in spans):
                episodes[-1][1] = day
                continue
        episodes.append([day, day])
    return [(first, last) for first, last in episodes]


def span_text(first: str, last: str) -> str:
    """«05 лист. 2025», «03–04 серп. 2026», «28 серп. – 04 вер. 2025», «28 груд. 2024 – 04 січ. 2025»."""
    if not first:
        return t("date.unknown")
    if first == last:
        return format_date_localized(first)
    start, end = format_date_localized(first), format_date_localized(last)
    if first[:7] == last[:7]:
        return t("changes.span_days", start=first[8:10], end=end)
    if first[:4] == last[:4]:
        start = start.removesuffix(f" {first[:4]}")
    return t("changes.span", start=start, end=end)


def build_changes(
    connection,
    owner_user_id: str,
    *,
    document_id: str | None = None,
    episode: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict | None:
    """One report: the latest result episode, a chosen one, a date range or one document.

    Every test measured inside the selection appears once, with its newest
    reading there, compared with its last reading from *before* the selection
    -- never with another day of the same episode, which would call the second
    half of one order a change.  Other readings inside the selection are kept
    on the entry (``also``) rather than dropped.  None when ``document_id`` is
    not this owner's document.
    """
    from . import app as web  # the page helpers live there; imported late to avoid a cycle

    age, sex = web._demographics(connection, owner_user_id)
    documents, orders_of, home = _load_documents(web, connection, owner_user_id)
    focus: dict[tuple[str, object], str] | None = None
    if document_id:
        if document_id not in documents:
            return None
        focus = _document_focus(connection, owner_user_id, document_id)
    series = _displayable_series(web, connection, owner_user_id, home, document_id)

    concept_days, spans = _episode_spans(series, orders_of)
    kind, index, lower, upper = _selection(focus, date_from, date_to, episode, spans)

    def inside(concept_id: str, row: dict) -> bool:
        return _row_inside(focus, kind, lower, upper, bool(spans), concept_id, row)

    entries, document_ids, days_seen = [], [], set()
    for concept_id, daily in series.items():
        positions = [i for i, row in enumerate(daily) if inside(concept_id, row)]
        if not positions:
            continue
        entries.append(
            _selected_entry(web, connection, concept_id, daily, positions, focus, document_id, age, sex)
        )
        _note_sources(daily, positions, document_id, days_seen, document_ids)

    report = _build_report(entries, days_seen, document_ids, documents)
    episodes = _episode_rows(spans, concept_days, kind, index)
    nav = _episode_nav(kind, index, len(spans), episodes)
    dated = sorted(day for day in concept_days if day) or [""]
    # The AI state is "where do I stand now": the latest episode or one document.
    scope = _ai_scope(document_id, focus, kind)
    payload = ai_payload([report]) if report and scope else []
    return {
        "groups": [report] if report else [],
        "report": report,
        "episodes": episodes,
        "selection": {
            "kind": kind,
            "from": lower,
            "to": upper,
            "label": span_text(lower or dated[0], upper or dated[-1]),
        },
        "nav": nav,
        "bounds": {"min": dated[0], "max": dated[-1]},
        "document": documents.get(document_id) if document_id else None,
        "scope": scope,
        "ai_payload": payload,
        "fingerprint": fingerprint(payload),
    }


def _load_documents(web, connection, owner_user_id: str) -> tuple[dict, dict, set]:
    documents, orders_of, home = {}, {}, set()
    for row in connection.execute(_DOCUMENTS_SQL, (owner_user_id,)):
        documents[str(row["id"])] = web._document_row(row)
        if row["clinical_type"] in HOME_MONITORING_TYPES:
            home.add(str(row["id"]))
        if row["order_identifier"]:
            orders_of[str(row["id"])] = (row["vendor_id"], str(row["order_identifier"]))
    return documents, orders_of, home


def _episode_spans(series: dict, orders_of: dict) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    # Episodes over every result date; undated readings are one episode of their own.
    concept_days: dict[str, set[str]] = {}
    order_days: dict[object, set[str]] = {}
    for concept_id, daily in series.items():
        for row in daily:
            concept_days.setdefault(_day(row), set()).add(concept_id)
            order = orders_of.get(str(row["document_id"]))
            if order and _day(row):
                order_days.setdefault(order, set()).add(_day(row))
    spans = group_episodes(set(concept_days), order_days)[::-1]  # newest first
    if "" in concept_days:
        spans.append(("", ""))
    return concept_days, spans


def _row_inside(focus, kind: str, lower: str, upper: str, has_spans: bool, concept_id: str, row: dict) -> bool:
    if focus is not None:
        return (concept_id, row.get("observed_at")) in focus
    day = _day(row)
    if kind == "range":
        return bool(day) and (not lower or day >= lower) and (not upper or day <= upper)
    if not has_spans:
        return False
    return day == "" if lower == "" else bool(day) and lower <= day <= upper


def _note_sources(daily: list, positions: list, document_id, days_seen: set, document_ids: list) -> None:
    for i in positions:
        days_seen.add(_day(daily[i]))
        source = document_id or str(daily[i]["document_id"])
        if source not in document_ids:
            document_ids.append(source)


def _episode_nav(kind: str, index: int, total: int, episodes: list) -> dict:
    nav = {}
    if kind not in ("latest", "episode"):
        return nav
    if index + 1 < total:
        nav["earlier"] = episodes[index + 1]
    if index > 0:
        nav["newer"] = episodes[index - 1]
    return nav


def _ai_scope(document_id: str | None, focus: object, kind: str) -> str | None:
    if focus is not None:
        return f"document:{document_id}"
    return "all" if kind == "latest" else None


def _document_focus(connection, owner_user_id: str, document_id: str) -> dict[tuple[str, object], str]:
    # Matched on (test, date) rather than on the row the catalog kept: a
    # re-uploaded copy of a report loses the de-duplication to the
    # original, and "what did this upload change" must still answer.
    return {
        (str(item["concept_id"]), item["observed_at"]): str(item["id"])
        for item in connection.execute(
            """SELECT id, concept_id, observed_at FROM observations
                WHERE document_id=? AND owner_user_id=? AND verification_status <> 'rejected'""",
            (document_id, owner_user_id),
        )
    }


def _displayable_series(
    web, connection, owner_user_id: str, home: set[str], document_id: str | None
) -> dict[str, list[dict]]:
    by_concept: dict[str, list[dict]] = {}
    for row in web._deduped_observation_rows(connection, owner_user_id):
        if str(row["document_id"]) in home and not document_id:
            continue
        by_concept.setdefault(str(row["concept_id"]), []).append(row)

    series: dict[str, list[dict]] = {}
    for concept_id, values in by_concept.items():
        if concept_id in DISPLAY_SUPPRESSED:
            continue
        daily = web._one_per_day(values)
        if web._displayable_metric(str(daily[0]["canonical_name"])):
            series[concept_id] = daily  # newest first
    return series


def _selection(focus, date_from, date_to, episode, spans) -> tuple[str, int, str, str]:
    """What is selected: one document, a date range, an episode, or the latest episode."""
    kind, index, lower, upper = "latest", 0, "", ""
    if focus is not None:
        kind = "document"
    elif _parse_day(date_from) or _parse_day(date_to):
        kind = "range"
        lower, upper = _range_bounds(date_from, date_to)
    elif episode and spans:
        index = _episode_position(episode, spans)
        kind = "latest" if index == 0 else "episode"
    if kind in ("latest", "episode") and spans:
        lower, upper = spans[index]
    return kind, index, lower, upper


def _range_bounds(date_from, date_to) -> tuple[str, str]:
    lower, upper = str(_parse_day(date_from) or ""), str(_parse_day(date_to) or "")
    if lower and upper and lower > upper:
        lower, upper = upper, lower
    return lower, upper


def _episode_position(episode: str, spans) -> int:
    # Any date inside an episode finds it, so a link survives the episode
    # growing when the rest of the order arrives.  Unknown: the latest.
    wanted = "" if episode == "undated" else str(_parse_day(episode) or "-")
    return next((i for i, (first, last) in enumerate(spans) if first <= wanted <= last), 0)


def _selected_entry(web, connection, concept_id, daily, positions, focus, document_id, age, sex) -> dict:
    newest, oldest = positions[0], positions[-1]
    row = daily[newest]
    oldest_day = _day(daily[oldest])
    # The last reading from before the selection, never one inside it.
    previous = next(
        (item for item in daily[oldest + 1:] if not oldest_day or _day(item) < oldest_day), None
    )
    observation_id = focus.get((concept_id, row.get("observed_at"))) if focus else str(row["id"])
    entry = _entry(
        web, connection, concept_id, row, previous, document_id or str(row["document_id"]),
        observation_id, age, sex, daily[newest: newest + TREND_POINTS + 3],
    )
    # Measured more than once in the selection: the newest is the result,
    # the others are named beside it rather than dropped.
    entry["also"] = [
        f"{web.format_date(daily[i].get('observed_at'))}: "
        + " ".join(filter(None, (web.format_reading(daily[i], entry["unit"]), entry["unit"])))
        for i in positions[1:]
    ]
    return entry


def _build_report(entries, days_seen, document_ids, documents) -> dict | None:
    if not entries:
        return None
    entries.sort(key=_sort_key)
    seen = sorted(day for day in days_seen if day)
    first, last = (seen[0], seen[-1]) if seen else ("", "")
    counts = {bucket: sum(1 for e in entries if e["bucket"] == bucket) for bucket in BUCKETS}
    return {
        "date": first if first == last else f"{first}..{last}",
        "date_text": span_text(first, last),
        "anchor": "changes-report",
        "counts": counts,
        "open": [e for e in entries if e["bucket"] in OPEN_BUCKETS],
        "collapsed": [
            (bucket, [e for e in entries if e["bucket"] == bucket])
            for bucket in BUCKETS
            if bucket not in OPEN_BUCKETS and counts[bucket]
        ],
        "total": len(entries),
        "documents": [documents[i] for i in document_ids if i in documents],
    }


def _episode_rows(spans, concept_days, kind: str, index: int) -> list[dict]:
    def tests_in(first: str, last: str) -> int:
        if not first:
            return len(concept_days[""])
        return len(set().union(*(ids for day, ids in concept_days.items() if day and first <= day <= last)))

    return [
        {
            "value": first or "undated",
            "label": span_text(first, last),
            "count": tests_in(first, last),
            "url": "/changes" if i == 0 else f"/changes?episode={first or 'undated'}",
            "current": kind in ("latest", "episode") and i == index,
        }
        for i, (first, last) in enumerate(spans)
    ]


# --- AI short state ------------------------------------------------------------


def bucket_label(entry: dict) -> str:
    if entry["bucket"] == "still" and entry.get("direction"):
        return t(f"changes.direction_{entry['direction']}")
    return t(f"changes.bucket_{entry['bucket']}")


def _beyond(entry: dict) -> dict | None:
    """How far outside its target this reading is, computed here so the model
    quotes a real number instead of estimating one."""
    value, verdict = entry.get("value_numeric"), entry["verdict"]
    low, high = verdict.get("target_low"), verdict.get("target_high")
    if value is None:
        return None
    value = float(value)
    if high is not None and value > float(high) and float(high) > 0:
        return {"side": "above upper limit", "percent": round((value - float(high)) / float(high) * 100)}
    if low is not None and value < float(low) and float(low) > 0:
        return {"side": "below lower limit", "percent": round((float(low) - value) / float(low) * 100)}
    return None


def ai_payload(groups: list[dict]) -> list[dict]:
    """The change data the model sees: tests, values, ranges, earlier
    readings and dates -- and nothing that names the person.  Built from the
    page's own entries so the model can only be asked about what the reader
    is looking at."""
    payload = []
    for group in groups[:AI_GROUPS]:
        payload.append({
            "date": group["date"],
            "counts": {t(f"changes.bucket_{b}"): n for b, n in group["counts"].items() if n},
            "changes": [
                {
                    "test": entry["name"],
                    "status": bucket_label(entry),
                    "value": entry["value_text"],
                    "unit": entry["unit"] or "",
                    "verdict": entry["verdict"]["label"],
                    "verdict_code": entry["verdict"].get("interpretation") or "",
                    "target_range": entry["verdict"].get("target_range_text") or "",
                    "band": entry["verdict"].get("band_label") or "",
                    "beyond_target": _beyond(entry),
                    "earlier": [
                        {"month": point["month"], "value": point["value"]}
                        for point in (entry["trend"] or {}).get("points", [])[:-1]
                    ],
                    "previous": {
                        "date": entry["previous"]["date_text"],
                        "value": entry["previous"]["value_text"],
                        "unit": entry["previous"]["unit"] or "",
                        "verdict": entry["previous"]["verdict"]["label"],
                    } if entry["previous"] else None,
                    "change": (entry["change"] or {}).get("text") or "",
                }
                for entry in group["open"]
            ],
        })
    return payload


def fingerprint(payload: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


#: How serious a finding is, as the model judges it for that test.  A fixed
#: set so the page can label and explain each level in both languages.
LEVELS = ("slight", "moderate", "marked", "urgent")
_STRINGS = {"type": "array", "items": {"type": "string"}}
_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "changes_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "test": {"type": "string"},
                            "level": {"type": "string", "enum": list(LEVELS)},
                            "how_serious": {"type": "string"},
                            "what_it_is": {"type": "string"},
                            "possible_reasons": _STRINGS,
                            "usually_next": _STRINGS,
                            "ask": _STRINGS,
                        },
                        "required": ["test", "level", "how_serious", "what_it_is",
                                     "possible_reasons", "usually_next", "ask"],
                        "additionalProperties": False,
                    },
                },
                "improved": _STRINGS,
            },
            "required": ["state", "findings", "improved"],
            "additionalProperties": False,
        },
    },
}
_LANGUAGE = {"en": "English", "uk": "Ukrainian"}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(match.replace(",", ".")) for match in _NUMBER.findall(text)}


def _grounded(text: str, allowed: set[float]) -> bool:
    """Every number the model wrote is one the data contains."""
    return _numbers(text) <= allowed


#: Payload fields that hold a measured value, change, target bound or percent; dates, ids, counts, ages are not.
_MEASUREMENT_FIELDS = ("value", "change", "target_range", "percent")


def _measurement_numbers(payload) -> set[float]:
    """The numbers the data holds as measurements, found by walking the payload's measurement fields."""
    found: set[float] = set()
    if isinstance(payload, dict):
        for key, item in payload.items():
            if key in _MEASUREMENT_FIELDS and isinstance(item, (str, int, float)):
                found |= _numbers(str(item))
            elif isinstance(item, (dict, list)):
                found |= _measurement_numbers(item)
    elif isinstance(payload, list):
        for item in payload:
            found |= _measurement_numbers(item)
    return found


#: Payload fields that hold a date or a month (the group date, a previous reading's date, earlier months).
_DATE_FIELDS = ("date", "month")
_YEAR = re.compile(r"\b\d{4}\b")


def _payload_years(payload) -> set[float]:
    """The years the data names in its date fields: a year is when a reading was taken, not a duration or a dose."""
    found: set[float] = set()
    if isinstance(payload, dict):
        for key, item in payload.items():
            if key in _DATE_FIELDS and isinstance(item, str):
                found |= {float(year) for year in _YEAR.findall(item) if 1900 <= int(year) <= 2100}
            elif isinstance(item, (dict, list)):
                found |= _payload_years(item)
    elif isinstance(payload, list):
        for item in payload:
            found |= _payload_years(item)
    return found


def _clamped_level(level: str, verdict: str) -> str:
    """The model's severity, held inside what the reference engine's verdict
    allows.  The engine is the only judge of a value; the model words the
    change, it does not get to out-rank or under-rank that judgment."""
    if level not in LEVELS:
        return level
    rank = LEVELS.index(level)
    if verdict.startswith("critical"):
        rank = max(rank, LEVELS.index("marked"))
    elif verdict.startswith("borderline") or verdict in ("normal", "optimal"):
        rank = min(rank, LEVELS.index("moderate"))
    return LEVELS[rank]


def messages_for(payload: list[dict], locale: str) -> list[dict]:
    language = _LANGUAGE.get(locale, "English")
    rules = (
        "You explain a person's recent laboratory changes to that person, the way a careful, "
        "plain-spoken clinician would at the start of a visit: what each abnormal result is, how "
        "worrying it is, what commonly causes it and what is usually done next. The data is the "
        "latest report: results from a few consecutive days, each compared with the previous result "
        "of the same test from before them. Each change carries the test, its value and unit, the "
        "verdict from the reference engine (`verdict_code` is its code), the target range, the band label of the published "
        "source, `beyond_target` (how far outside the target it is, already computed), earlier "
        "readings and the previous result.\n"
        "Rules:\n"
        "- Numbers: quote only numbers that appear in the data, exactly as written. Never invent, "
        "round or recompute one, and write no other figures (no thresholds, multiples, doses, ages "
        "or durations) in any field. Describe the size of a change or a deviation only by quoting "
        "`change` or `beyond_target.percent`; never in words such as twice, almost double, several "
        "times or half.\n"
        "- When you mention when an earlier reading was taken, name the month and year only, never the day of the month.\n"
        "- Severity (`level`): judge it for THAT test using general medical knowledge and the data "
        "-- how far outside the range, the direction, whether it is rising, and how much that test "
        "usually matters. `slight`: just outside, commonly not significant on its own. `moderate`: "
        "clearly outside, worth raising at the next routine visit. `marked`: far outside or "
        "steadily worsening, worth seeing a doctor about soon. `urgent`: a value that usually "
        "needs prompt medical attention. Be honest in both directions: do not alarm about a "
        "slight deviation and do not soften a marked one. The level must not contradict the verdict "
        "given for that test: a critical verdict is never `slight`, and a borderline, normal or "
        "optimal verdict is never `marked` or `urgent`. `how_serious` says this in one or two "
        "sentences, referring to the value, the range and the earlier readings.\n"
        "- `what_it_is`: one sentence on what the test measures and why it matters.\n"
        "- `possible_reasons`: two to four common general causes of a result like this, most "
        "common and benign first (for example recent exercise, a meal, a recent infection, "
        "medicines, lab variation), then the conditions doctors usually check for. These are "
        "possibilities, never a diagnosis of this person.\n"
        "- `usually_next`: one to three things that are typically done next, such as repeating "
        "the test or checking related tests. No treatments, medicines or doses.\n"
        "- `ask`: one to three specific questions this person could ask their doctor about this "
        "result, not generic ones.\n"
        "- `findings`: up to five results that are new, still or newly outside range, most "
        "important first; skip stable and improved ones. `improved`: up to four short items that "
        "resolved or moved towards range. `state`: two or three sentences on the overall picture "
        "and how serious it is overall.\n"
        "- Be brief: each sentence and list item short and concrete, no repetition between fields.\n"
        f"Write every text field in {language}; `test` is the test name exactly as given. Answer "
        "with one JSON object. Empty lists are fine."
    )
    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": json.dumps({"results": payload}, ensure_ascii=False)},
    ]


def _clean_text(value: object, allowed: set[float], cap: int = 400) -> str:
    cleaned = value.strip()[:cap] if isinstance(value, str) else ""
    return cleaned if cleaned and _grounded(cleaned, allowed) else ""


def _clean_items(values: object, cap: int, allowed: set[float]) -> list[str]:
    if not isinstance(values, list):
        return []
    kept = [_clean_text(item, allowed, 300) for item in values]
    return [item for item in kept if item][:cap]


def _clean_finding(raw: object, verdicts: dict[str, str], allowed: set[float]) -> dict | None:
    """One model finding, or None when it names an unknown test, level or has no grounded gist.

    ``verdicts`` maps each test in the payload to its engine verdict code; the
    level is held inside that verdict.
    """
    if not isinstance(raw, dict) or raw.get("test") not in verdicts or raw.get("level") not in LEVELS:
        return None
    how_serious = _clean_text(raw.get("how_serious"), allowed)
    if not how_serious:
        return None
    return {
        "test": raw["test"],
        "level": _clamped_level(raw["level"], verdicts[raw["test"]]),
        "how_serious": how_serious,
        "what_it_is": _clean_text(raw.get("what_it_is"), allowed),
        "possible_reasons": _clean_items(raw.get("possible_reasons"), 4, allowed),
        "usually_next": _clean_items(raw.get("usually_next"), 3, allowed),
        "ask": _clean_items(raw.get("ask"), 3, allowed),
    }


def summarise(settings, payload: list[dict], locale: str) -> tuple[dict, str]:
    """Ask the configured model; return the cleaned answer and the model name.

    A sentence or item carrying a number the data does not contain is dropped,
    not repaired: an invented value is worse than a shorter summary.  So is a
    finding about a test the data does not name.
    """
    result = ai.complete(settings, AI_FEATURE, messages_for(payload, locale), response_format=_SCHEMA)
    parsed = ai.parse_json_reply(result.content)
    allowed = _measurement_numbers(payload) | _payload_years(payload)
    # The newest group's verdict wins for a test named in several groups, as attach_notes does.
    verdicts: dict[str, str] = {}
    for group in payload:
        for change in group["changes"]:
            verdicts.setdefault(change["test"], change.get("verdict_code") or "")

    findings = []
    raw_findings = parsed.get("findings")
    for raw in raw_findings if isinstance(raw_findings, list) else []:
        finding = _clean_finding(raw, verdicts, allowed)
        if finding:
            findings.append(finding)
    sentences = re.split(r"(?<=[.!?])\s+", str(parsed.get("state") or "").strip())
    state = " ".join(s for s in sentences if s and _grounded(s, allowed))[:900]
    if not state:
        raise ai.AIUnavailable("provider_error", "summary had no usable state")
    return {
        "state": state,
        "findings": findings[:5],
        "improved": _clean_items(parsed.get("improved"), 4, allowed),
    }, result.model


_ACTIVE: set[tuple[str, str, str, str]] = set()
_ACTIVE_LOCK = threading.Lock()


def _summarise_exclusive(settings, key: tuple[str, str, str, str], payload: list[dict], locale: str):
    """`summarise`, refused with `in_progress` while the same scope is already being asked."""
    with _ACTIVE_LOCK:
        if key in _ACTIVE:
            raise ai.AIUnavailable("in_progress")
        _ACTIVE.add(key)
    try:
        return summarise(settings, payload, locale)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(key)


def _summary_reply(location: str, wants_json: bool, *, cached: bool = False):
    if wants_json:
        body = {"ok": True, "location": location}
        if cached:
            body["cached"] = True
        return JSONResponse(body)
    return RedirectResponse(location, status_code=303)


def load_summary(connection, owner_user_id: str, locale: str, scope: str, current: str):
    row = connection.execute(
        "SELECT * FROM ai_change_summaries WHERE owner_user_id=? AND locale=? AND scope=?",
        (owner_user_id, locale, scope),
    ).fetchone()
    if row is None:
        return None
    try:
        content = json.loads(row["content_json"])
    except ValueError:
        return None
    created = str(row["created_at"] or "")
    return {
        "content": content,
        # The model id is an implementation detail a reader cannot act on, so
        # it stays in the table and is never printed.  The time is stored in
        # UTC; the page prints the date and the browser restates it on the
        # reader's own clock (`time[data-local]`).
        "created_text": format_date_localized(created),
        "created_iso": created if re.search(r"(Z|[+-]\d\d:?\d\d)$", created) else f"{created}Z",
        "stale": row["fingerprint"] != current,
    }


def attach_notes(view: dict, summary: dict | None) -> list[dict]:
    """Move each per-test AI finding into the change row it is about.

    A finding read beside its own value and trend needs no cross-reference;
    the summary block keeps the overall state.  Each finding attaches to the
    newest row of its test.  A stale summary keeps its findings in the summary
    block, under its staleness warning, rather than putting a note written
    about older numbers beside today's.  Returns the findings left behind.
    """
    findings = list(((summary or {}).get("content") or {}).get("findings") or [])
    if not findings or summary.get("stale"):
        return findings
    by_test = {finding["test"]: finding for finding in findings}
    for group in view["groups"][:AI_GROUPS]:
        for entry in group["open"]:
            finding = by_test.pop(entry["name"], None)
            if finding is not None:
                entry["ai_note"] = finding
    return [finding for finding in findings if finding["test"] in by_test]


def _can_ask(settings, request, user, view: dict, viewing_row) -> bool:
    return (
        ai.ai_active(settings, AI_FEATURE)
        and viewing_row(request) is None
        and user.get("token_kind") != "guest"
        and bool(view["ai_payload"])
    )


def _cached_summary_row(connection, user_id: str, locale: str, scope):
    return connection.execute(
        "SELECT fingerprint FROM ai_change_summaries WHERE owner_user_id=? AND locale=? AND scope=?",
        (user_id, locale, scope),
    ).fetchone()


def _failure_reply(failure, location: str, wants_json: bool):
    reason = failure.reason if failure.reason in AI_ERRORS else "provider_error"
    if wants_json:
        return JSONResponse({"ok": False, "reason": reason}, status_code=503)
    joiner = "&" if "?" in location else "?"
    return RedirectResponse(
        location.replace("#changes-ai", f"{joiner}ai_error={reason}#changes-ai"), status_code=303
    )


def _store_summary(settings, user_id: str, locale: str, view: dict, model, content) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_change_summaries(owner_user_id, locale, scope, fingerprint, model, content_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, locale, scope) DO UPDATE SET
                 fingerprint=excluded.fingerprint, model=excluded.model,
                 content_json=excluded.content_json, created_at=excluded.created_at""",
            (user_id, locale, view["scope"], view["fingerprint"], model,
             json.dumps(content, ensure_ascii=False), utc_now()),
        )


def _answer_ai_summary(settings, build, user_id: str, document: str, refresh: str, location: str, wants_json: bool):
    """Serve the cached summary when it still matches the view, otherwise ask the model once."""
    locale = get_locale()
    with connect(settings) as connection:
        view = build(connection, user_id, document)
        cached = _cached_summary_row(connection, user_id, locale, view["scope"])
    if not view["ai_payload"]:
        raise HTTPException(400, t("changes.ai_nothing"))
    if cached and cached["fingerprint"] == view["fingerprint"] and refresh != "1":
        return _summary_reply(location, wants_json, cached=True)
    key = (str(settings.database_path), user_id, locale, view["scope"])
    try:
        content, model = _summarise_exclusive(settings, key, view["ai_payload"], locale)
    except ai.AIUnavailable as failure:
        return _failure_reply(failure, location, wants_json)
    _store_summary(settings, user_id, locale, view, model, content)
    return _summary_reply(location, wants_json)


def register_changes_routes(
    app, settings, *, templates, template_context, require_user, require_csrf,
    record_user, viewing_row,
):
    def build(connection, owner_id: str, document: str, **selection):
        view = build_changes(connection, owner_id, document_id=document or None, **selection)
        if view is None:
            raise HTTPException(404)
        return view

    @app.get("/changes", response_class=HTMLResponse)
    def changes_page(
        request: Request,
        document: str = "",
        episode: str = "",
        date_from: Annotated[str, Query(alias="from")] = "",
        date_to: Annotated[str, Query(alias="to")] = "",
    ):
        user = require_user(request)
        owner = record_user(request, user)
        locale = get_locale()
        with connect(settings) as connection:
            view = build(connection, owner["id"], document, episode=episode, date_from=date_from, date_to=date_to)
            summary = (
                load_summary(connection, owner["id"], locale, view["scope"], view["fingerprint"])
                if view["scope"] else None
            )
        unattached = attach_notes(view, summary)
        can_ask = _can_ask(settings, request, user, view, viewing_row)
        error = request.query_params.get("ai_error")
        return templates.TemplateResponse(
            request,
            "changes.html",
            template_context(
                request,
                view=view,
                buckets=BUCKETS,
                episode_gap_days=EPISODE_GAP_DAYS,
                summary=summary,
                summary_findings=unattached,
                ai_can_ask=can_ask,
                ai_error=error if error in AI_ERRORS else None,
                document_filter=document,
                active="changes",
            ),
        )

    @app.post("/changes/ai-summary")
    def changes_ai_summary(
        request: Request,
        csrf_token: Annotated[str, Form()] = "",
        refresh: Annotated[str, Form()] = "",
        document: Annotated[str, Form()] = "",
    ):
        user = require_user(request)
        require_csrf(user, csrf_token)
        # A guest link and a shared-record viewer read; neither spends the
        # owner's AI budget nor sends the owner's results anywhere.
        if user.get("token_kind") == "guest" or viewing_row(request) is not None:
            raise HTTPException(403, t("changes.ai_forbidden"))
        location = (f"/changes?document={document}" if document else "/changes") + "#changes-ai"
        wants_json = "application/json" in request.headers.get("accept", "")
        return _answer_ai_summary(settings, build, user["id"], document, refresh, location, wants_json)
