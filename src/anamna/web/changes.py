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
from urllib.parse import urlencode

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import ai, diagnoses, factors
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
from . import factors_view

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
        return {"comparable": True, "direction": "flat", "text": t("changes.no_change"), "share": 0.0}
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
        "share": abs(delta / float(before) * 100) if float(before) else None,
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
        "panel_id": panel.id if panel else None,
        "area_id": area_ids[0] if area_ids else "other",
        "area_name": web.translate_phrase(str(area.get("name", "Other results"))),
        "date_text": web.format_date(row.get("observed_at")),
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


SORTS = ("status", "name", "change", "date")
SHOWS = ("all", "attention", "changed", "medicine", "unverified", "due")
GROUPS = ("area", "panel", "status", "none")
#: How many rows a body-system or test-group section shows before "Show all".
SECTION_CAP = 5


def view_options(sort: str = "", show: str = "", group: str = "", reverse: str = "", *, everything=False, area="") -> dict:
    """The reader's sort, filter and grouping; anything unknown is the page's own default.

    ``show="outside"`` is the name the page used before ``"attention"``, and
    still means it.  ``everything`` groups by body system by default; ``area``
    is a body-system id, validated by the caller."""
    if show == "outside":
        show = "attention"
    default_group = "area" if everything else "status"
    return {
        "sort": sort if sort in SORTS else "status",
        "show": show if show in SHOWS else "all",
        "default_group": default_group,
        "group": group if group in GROUPS else default_group,
        "reverse": reverse == "1",
        "everything": bool(everything),
        "area": area,
    }


def view_query(options: dict) -> str:
    """The choices that differ from the default, as a query string: a link to
    another period carries them, and the default page keeps a clean address.
    The body-system filter is not part of it."""
    pairs = []
    if options["sort"] != "status":
        pairs.append(("sort", options["sort"]))
    if options["show"] != "all":
        pairs.append(("show", options["show"]))
    if options["group"] != options["default_group"]:
        pairs.append(("group", options["group"]))
    if options["reverse"]:
        pairs.append(("reverse", "1"))
    return urlencode(pairs)


def _kept(entry: dict, show: str) -> bool:
    if show == "all":
        return True
    if show == "attention":
        return bool(entry.get("attention"))
    if show == "due":
        return bool(entry.get("due"))
    if show == "medicine":
        return bool(entry.get("influences"))
    if show == "unverified":
        return bool(entry["unverified"])
    if show == "changed":
        return entry["bucket"] in ("new", "resolved")
    return False


def _change_size(entry: dict) -> tuple:
    # Biggest relative change first; a result with nothing to compare goes last.
    share = (entry.get("change") or {}).get("share")
    return (share is None, -(share or 0.0), entry["name"].casefold())


def _ordered(entries: list[dict], sort: str) -> list[dict]:
    """Sorted for the reader: attention first under "status", then by the chosen key."""
    if sort == "name":
        return sorted(entries, key=lambda entry: entry["name"].casefold())
    if sort == "change":
        return sorted(entries, key=_change_size)
    if sort == "date":
        # Stable sorts: by name first, then newest day first with the undated last.
        by_name = sorted(entries, key=lambda entry: entry["name"].casefold())
        return sorted(by_name, key=lambda entry: (bool(entry["day"]), entry["day"]), reverse=True)
    return sorted(entries, key=lambda entry: (0 if entry.get("attention") else 1, *_sort_key(entry)))


def _section(found: list[dict], *, key: str, title: str, url, url_kind: str, more_url, capped: bool) -> dict:
    """A body-system or test-group section: cut to SECTION_CAP when capped, open when it flags something."""
    flagged = sum(1 for entry in found if entry.get("attention"))
    over = capped and len(found) > SECTION_CAP
    return {
        "kind": "section",
        "key": key,
        "title": title,
        "url": url,
        "url_kind": url_kind,
        "entries": found[:SECTION_CAP] if over else found,
        "total": len(found),
        "flagged": flagged,
        "more_url": more_url if over else None,
        "open": not capped or flagged > 0,
    }


