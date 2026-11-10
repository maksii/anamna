"""Presentation of medicines and other factors: labels, periods, durations, the
time scale their bars are drawn on, and the periods a chart prints under itself.

Storage lives in :mod:`anamna.factors`; these functions turn its rows into the
words and numbers the templates show.  Every label is looked up in the locale
the caller names, so one page renders in one language throughout.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from .. import factors
from ..health import concept_display_name
from ..i18n import (
    EN_MONTHS_SHORT,
    UK_MONTHS_SHORT,
    activate_locale,
    format_date_localized,
    get_locale,
    reset_locale,
    t,
    t_plural,
)

#: The bar scale runs 0..SCALE from the earliest start (0) to today (SCALE).
SCALE = 1000
MIN_BAR = 6
#: Spans of at least this many days are labelled at four moments, then at three.
FOUR_LABEL_DAYS = 2 * 365
THREE_LABEL_DAYS = 60
OTHERS_LIMIT = 12


@contextmanager
def _in(locale: str):
    token = activate_locale(locale)
    try:
        yield
    finally:
        reset_locale(token)


def _day(text: str) -> date:
    return date.fromisoformat(str(text)[:10])


def kind_label(kind: str, locale: str) -> str:
    with _in(locale):
        return t(f"med.kind.{kind}")


def status_label(status: str, locale: str) -> str:
    with _in(locale):
        return t(f"med.status.{status}")


def direction_label(direction: str, locale: str) -> str:
    with _in(locale):
        return t(f"med.dir.{direction}")


def _period(start: str | None, end: str | None, point: bool, ongoing: bool) -> str:
    """The words for a period.  Callers hold the locale; ``ongoing`` means the
    entry still runs, so a start without an end reads as "since"."""
    if start and end:
        return t("med.period.range", start=format_date_localized(start), end=format_date_localized(end))
    if start:
        key = "med.period.ongoing" if ongoing and not point else "med.period.point"
        return t(key, start=format_date_localized(start))
    if end:
        return t("med.period.until_only", end=format_date_localized(end))
    return t("med.period.unknown")


def period_text(row: Mapping[str, Any], locale: str) -> str:
    with _in(locale):
        return _period(
            row["started_on"], row["ended_on"], bool(row["is_point"]), row["effective_status"] == "current",
        )


def _months(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def duration_text(row: Mapping[str, Any], today: date, locale: str) -> str:
    if row["is_point"] or not row["started_on"]:
        return ""
    if row["effective_status"] == "past" and not row["ended_on"]:
        return ""
    start = _day(row["started_on"])
    end = _day(row["ended_on"]) if row["ended_on"] else today
    days = (end - start).days
    if days < 0:
        return ""
    with _in(locale):
        if days < 60:
            return t_plural("med.days", days)
        months = _months(start, end)
        if months < 24:
            return t_plural("med.months", months)
        years, rest = divmod(months, 12)
        text = t_plural("med.years", years)
        return f"{text} {t_plural('med.months', rest)}" if rest else text


def _label_count(span: int) -> int:
    if span >= FOUR_LABEL_DAYS:
        return 4
    if span >= THREE_LABEL_DAYS:
        return 3
    return 2


def _month_year(day: date) -> str:
    """Short month and year in the active locale, with the abbreviations format_date_localized uses."""
    months = UK_MONTHS_SHORT if get_locale() == "uk" else EN_MONTHS_SHORT
    return f"{months[day.month - 1]} {day.year}"


def scale(rows: Iterable[Mapping[str, Any]], today: date, locale: str) -> dict | None:
    """The shared time axis: from the earliest start that is not after today, to today.

    Each tick but the last is the month and year of an evenly spaced moment between
    the start and today; the last is "today".  A tick equal to the one before it is dropped.
    """
    starts = [_day(row["started_on"]) for row in rows if row["started_on"]]
    starts = [start for start in starts if start <= today]
    if not starts:
        return None
    origin = min(starts)
    span = (today - origin).days
    count = _label_count(span)
    with _in(locale):
        ticks: list[str] = []
        for index in range(count - 1):
            day = origin + timedelta(days=round(span * index / (count - 1)))
            label = _month_year(day)
            if not ticks or ticks[-1] != label:
                ticks.append(label)
        ticks.append(t("med.today"))
        start_text = format_date_localized(origin.isoformat())
    return {"start": origin.isoformat(), "start_text": start_text, "ticks": ticks}


def _bar(row: Mapping[str, Any], axis: Mapping[str, Any] | None, today: date, locale: str) -> dict | None:
    if axis is None or not row["started_on"] or row["effective_status"] == "prescribed":
        return None
    start = _day(row["started_on"])
    if start > today:
        return None
    origin = _day(axis["start"])
    span = max((today - origin).days, 1)
    x0 = round(SCALE * (start - origin).days / span)
    point = bool(row["is_point"])
    if point:
        width = MIN_BAR
    else:
        end = min(_day(row["ended_on"]), today) if row["ended_on"] else today
        width = max(MIN_BAR, round(SCALE * (end - start).days / span))
    x0 = max(0, min(x0, SCALE - width))
    return {
        "x0": x0,
        "width": width,
        "point": point,
        "title": t("med.bar_title", name=row["name"], period=period_text(row, locale)),
    }


def effect_view(
    effect: Mapping[str, Any],
    locale: str,
    metric_ids: frozenset[str] | set[str],
    concept_names: Mapping[str, str] | None = None,
) -> dict:
    """An effect for the page: its direction in words, its link to the result's
    chart when this person has results for it, and its localized name.

    ``concept_names`` maps concept id to canonical name; without it a linked
    effect keeps the label it was stored with.
    """
    with _in(locale):
        concept = effect.get("concept_id") or ""
        label = effect.get("label") or ""
        if concept and concept_names and concept in concept_names:
            label = concept_display_name(concept_names[concept])
        return {
            **effect,
            "label": label,
            "direction_label": t(f"med.dir.{effect['direction']}"),
            "url": f"/metrics/{concept}" if concept and concept in metric_ids else "",
        }


def card(
    row: Mapping[str, Any],
    *,
    locale: str,
    today: date,
    scale: Mapping[str, Any] | None = None,
    metric_ids: frozenset[str] | set[str] = frozenset(),
    concept_names: Mapping[str, str] | None = None,
) -> dict:
    """One entry as the medicines list and the detail page show it."""
    with _in(locale):
        data = dict(row)
        data["url"] = f"/medicines/{row['id']}"
        data["kind_label"] = kind_label(row["kind"], locale)
        data["status"] = row["effective_status"]
        data["status_label"] = status_label(row["effective_status"], locale)
        data["dose_line"] = factors.regimen_text(row, locale)
        data["period_text"] = period_text(row, locale)
        data["duration_text"] = duration_text(row, today, locale)
        data["approximate"] = bool(row["dates_approximate"])
        data["effects"] = [effect_view(effect, locale, metric_ids, concept_names) for effect in row["effects"]]
        data["has_reference_text"] = any(row[name] for name in factors.REFERENCE_FIELDS)
        data["bar"] = _bar(row, scale, today, locale)
        data["document"] = None
        data["fact_notes"] = []
    return data


def _item(row: Mapping[str, Any]) -> dict:
    related = bool(row["related"])
    direction = row["direction"] if related else ""
    this = t(f"med.dir_this.{direction}") if related else ""
    text = _period(row["start"], row["end"], bool(row["point"]), ongoing=not row["point"])
    title = f"{row['name']}: {text}" + (f", {this}" if related else "")
    return {
        "id": row["id"],
        "name": row["name"],
        "url": f"/medicines/{row['id']}",
        "kind": row["kind"],
        "kind_label": t(f"med.kind.{row['kind']}"),
        "start": row["start"],
        "end": row["end"],
        "point": row["point"],
        "approximate": row["approximate"],
        "related": related,
        "direction": direction,
        "direction_label": this,
        "note": row["note"],
        "origin": row["origin"],
        "period_text": text,
        "title": title,
    }


def chart_periods(connection, owner_id: str, concept_ids, *, locale: str, today: date) -> dict | None:
    """The entries a chart over ``concept_ids`` prints under itself: those that
    list an effect on it, and the most recent others (capped)."""
    rows = factors.periods(connection, owner_id, concept_ids, today=today)
    if not rows:
        return None
    with _in(locale):
        related = [_item(row) for row in rows if row["related"]]
        others_rows = sorted(
            (row for row in rows if not row["related"]),
            key=lambda row: (row["start"] or "", row["name"]),
            reverse=True,
        )[:OTHERS_LIMIT]
        others = [_item(row) for row in others_rows]
    keys = ("id", "name", "start", "end", "point", "approximate", "related", "direction", "title")
    return {
        "related": related,
        "others": others,
        "json": [{key: item[key] for key in keys} for item in related + others],
    }