def _plain(kind: str, found: list[dict], title: str, *, open_: bool) -> dict:
    """A list or a fold: never cut, never linked."""
    return {
        "kind": kind,
        "key": "",
        "title": title,
        "url": None,
        "url_kind": "",
        "entries": found,
        "total": len(found),
        "flagged": sum(1 for entry in found if entry.get("attention")),
        "more_url": None,
        "open": open_,
    }


def _group_sections(shown: list[dict], group: str, areas, capped: bool) -> list[dict]:
    names = dict(areas)
    grouped: dict = {}
    for entry in shown:
        grouped.setdefault(entry["area_id"] if group == "area" else (entry["context"], entry["panel_url"]), []).append(entry)
    if group == "area":
        # Known body systems in the order given; unknown ones after them, in order of first appearance.
        position = {area_id: i for i, (area_id, _) in enumerate(areas)}
        keys = sorted(grouped, key=lambda area_id: position.get(area_id, len(position)))
    else:
        keys = list(grouped)  # the sort decides the order of the groups
    sections = []
    for key in keys:
        found = grouped[key]
        if group == "area":
            area_id = key
            sections.append(_section(
                found, key=f"area-{area_id}", title=names.get(area_id, found[0]["area_name"]),
                url=f"/areas/{area_id}" if area_id in names else None, url_kind="area",
                more_url=f"/results?area={area_id}", capped=capped,
            ))
        else:
            first = found[0]
            sections.append(_section(
                found, key=f"panel-{first['panel_id'] or first['area_id']}", title=first["context"],
                url=first["panel_url"], url_kind="panel",
                more_url=first["panel_url"] or f"/results?area={first['area_id']}", capped=capped,
            ))
    return sections


def arrange(report: dict, options: dict, *, areas=()) -> dict:
    """The report's entries as the sections the page prints.

    ``options`` is what ``view_options`` returned.  Entries are narrowed to one
    body system when ``options["area"]`` is set, then kept by ``show``, sorted
    and reversed when asked.  ``group`` decides the sections: ``"status"`` gives
    the results that changed or are outside their range as one open list, then
    one closed fold per quiet bucket; ``"area"`` (body system, ``areas`` is
    ``(id, name)`` in display order) and ``"panel"`` (test group) give one
    section per group in the order each first appears; ``"none"`` gives one list.
    On the whole ``everything`` report with no filter, a body-system or
    test-group section shows ``SECTION_CAP`` rows and links to the rest.
    ``kind`` is ``"list"``, ``"fold"`` or ``"section"``."""
    entries = [*report["open"], *(entry for _, found in report["collapsed"] for entry in found)]
    if options["area"]:
        entries = [entry for entry in entries if entry["area_id"] == options["area"]]
    shown = [entry for entry in _ordered(entries, options["sort"]) if _kept(entry, options["show"])]
    if options["reverse"]:
        shown.reverse()
        if options["sort"] == "date":
            # Oldest first: a result with no date is not the oldest, it stays last.
            shown.sort(key=lambda entry: not entry["day"])
    group = options["group"]
    if group == "none":
        sections = [_plain("list", shown, "", open_=True)] if shown else []
    elif group == "status":
        opened = [entry for entry in shown if entry["bucket"] in OPEN_BUCKETS]
        sections = [_plain("list", opened, "", open_=True)] if opened else []
        for bucket in BUCKETS:
            found = [entry for entry in shown if entry["bucket"] == bucket]
            if bucket not in OPEN_BUCKETS and found:
                sections.append(_plain("fold", found, t(f"changes.bucket_{bucket}"), open_=False))
    else:
        capped = options["everything"] and options["show"] == "all" and not options["area"] and group in ("area", "panel")
        sections = _group_sections(shown, group, areas, capped)
    return {
        **options,
        "sections": sections,
        "shown": len(shown),
        "total": len(entries),
        # The page's own "nothing changed" line: only when nothing was filtered away.
        "nothing_open": options["group"] == "status" and options["show"] == "all"
        and not any(entry["bucket"] in OPEN_BUCKETS for entry in shown),
    }


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
    everything: bool = False,
) -> dict | None:
    """One report: the latest result episode, a chosen one, a date range or one document.

    Every test measured inside the selection appears once, with its newest
    reading there, compared with its last reading from *before* the selection
    -- never with another day of the same episode, which would call the second
    half of one order a change.  Other readings inside the selection are kept
    on the entry (``also``) rather than dropped.  None when ``document_id`` is
    not this owner's document.

    ``everything`` (with no document, range or episode) gives the newest result
    of every test, home-monitoring readings included, each compared with the
    reading before its own newest episode.
    """
    from . import app as web  # the page helpers live there; imported late to avoid a cycle

    age, sex = web._demographics(connection, owner_user_id)
    documents, orders_of, home = _load_documents(web, connection, owner_user_id)
    focus: dict[tuple[str, object], str] | None = None
    if document_id:
        if document_id not in documents:
            return None
        focus = _document_focus(connection, owner_user_id, document_id)
    whole = everything and not document_id and not episode and not (_parse_day(date_from) or _parse_day(date_to))
    series = _displayable_series(web, connection, owner_user_id, home, document_id)

    concept_days, spans = _episode_spans(series, orders_of)
    kind, index, lower, upper = _selection(focus, date_from, date_to, episode, spans, whole)
    if whole:
        full = _displayable_series(web, connection, owner_user_id, set(), None)
        full_spans = _episode_spans(full, orders_of)[1]

    def inside(concept_id: str, row: dict) -> bool:
        return _row_inside(focus, kind, lower, upper, bool(spans), concept_id, row)

    entries, document_ids, days_seen = [], [], set()
    for concept_id, daily in (full if whole else series).items():
        if whole:
            positions = _latest_positions(daily, full_spans)
        else:
            positions = [i for i, row in enumerate(daily) if inside(concept_id, row)]
        if not positions:
            continue
        entries.append(
            _selected_entry(web, connection, concept_id, daily, positions, focus, document_id, age, sex)
        )
        _note_sources(daily, positions, document_id, days_seen, document_ids)
    by_concept = factors.influences(connection, owner_user_id, today=date.today())
    locale = get_locale()
    for entry in entries:
        entry["influences"] = factors_view.influence_chips(
            factors.influencing(by_concept.get(entry["concept_id"], []), entry["day"], entry["previous_day"]),
            locale=locale,
        )

    report = _build_report(entries, days_seen, document_ids, documents)
    episodes = _episode_rows(spans, concept_days, kind, index)
    nav = _episode_nav(kind, index, len(spans), episodes)
    dated = sorted(day for day in concept_days if day) or [""]
    # The AI state is "where do I stand now": the latest episode or one document.
    scope = _ai_scope(document_id, focus, kind)
    payload = ai_payload([report]) if report and scope else []
    factor_items = (
        factors_payload(connection, owner_user_id, today=date.today()) + diagnoses_payload(connection, owner_user_id)
        if payload else []
    )
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
        "everything": whole,
        "ai_payload": payload,
        "ai_factors": factor_items,
        # The medicines travel with the results, so a change in either makes a saved summary stale.
        "fingerprint": fingerprint({"results": payload, "factors": factor_items}),
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


def _selection(focus, date_from, date_to, episode, spans, whole: bool = False) -> tuple[str, int, str, str]:
    """What is selected: one document, every test's newest result, a date range, an episode, or the latest episode."""
    kind, index, lower, upper = "latest", 0, "", ""
    if focus is not None:
        kind = "document"
    elif whole:
        kind = "everything"
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


def _latest_positions(daily: list[dict], spans: list[tuple[str, str]]) -> list[int]:
    """The rows of a test's newest episode: its newest reading, and any other reading of the same episode."""
    day = _day(daily[0])
    lower, upper = next(((first, last) for first, last in spans if first <= day <= last), (day, day))
    return [i for i, row in enumerate(daily) if lower <= _day(row) <= upper]


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
    # The day of this reading and of the one it is compared with: what a
    # medicine has to cover, or fall between, to bear on the change.
    entry["day"] = _day(row)
    entry["previous_day"] = _day(previous) if previous is not None else ""
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
            "url": "/results?episode=latest" if i == 0 else f"/results?episode={first or 'undated'}",
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


#: Medicines and other factors sent with a change summary: the current ones, and those that started or ended within this many months.
FACTOR_WINDOW_MONTHS = 18
FACTOR_LIMIT = 20
DIAGNOSIS_LIMIT = 40


def _months_before(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, 28))


def _year_month(value: object) -> str | None:
    text = str(value or "")[:7]
    return text if re.fullmatch(r"\d{4}-\d{2}", text) else None


def factors_payload(connection, owner_user_id: str, *, today: date) -> list[dict]:
    """The medicines and other factors the model may connect to these results.

    A factor is included when it is current, or when it started or ended in the
    window before today.  One stopped three years ago cannot explain this report,
    and listing it invites the model to blame it.
    """
    since = _months_before(today, FACTOR_WINDOW_MONTHS).isoformat()
    now = today.isoformat()
    chosen = []
    for factor in factors.listing(connection, owner_user_id, today=today):
        recent = any(
            value and since <= str(value)[:10] <= now
            for value in (factor["started_on"], factor["ended_on"])
        )
        if factor["effective_status"] == "current" or recent:
            chosen.append(factor)
    # Stable: current first, the order of the Medicines page otherwise.
    chosen.sort(key=lambda factor: factor["effective_status"] != "current")
    payload = []
    for factor in chosen[:FACTOR_LIMIT]:
        item = {
            "name": factor["name"],
            "kind": factor["kind"],
            "since": _year_month(factor["started_on"]),
            "until": _year_month(factor["ended_on"]),
            "status": factor["effective_status"],
            "can_change": [
                {"test": effect["label"], "direction": effect["direction"]}
                for effect in factor["effects"]
            ],
        }
        how_taken = factors.regimen_text(factor, "en")
        if how_taken:
            item["how_taken"] = how_taken
        payload.append(item)
    return payload


def diagnoses_payload(connection, owner_user_id: str) -> list[dict]:
    """The recorded diagnoses, as items of kind ``diagnosis`` beside the factors.

    All of them, active and over: the summary of a 2018 report must see what was diagnosed
    in 2018.  The model is told to connect a result only to a diagnosis whose dates cover it.
    """
    return [
        {
            "name": diagnoses.display_name(row, "en"),
            "kind": "diagnosis",
            "code": row["code"],
            "status": row["status"],
            "certainty": row["certainty"],
            "since": _year_month(row["diagnosed_on"]),
            "until": _year_month(row["resolved_on"]),
        }
        for row in diagnoses.listing(connection, owner_user_id)[:DIAGNOSIS_LIMIT]
    ]


def fingerprint(payload) -> str:
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


def _factor_numbers(factor_items) -> set[float]:
    """A medicine's name can carry a number ("Діокор 80", "Вітамін D3"): a sentence naming it is grounded.

    The same holds for how it is taken ("1 tablet, 2 times a day"): those numbers are in the record.
    """
    found: set[float] = set()
    for item in factor_items:
        found |= _numbers(str(item["name"]))
        found |= _numbers(str(item.get("how_taken") or ""))
    return found


def _factor_years(factor_items) -> set[float]:
    """The years a medicine started or stopped: the months it is written with."""
    found: set[float] = set()
    for item in factor_items:
        for key in ("since", "until"):
            found |= {float(year) for year in _YEAR.findall(str(item.get(key) or "")) if 1900 <= int(year) <= 2100}
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


def messages_for(payload: list[dict], locale: str, factor_items=()) -> list[dict]:
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
        "medicines, lab variation), then the conditions doctors usually check for. "
        "Say which is most likely for this person given the other results in the data, and why.\n"
        "- `usually_next`: one to three things that are typically done next: repeating the test "
        "and how to prepare for it, the related tests that would narrow down the cause, the kind "
        "of doctor who deals with it, and the treatment that is used when that applies, named "
        "specifically (the medicine or class, not just \"treatment\"). Figures other than the "
        "measurements cannot appear in this summary because every number is checked against the "
        "data, so leave doses out here: the person can ask the assistant, which works them out.\n"
        "- `ask`: one to three specific questions this person could ask their doctor about this "
        "result, not generic ones.\n"
        "- Read results that belong together as one picture (for example iron studies with "
        "haemoglobin, liver enzymes with bilirubin, lipids with glucose, kidney markers together, "
        "thyroid tests together): when several of them are in the data, say in `how_serious` or "
        "`possible_reasons` what the combination suggests, not each value alone.\n"
        "- `factors` lists the medicines and other things the person recorded (supplements, operations, "
        "illnesses, diet, training), with the month they started and stopped and the results each can "
        "change. When a change in a result follows the start, the stop or a change of one of them, or "
        "one of them is known to move that result, say so in `possible_reasons` and name it. Do not "
        "blame a factor the data does not connect to the result.\n"
        "- Items of `factors` with kind `diagnosis` are the person's recorded diagnoses, with the month "
        "each was made and, when it is over, resolved. When a result fits one whose dates cover the result "
        "(for example raised liver enzymes with a recorded fatty liver, a raised white cell count during a "
        "recorded infection), say so in `possible_reasons` and name it. A diagnosis made after the result, "
        "or resolved before it, cannot explain it.\n"
        "- `findings`: up to five results that are new, still or newly outside range, most "
        "important first; skip stable and improved ones. `improved`: up to four short items that "
        "resolved or moved towards range. `state`: two or three sentences on the overall picture: "
        "what the abnormal results suggest together, and how serious it is overall.\n"
        "- Be brief: each sentence and list item short and concrete, no repetition between fields.\n"
        f"Write every text field in {language}; `test` is the test name exactly as given. Answer "
        "with one JSON object. Empty lists are fine."
    )
    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": json.dumps(
            {"results": payload, "factors": list(factor_items)}, ensure_ascii=False
        )},
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


def summarise(settings, payload: list[dict], locale: str, factor_items=()) -> tuple[dict, str]:
    """Ask the configured model; return the cleaned answer and the model name.

    A sentence or item carrying a number the data does not contain is dropped,
    not repaired: an invented value is worse than a shorter summary.  So is a
    finding about a test the data does not name.  A medicine's own name and
    start or stop months are data too, so a sentence naming it keeps its numbers.
    """
    result = ai.complete(
        settings, AI_FEATURE, messages_for(payload, locale, factor_items), response_format=_SCHEMA
    )
    parsed = ai.parse_json_reply(result.content)
    allowed = (
        _measurement_numbers(payload) | _payload_years(payload)
        | _factor_numbers(factor_items) | _factor_years(factor_items)
    )
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


def _summarise_exclusive(
    settings, key: tuple[str, str, str, str], payload: list[dict], locale: str, factor_items=()
):
    """`summarise`, refused with `in_progress` while the same scope is already being asked."""
    with _ACTIVE_LOCK:
        if key in _ACTIVE:
            raise ai.AIUnavailable("in_progress")
        _ACTIVE.add(key)
    try:
        return summarise(settings, payload, locale, factor_items)
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
        content, model = _summarise_exclusive(settings, key, view["ai_payload"], locale, view["ai_factors"])
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

    @app.get("/changes")
    def changes_page(request: Request):
        """The Changes page is part of /results; an old link lands on the same selection there."""
        query = request.url.query
        if not any(request.query_params.get(name) for name in ("document", "episode", "from", "to")):
            query = "episode=latest" + (f"&{query}" if query else "")
        return RedirectResponse(f"/results?{query}", status_code=301)

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
        location = (f"/results?document={document}" if document else "/results?episode=latest") + "#changes-ai"
        wants_json = "application/json" in request.headers.get("accept", "")
        return _answer_ai_summary(settings, build, user["id"], document, refresh, location, wants_json)
