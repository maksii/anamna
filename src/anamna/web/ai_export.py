"""The AI hand-off: one whole record, compressed into one pasteable prompt.

Someone who wants a second opinion from a chat assistant today photographs one
page of one report and asks about it.  The assistant then reasons about a
single number with no interval, no history, no units it can trust and no idea
what else is in the record -- and answers confidently anyway.

This builds the other thing.  Everything the application already knows, already
judged against a cited interval, already translated, arranged so a model reads
the alarming parts first, with three properties that matter more than
completeness:

* **Nothing is silently dropped.**  Every cap in this file states what it left
  out and where to find it.  An export that quietly stops at forty analytes
  reads like a complete record, and the assistant will reason confidently about
  a person whose abnormal result was number forty-one.
* **Bulk telemetry is summarised, not truncated.**  Fifty-eight thousand daily
  wearable rows become monthly means with the row count beside them.  Sending
  the first thousand rows would be both larger and less true.
* **The gaps are declared.**  Medication, symptoms, diagnoses and family
  history are not in this database, so the export says so and tells the
  assistant to ask rather than assume.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Collection, Sequence
from datetime import date

from .. import factors
from ..devices.catalog import CORE_METRIC_KEYS
from ..i18n import get_locale, t, t_plural
from ..panels import SAME_DEVICE_KEYS

#: Optional sections, in the order they are offered, with their default state.
#: Identity is off by default and stays that way: this text is written to be
#: pasted into someone else's chat assistant, and a name and date of birth buy
#: the reader nothing clinically while being the one part of the record that
#: identifies them.
SECTIONS: tuple[tuple[str, bool], ...] = (
    ("history", True),
    ("devices", True),
    ("findings", True),
    ("guidance", False),
    ("documents", False),
    ("identity", False),
)
DEFAULT_SECTIONS = frozenset(key for key, enabled in SECTIONS if enabled)
SECTION_KEYS = frozenset(key for key, _ in SECTIONS)

#: Caps.  Each one has a line in the output naming what it excluded.
MAX_ATTENTION = 40
MAX_HISTORY_POINTS = 8
MAX_HISTORY_METRICS = 120
MAX_DEVICE_MONTHS = 12
MAX_DEVICE_RECENT_DAYS = 14
MAX_FINDINGS = 40
MAX_DOCUMENTS = 60
MAX_GUIDANCE = 80

#: Caps for the page-scoped excerpt.  The subject is the whole point of that
#: prompt, so its history keeps five times the points the record-wide export
#: affords each analyte; everything else stays a one-liner.
MAX_SUBJECT_POINTS = 40
MAX_SUBJECT_CARDS = 60
MAX_SUBJECT_OBSERVATIONS = 200
MAX_ELSEWHERE = 12
MAX_RELATED = 24


def _num(value: object, significant: int = 6) -> str:
    """A number the assistant can parse: dot decimal, no thousands separator.

    Deliberately not ``format_number_localized``.  The surrounding prose is
    localised, but a Ukrainian "1 234,5" inside a data table is two numbers to
    a parser and one number to a reader, and the reader here is a machine.  The
    legend says so in the reader's own language.

    Significant figures, not decimal places: a urine specific gravity of 1.035
    rounded to two decimals prints "1.03", which sits inside the 1.010-1.030
    interval printed beside it and makes the [!] marker look like a mistake.
    Fixed-point rather than ``%g`` so a step count never arrives as 6.93e+03.
    """
    if value is None:
        return "-"
    number = float(value)
    if number == 0:
        return "0"
    decimals = max(0, significant - 1 - math.floor(math.log10(abs(number))))
    text = f"{number:.{decimals}f}"
    return (text.rstrip("0").rstrip(".") or "0") if "." in text else text


def _capped(items: Sequence[object], limit: int) -> tuple[list[object], int]:
    """The first ``limit`` items, and how many were left behind."""
    return list(items[:limit]), max(0, len(items) - limit)


def _marker(card: dict[str, object]) -> str:
    """`[!]`, `[?]` or nothing -- the same judgement the badge on the page makes."""
    verdict = card.get("verdict") or {}
    interpretation = str(verdict.get("interpretation") or "")
    if interpretation in {"critical_low", "critical_high", "critical"}:
        return "[!!] "
    if interpretation in {"low", "high", "positive", "abnormal", "elevated", "deficient"}:
        return "[!] "
    if verdict.get("authorities_disagree") or verdict.get("conflicts_with_vendor"):
        return "[?] "
    if interpretation in {"indeterminate", "borderline", "unjudged"}:
        return "[?] "
    return ""


_SEVERITY_RANK = {"[!!] ": 0, "[!] ": 1, "[?] ": 2}


def _severity(card: dict[str, object]) -> int:
    return _SEVERITY_RANK.get(_marker(card), 3)


def _area_rank(cards: Sequence[dict[str, object]]) -> tuple[int, int]:
    """Worst marker in a body system, then how many are flagged (more first)."""
    ranks = [_severity(card) for card in cards]
    return (min(ranks, default=3), -sum(1 for rank in ranks if rank < 3))


#: Below this many, negative allergen components are listed one per line.
ALLERGEN_COLLAPSE_MIN = 5


def _collapse_negative_allergens(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str | None]:
    """One line for every allergen component below the positivity cut-off.

    An ALEX² panel is ~300 components, nearly all "<0.1 kUA/L"; printed one
    per line they were ~47k tokens that said one thing. Anything flagged,
    disputed or unjudged keeps its own line, and every collapsed component is
    still named (codes verbatim), so nothing is silently dropped.
    """
    negatives = [
        card for card in rows
        if card.get("panel_id") == "allergy"
        and _severity(card) == 3
        # "negative" only: total IgE shares the panel and reads "normal".
        and str((card.get("verdict") or {}).get("interpretation")) == "negative"
    ]
    if len(negatives) < ALLERGEN_COLLAPSE_MIN:
        return rows, None
    kept = [card for card in rows if card not in negatives]
    dates = sorted({str(card.get("latest_date") or "")[:10] for card in negatives} - {""})
    span = "-"
    if dates:
        span = dates[0] if len(dates) == 1 else f"{dates[0]} - {dates[-1]}"
    names = ", ".join(str(card["name"]) for card in negatives)
    return kept, "- " + t_plural("ai.allergen_negatives", len(negatives), dates=span, names=names)


def _value_text(card: dict[str, object]) -> str:
    """The measurement itself, machine-readable where it is a number.

    The comparator travels with the number.  A result the laboratory reported
    as "<0.1" is a limit of detection, not a reading of 0.1 -- printing the
    bare number tells the assistant a measurement was made that never was, and
    an allergen at "<0.1 kUA/L" then reads as a small positive instead of an
    absence.
    """
    if card.get("value_numeric") is not None:
        unit = str(card.get("unit") or "").strip()
        # A catalog card carries the comparator only inside its formatted
        # value ("<0,1"); reading the absent `comparator` key exported 290
        # limit-of-detection results as measured numbers.
        comparator = str(card.get("comparator") or "").strip() or _COMPARATOR.match(
            str(card.get("value_text") or "")
        ).group(1)
        # A lab value keeps six figures (1.035 against 1.010-1.030); a
        # device's daily mean is not that precise ("6.81667 hours").
        figures = 4 if card.get("is_device") else 6
        return f"{comparator}{_num(card['value_numeric'], figures)} {unit}".strip()
    return str(card.get("latest_text") or card.get("value_text") or "-")


_COMPARATOR = re.compile(r"\s*([<>≤≥]=?|)")


def _interval(
    low: object, high: object, unit: object = None,
    low_inclusive: object = True, high_inclusive: object = True,
) -> str:
    """An interval in the same number convention as the value beside it.

    Not ``reference.range_text``: that one localises through
    ``format_number_localized``, so a Ukrainian line read "LDL 4.42 mmol/L,
    reference <= 1,4" -- the measurement with a dot and its own threshold with
    a comma, one line apart.  A reader shrugs; a parser reads two different
    kinds of number and one of them wrong.  The comparator follows the band's
    inclusivity: class 0 is "< 0.35", never "≤ 0.35".
    """
    suffix = f" {unit}" if unit else ""
    if low is not None and high is not None:
        return f"{_num(low)}-{_num(high)}{suffix}"
    if high is not None:
        return f"{'≤' if high_inclusive is not False else '<'} {_num(high)}{suffix}"
    if low is not None:
        return f"{'≥' if low_inclusive is not False else '>'} {_num(low)}{suffix}"
    return ""


# --- the compact notation, shared with the chat's tools ------------------------
#
# A row is ``- name: value unit @date mark (interval S3; ≠ S1 <3 ✓; lab 30-400)``
# and the legend explains it once.  The long form ("reference ≤ 33 U/L per
# American College of Gastroenterology ... VERIFIED: a person checked this one
# against the original page") repeated the same five phrases on six hundred
# rows: 56k tokens for the default English export, 38k after (measured 2026-11-09).

_SOURCE = re.compile("\x01(.*?)\x02")


def _fold(name: str) -> str:
    """One body, one alias: the library spells МОЗ's «здоров’я» with both
    apostrophes, which listed the ministry twice."""
    return name.replace("'", "’")


class Sources:
    """Publishers as short aliases, stable across every output of a request.

    The alias is the publisher's place in the sorted list of all publishers,
    so S4 means the same body in the chat's profile and in its fourth tool
    result.  Text carries placeholders until ``render`` swaps them and writes
    a legend of the aliases actually used.
    """

    def __init__(self, connection, *, by_use: bool = False):
        self.by_source = _publishers(connection)
        names = sorted({_fold(name) for name in self.by_source.values() if name})
        self.alias = {name: f"S{index}" for index, name in enumerate(names, 1)}
        # A one-shot text (the export) numbers them in order of first use
        # instead, so its legend reads S1..S12 rather than S4..S211.
        if by_use:
            self.alias = {}
        self.by_use = by_use

    def ref(self, source_id: object, fallback: object = "") -> str:
        name = self.by_source.get(str(source_id or "")) or str(fallback or "")
        return f"\x01{_fold(name)}\x02" if name else ""

    def render(self, text: str, *, label: str = "Sources", at: str | None = None) -> str:
        """Aliases in, legend written: appended, or in place of ``at``."""
        used: dict[str, str] = {}

        def swap(match: re.Match) -> str:
            name = match.group(1)
            if self.by_use and name not in self.alias:
                self.alias[name] = f"S{len(self.alias) + 1}"
            alias = self.alias.get(name)
            if alias is None:
                return name
            used[alias] = name
            return alias

        text = _SOURCE.sub(swap, text)
        ordered = sorted(used.items(), key=lambda item: int(item[0][1:]))
        legend = f"{label}: " + "; ".join(f"{alias} {name}" for alias, name in ordered) if used else ""
        if at is not None:
            return text.replace(at, legend, 1)
        return f"{text}\n{legend}" if legend else text


def _band(verdict: dict, prefix: str = "") -> str:
    text = _interval(
        verdict.get(f"{prefix}low"), verdict.get(f"{prefix}high"), None,
        verdict.get(f"{prefix}low_inclusive", True), verdict.get(f"{prefix}high_inclusive", True),
    )
    return re.sub(r"^([<>≤≥]) ", r"\1", text)


def _code(interpretation: object) -> str:
    return {"no_universal_target": "no-target", "": "unjudged"}.get(str(interpretation or ""), str(interpretation))


#: The verdict as a symbol.  Within range and negative print nothing, which is
#: most rows; the legend explains the rest.
_MARKS = {
    "critical_high": "↑↑", "critical_low": "↓↓", "critical": "!!",
    "high": "↑", "elevated": "↑", "low": "↓", "deficient": "↓",
    "borderline_high": "(↑)", "borderline_low": "(↓)", "borderline": "(±)",
    "positive": "+", "abnormal": "!", "unjudged": "?", "indeterminate": "?",
    "no_universal_target": "?",
}


def _mark(interpretation: object) -> str:
    return _MARKS.get(str(interpretation or "unjudged"), "")


def _position(interpretation: object) -> str:
    """Another body's verdict, where "within range" has to be said out loud."""
    return _mark(interpretation) or "✓"


def judged(
    verdict: dict, sources: Sources, *, code: Callable[[object], str] = _code,
    lab: str = "lab", no_target: str = "no-target",
) -> str:
    """``(<1.8 S3; ≠ S1 <3 normal; lab 30-400)``: the interval the verdict was
    judged against and who published it, then every disagreement.

    The printed number is cited to the body that published it: the non-HDL 3.8
    cut-point is EAS/EFLM's even when an ESC goal matched the value.  A
    disagreement is spelled out, never resolved: averaging two authorities is
    the one thing this record must not do.
    """
    parts = []
    has_target = verdict.get("target_low") is not None or verdict.get("target_high") is not None
    interval = _band(verdict, "target_" if has_target else "")
    source = verdict.get("target_source_id") if has_target else verdict.get("source_id")
    who = lab if verdict.get("authority") == "vendor" else sources.ref(source or verdict.get("source_id"))
    if interval:
        parts.append(f"{interval} {who}".strip())
    elif verdict.get("no_universal_target") and no_target:
        # With an interval printed, "lab" already says whose it is; the export
        # says once, in its legend, what a row with no interval means.
        parts.append(no_target)
    if verdict.get("authorities_disagree"):
        others = [
            f"{sources.ref(item.get('source_id'), item.get('publisher'))} {_band(item)} {code(item.get('interpretation'))}"
            for item in verdict.get("authority_positions") or []
            if item.get("source_id") != verdict.get("source_id")
        ]
        if others:
            parts.append("≠ " + ", ".join(" ".join(other.split()) for other in others))
    if verdict.get("conflicts_with_vendor"):
        parts.append(f"{lab} " + (_band({"low": verdict.get("vendor_low"), "high": verdict.get("vendor_high")}) or "-"))
    return f" ({'; '.join(parts)})" if parts else ""


#: Statuses that need no mark: a person checked it, or a device measured it.
_CHECKED = {"verified", "corrected", "device_measurement"}


def _result_line(card: dict[str, object], sources: Sources, *, dated: str = "") -> str:
    """``- LDL cholesterol: 2.7 mmol/L @2026-11-05 ↑ (<1.8 S3; ≠ S1 <3 ✓)``

    ``dated`` is the date every row shares (a document's), left out of each.
    Only the unchecked rows are marked: most of this record has been checked
    against its source page, and saying so on every line cost more than any
    other phrase in the export.
    """
    verdict = card.get("verdict") or {}
    day = str(card.get("latest_date") or "-")[:10]
    mark = _mark(verdict.get("interpretation"))
    text = (
        f"- {card['name']}: {_value_text(card)}{'' if day == dated else ' @' + day}"
        f"{' ' + mark if mark else ''}"
        + judged(verdict, sources, code=_position, lab=t("ai.mark_lab"), no_target="")
    )
    if str(card.get("verification_status") or "") not in _CHECKED:
        text += " " + t("ai.mark_unverified")
    # A same-measurement twin is one line read from documents and devices.
    if card.get("sources_text"):
        text += f"; {card['sources_text']}"
    return text


def _history_line(card: dict[str, object], limit: int = MAX_HISTORY_POINTS) -> str | None:
    """One analyte's whole history in one line, evenly thinned.

    The first and the last reading always survive: a trend that drops its own
    starting point is not a trend, and the oldest value is frequently the one
    that makes the newest one meaningful.
    """
    series = [point for point in (card.get("series") or []) if point.get("value") is not None]
    if len(series) < 2:
        return None
    kept, dropped = series, 0
    if len(series) > limit:
        step = (len(series) - 1) / (limit - 1)
        indexes = sorted({round(index * step) for index in range(limit)})
        indexes = sorted(set(indexes) | {0, len(series) - 1})
        kept = [series[index] for index in indexes]
        dropped = len(series) - len(kept)
    path = ", ".join(f"{point['date']} {_num(point['value'])}" for point in kept)
    unit = str(card.get("unit") or "").strip()
    # The span is only news when points were dropped: otherwise every date
    # and the extremes are already on the line.
    thinned = ""
    if dropped:
        values = [float(point["value"]) for point in series]
        thinned = " " + t(
            "ai.history_thinned", count=dropped, total=len(series),
            low=_num(min(values)), high=_num(max(values)),
        )
    return f"- {card['name']}{f' ({unit})' if unit else ''}: {path}{thinned}"


def _device_block(summary: dict[str, object]) -> list[str]:
    """A core wearable metric, month by month, with the compression stated."""
    unit = str(summary["unit"] or "")
    aggregation = str(summary["aggregation"])
    lines = [
        "",
        f"#### {summary['name']} ({unit or t('ai.unit_none')})",
        t(
            "ai.device_meta",
            aggregation=t(f"ai.aggregation_{aggregation}")
            if f"ai.aggregation_{aggregation}" in _KNOWN_AGGREGATIONS
            else aggregation,
            days=summary["day_count"],
            first=summary["first_day"],
            rows=summary["row_count"],
            vendors=", ".join(str(item) for item in summary["vendors"]),
        ),
    ]
    recent, _ = _capped(summary["recent_days"], MAX_DEVICE_RECENT_DAYS)
    if recent:
        # Newest first, so the first entry is the latest reading; only it
        # carries the year (a watch value six figures deep is noise).
        lines.append(
            t("ai.device_recent")
            + " "
            + ", ".join(
                f"{day['day'] if index == 0 else str(day['day'])[5:]} {_num(day['value'], 4)}"
                for index, day in enumerate(recent)
            )
        )
    months, _ = _capped(summary["months"], MAX_DEVICE_MONTHS)
    if months:
        lines.append(f"{t('ai.device_monthly')} {_buckets(months)}")
    if summary["years"]:
        lines.append(f"{t('ai.device_yearly')} {_buckets(summary['years'])}")
    return lines


def _buckets(rows: Sequence[dict[str, object]]) -> str:
    return "; ".join(
        f"{bucket['period']} {_num(bucket['mean'], 4)} "
        f"({_num(bucket['min'], 4)}-{_num(bucket['max'], 4)}, {bucket['days']}d)"
        for bucket in rows
    )


_KNOWN_AGGREGATIONS = {"ai.aggregation_sum", "ai.aggregation_average", "ai.aggregation_latest"}


def _device_one_liner(summary: dict[str, object]) -> str:
    """A secondary metric: recent level, full span, row count.  One line."""
    unit = str(summary["unit"] or "")
    window = summary["months"] or summary["years"]
    if window:
        days = sum(int(bucket["days"]) for bucket in window)
        mean = sum(float(bucket["mean"]) * int(bucket["days"]) for bucket in window) / max(days, 1)
        low = min(float(bucket["min"]) for bucket in window)
        high = max(float(bucket["max"]) for bucket in window)
        recent = t(
            "ai.device_window", mean=_num(mean, 4), low=_num(low, 4), high=_num(high, 4), days=days
        )
    else:
        recent = ""
    return "; ".join(
        part
        for part in (
            f"- {summary['name']}: {_num(summary['latest_value'], 4)} {unit}".rstrip()
            + f" @{summary['latest_day']}",
            recent,
            t("ai.device_span", days=summary["day_count"], first=summary["first_day"]),
        )
        if part
    )


def _publishers(connection) -> dict[str, str]:
    return {
        str(row["id"]): str(row["publisher"] or "")
        for row in connection.execute("SELECT id, publisher FROM reference_sets")
    }


def _about_lines(
    patient,
    counts: dict[str, object],
    include: Collection[str],
    catalog: Sequence[dict[str, object]],
) -> list[str]:
    """The "About me" section, shared by the whole-record and excerpt prompts."""
    out = [f"## {t('ai.about_heading')}", ""]
    if patient is not None:
        if "identity" in include:
            out.append(t("ai.about_name", name=patient["display_name"]))
            out.append(t("ai.about_dob", date=patient["date_of_birth"] or "-"))
        age = counts.get("patient_age")
        out.append(t("ai.about_age", age=age if age is not None else "-"))
        out.append(t("ai.about_sex", sex=t(f"sex.{str(patient['sex_at_birth'] or 'unknown').casefold()}")))
        if patient["blood_type"]:
            out.append(t("ai.about_blood_type", value=patient["blood_type"]))
        # Dosing is calculated from these (a weight-based dose, an eGFR-adjusted one), so they travel.
        if patient["weight_kg"] is not None:
            out.append("- " + t("ai.profile_weight", value=_num(patient["weight_kg"])))
        if patient["height_cm"] is not None:
            out.append("- " + t("ai.profile_height", value=_num(patient["height_cm"])))
    if "identity" not in include:
        out.append(t("ai.identity_withheld"))
    lab_cards = [card for card in catalog if not card.get("is_device")]
    out += [
        t(
            "ai.about_record",
            observations=counts.get("observations", 0),
            analytes=len(lab_cards),
            devices=len(catalog) - len(lab_cards),
            documents=counts.get("documents", 0),
            latest=str(counts.get("latest_result") or "-")[:10],
            device_latest=counts.get("latest_device") or "-",
        ),
        "",
    ]
    return out


def _finding_line(item: dict[str, object]) -> str:
    """``- 2026-08-09 Cardiology consultation (Veselka): E78.2 Mixed hyperlipidaemia; ...``

    The conclusion in the language it was written in.  Reading only the English
    summary sent 42 of 43 conclusions as a bare title: the diagnoses a
    cardiologist wrote never reached the assistant.
    """
    summary = " ".join(str(item.get("summary_text") or item.get("summary_en") or "").split())
    return (
        f"- {item.get('finding_date') or '-'} {item.get('title')} ({item.get('vendor')})"
        + (f": {summary}" if summary else "")
    )


def _add_attention(out, omissions, attention, sources) -> set[str]:
    """Attention first: everything flagged, most alarming first.  Returns the
    ids listed, which the results section then leaves out."""
    flagged, flagged_over = _capped(attention, MAX_ATTENTION)
    out += [f"## {t('ai.attention_heading')}", ""]
    if flagged:
        out.append(t("ai.attention_body", count=len(attention)))
        out.append("")
        out += [_result_line(card, sources) for card in flagged]
        if flagged_over:
            omissions.append(t("ai.omitted_attention", count=flagged_over))
    else:
        out.append(t("ai.attention_none"))
    out.append("")
    return {str(card["id"]) for card in flagged}


def _add_results(out, catalog, sources, listed: Collection[str] = ()) -> None:
    """Every other current value, grouped the way the pages group them."""
    out += [f"## {t('ai.results_heading')}", "", t("ai.results_body"), ""]
    by_area: dict[str, list[dict[str, object]]] = {}
    for card in catalog:
        if card.get("is_device") or str(card["id"]) in listed:
            # Devices have their own section; a flagged result was printed
            # in full under "Needs attention" and is not printed twice.
            continue
        by_area.setdefault(str(card.get("area_name") or t("ai.area_other")), []).append(card)
    # Body systems with something flagged come first, the most alarming first,
    # so a reader -- or a model with a short attention span -- meets them
    # before three hundred negative allergens.
    for area_name in sorted(by_area, key=lambda name: (_area_rank(by_area[name]), name)):
        out += ["", f"### {area_name}", ""]
        rows = sorted(by_area[area_name], key=lambda card: (_severity(card), str(card["name"])))
        rows, collapsed = _collapse_negative_allergens(rows)
        out += [_result_line(card, sources) for card in rows]
        if collapsed:
            out.append(collapsed)
    out.append("")


def _add_history(out, omissions, catalog) -> None:
    lines = [line for line in (_history_line(card) for card in catalog) if line]
    kept, over = _capped(lines, MAX_HISTORY_METRICS)
    out += [f"## {t('ai.history_heading')}", ""]
    out.append(t("ai.history_body") if kept else t("ai.history_none"))
    out += ["", *kept, ""]
    if over:
        omissions.append(t("ai.omitted_history", count=over))


def _add_devices(out, connection, owner_user_id) -> None:
    """Wearables."""
    from . import app as web

    # A scale's weight and a cuff's pressure are already results above, their
    # daily values in the history; listing them here again would be twice.
    summaries = [
        item for item in web.device_history(connection, owner_user_id)
        if str(item["metric_key"]) not in SAME_DEVICE_KEYS
    ]
    out += [f"## {t('ai.devices_heading')}", ""]
    if not summaries:
        out += [t("ai.devices_none"), ""]
        return
    raw_rows = sum(int(item["row_count"]) for item in summaries)
    out.append(
        t(
            "ai.devices_body",
            metrics=len(summaries),
            rows=raw_rows,
            first=min(str(item["first_day"]) for item in summaries),
            last=max(str(item["latest_day"]) for item in summaries),
        )
    )
    by_key = {str(item["metric_key"]): item for item in summaries}
    core = [by_key[key] for key in CORE_METRIC_KEYS if key in by_key]
    for summary in core:
        out += _device_block(summary)
    rest = [item for item in summaries if item["metric_key"] not in set(CORE_METRIC_KEYS)]
    if rest:
        out += ["", f"#### {t('ai.devices_other_heading')}", "", t("ai.devices_other_body"), ""]
        out += [_device_one_liner(summary) for summary in rest]
    out.append("")


def _finding_lines(findings: Sequence[dict[str, object]]) -> tuple[list[object], int]:
    """Distinct lines only: one consultation is often extracted three times."""
    return _capped(list(dict.fromkeys(_finding_line(item) for item in findings)), MAX_FINDINGS)


def _add_findings(out, omissions, findings) -> None:
    """Narrative findings."""
    kept, over = _finding_lines(findings)
    out += [f"## {t('ai.findings_heading')}", ""]
    if not kept:
        out += [t("ai.findings_none"), ""]
        return
    out += [t("ai.findings_body"), "", *kept]
    out.append("")
    if over:
        omissions.append(t("ai.omitted_findings", count=over))


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _factor_line(factor: dict[str, object]) -> str:
    """``- Warfarin 5 mg [Medicine, Current]: anticoagulant; 5 mg, daily; from 2026-01-05; atrial fibrillation``

    Empty parts and their separators are left out.  The kind and status are
    always printed: they say whether a medicine is being taken, not just
    prescribed, which decides whether a result can be explained by it.
    """
    head = f"- {factor['name']}"
    if factor["strength"]:
        head += f" {factor['strength']}"
    head += f" [{t('med.kind.' + str(factor['kind']))}, {t('med.status.' + str(factor['effective_status']))}]"
    dosing = factors.regimen_text(factor, get_locale())
    started, ended = factor["started_on"], factor["ended_on"]
    when = ""
    if started and ended:
        when = t("ai.factors_range", start=started, end=ended)
    elif started:
        when = t("ai.factors_from", date=started)
    elif ended:
        when = t("ai.factors_range", start="-", end=ended)
    if when and factor["dates_approximate"]:
        when += f" ({_lower_first(t('med.approx'))})"
    parts = [str(part) for part in (factor["substance"], dosing, when, factor["reason"]) if part]
    return head + (": " + "; ".join(parts) if parts else "")


def _add_factors(out, connection, owner_user_id: str) -> None:
    """Medicines, supplements and other entries, with the results each can change."""
    entries = factors.listing(connection, owner_user_id, today=date.today())
    out += [f"## {t('ai.factors_heading')}", ""]
    if not entries:
        out += [t("ai.factors_none"), ""]
        return
    for entry in entries:
        out.append(_factor_line(entry))
        out += [f"  - {t('med.dir.' + str(effect['direction']))} {effect['label']}" for effect in entry["effects"]]
    out.append("")


def _add_guidance(out, omissions, catalog, guidance) -> None:
    """Guidance and citations."""
    out += [f"## {t('ai.guidance_heading')}", "", t("ai.guidance_body"), ""]
    seen: set[str] = set()
    written = 0
    for card in catalog:
        key = str(card["id"]).removeprefix("device:")
        entry = guidance.get(key)
        if not entry or key in seen:
            continue
        seen.add(key)
        if written >= MAX_GUIDANCE:
            continue
        written += 1
        detail = " ".join(
            str(entry.get(field) or "").strip()
            for field in ("short_description", "why_it_matters")
        ).strip()
        cadence = entry.get("retest_interval_months")
        retest = t("ai.retest", months=cadence) if cadence else ""
        out.append(f"- {card['name']}: {detail} {retest}".rstrip())
    skipped = len(seen) - written
    if skipped > 0:
        omissions.append(t("ai.omitted_guidance", count=skipped))
    out.append("")


def _add_documents(out, omissions, documents) -> None:
    kept, over = _capped(documents, MAX_DOCUMENTS)
    out += [f"## {t('ai.documents_heading')}", "", t("ai.documents_body"), ""]
    for row in kept:
        out.append(
            f"- {row.get('report_date') or '-'} - {row.get('title')} "
            f"({row.get('vendor')}, {t_plural('ai.documents_values', int(row.get('observation_count') or 0))})"
        )
    if over:
        omissions.append(t("ai.omitted_documents", count=over))
    out.append("")


def build_prompt(
    connection,
    owner_user_id: str,
    *,
    include: Collection[str],
    focus: str | None = None,
    patient=None,
    counts: dict[str, object] | None = None,
    catalog: Sequence[dict[str, object]] = (),
    attention: Sequence[dict[str, object]] = (),
    findings: Sequence[dict[str, object]] = (),
    guidance: dict[str, dict[str, object]] | None = None,
    documents: Sequence[dict[str, object]] = (),
) -> str:
    """Assemble the whole prompt.  Every argument is data the page already built."""
    include = set(include) & SECTION_KEYS
    counts = counts or {}
    guidance = guidance or {}
    sources = Sources(connection, by_use=True)
    omissions: list[str] = []
    out = _head(t("ai.doc_title"), t("ai.task_body", language=t(f"lang.name_{get_locale()}")))
    if focus:
        out += [t("ai.focus", subject=focus), ""]

    # --- who ----------------------------------------------------------------
    out += _about_lines(patient, counts, include, catalog)

    listed = _add_attention(out, omissions, attention, sources)
    _add_results(out, catalog, sources, listed)
    if "history" in include:
        _add_history(out, omissions, catalog)
    if "devices" in include:
        _add_devices(out, connection, owner_user_id)
    if "findings" in include:
        _add_findings(out, omissions, findings)
    if "guidance" in include:
        _add_guidance(out, omissions, catalog, guidance)
    if "documents" in include:
        _add_documents(out, omissions, documents)
    _add_factors(out, connection, owner_user_id)

    # --- what is not here ---------------------------------------------------
    out += [f"## {t('ai.gaps_heading')}", "", t("ai.gaps_body"), ""]
    for key, _default in SECTIONS:
        if key not in include:
            out.append(f"- {t(f'ai.section_{key}')} - {t('ai.gaps_excluded')}")
    return _finish(out, omissions, sources)


#: Where the publisher legend goes once the body knows which ones it cited.
_LEGEND_SLOT = "\x00sources\x00"


def _head(title: str, task: str) -> list[str]:
    """Title, the request, and how to read what follows."""
    return [
        f"# {title}", "",
        f"## {t('ai.task_heading')}", "", task, "",
        f"## {t('ai.legend_heading')}", "", t("ai.legend_body"), _LEGEND_SLOT, "",
    ]


def _finish(out: list[str], omissions: list[str], sources: Sources) -> str:
    out += [f"- {note}" for note in omissions]
    out += ["", t("ai.footer")]
    text = sources.render("\n".join(out), label=t("ai.sources_label"), at=_LEGEND_SLOT)
    return re.sub(r"\n{3,}", "\n\n", text) + "\n"


# --- the page-scoped excerpt -------------------------------------------------


def _observation_card(row: dict[str, object]) -> dict[str, object]:
    """A document's observation row, reshaped so `_result_line` can print it."""
    return {
        "name": row.get("name"),
        "unit": row.get("unit_text"),
        "value_numeric": row.get("value_numeric"),
        "comparator": row.get("comparator"),
        "latest_text": row.get("display_value"),
        "latest_date": str(row.get("observed_at") or "")[:10] or None,
        "verdict": row.get("verdict"),
        "verification_status": row.get("verification_status"),
    }


def _rank_related(cards: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Most alarming first, then most recent, using the marker the page shows.

    Only supporting context is ordered this way, because it is also the part
    that gets cut: a urinalysis panel is sixty rows of "Not detected" around
    two that are not, and a cap applied in storage order would keep the sixty.
    The subject itself keeps the order its own page uses -- re-sorting a lipid
    panel by severity would hand the assistant its numbers shuffled.
    """
    ordered = sorted(cards, key=lambda card: str(card.get("latest_date") or ""), reverse=True)
    ordered.sort(key=_severity)
    return ordered


def _subject_card_block(
    card: dict[str, object],
    sources: Sources,
    entry: dict[str, object] | None,
    *,
    with_guidance: bool,
) -> list[str]:
    """One in-scope measurement: verdict line, plain-language why, full trend.

    The trend always travels -- a value read without its own history is the
    thing this application exists to stop, and it costs one line.  The
    explanation of what the test is for costs five hundred characters, so it
    travels only where there is one subject to explain.
    """
    lines = [_result_line(card, sources)]
    if with_guidance and entry:
        detail = " ".join(
            str(entry.get(field) or "").strip()
            for field in ("short_description", "why_it_matters")
        ).strip()
        cadence = entry.get("retest_interval_months")
        if cadence:
            detail = f"{detail} {t('ai.retest', months=cadence)}".strip()
        if detail:
            lines.append(f"  - {detail}")
    history = _history_line(card, limit=MAX_SUBJECT_POINTS if with_guidance else MAX_HISTORY_POINTS)
    if history:
        lines.append("  " + history)
    return lines


def _add_subject(out, omissions, subject, sources, guidance, include) -> None:
    document = subject.get("document")
    if document:
        out += [
            t_plural(
                "ai.document_meta",
                len(subject.get("observations") or ()),
                title=document.get("title_text") or document.get("title"),
                vendor=document.get("vendor"),
                date=document.get("report_date") or "-",
            ),
            "",
        ]
        kept, over = _capped(list(subject.get("observations") or ()), MAX_SUBJECT_OBSERVATIONS)
        # The document's date is in the line above; a row repeats only a different one.
        dated = str(document.get("report_date") or "")[:10]
        out += [_result_line(_observation_card(row), sources, dated=dated) for row in kept]
        if over:
            omissions.append(t_plural("ai.omitted_observations", over))
    # One measurement gets its explanation; sixty do not.  A panel that
    # repeated "what this test is for" under every member would spend most of
    # the excerpt restating the library, which is exactly the noise this scope
    # exists to remove.
    detailed = bool(subject.get("detailed"))
    cards, cards_over = _capped(list(subject.get("cards") or ()), MAX_SUBJECT_CARDS)
    for card in cards:
        key = str(card["id"]).removeprefix("device:")
        out += _subject_card_block(
            card, sources, guidance.get(key), with_guidance=detailed and "guidance" in include
        )
    if cards_over:
        omissions.append(t_plural("ai.omitted_subject", cards_over))
    for summary in subject.get("device_summaries") or ():
        out += _device_block(summary)
    _add_subject_findings(out, omissions, subject, include)
    out.append("")


def _add_subject_findings(out, omissions, subject, include) -> None:
    # The section switches govern the excerpt too.  Turning "Conclusions
    # written in my reports" off for the whole record and then having them
    # reappear the moment the reader narrows to one page is the kind of
    # surprise this file exists to avoid — and the switch is honoured for
    # identity three screens down, so the inconsistency is the defect.
    findings = list(subject.get("findings") or ()) if "findings" in include else []
    if findings:
        kept, over = _finding_lines(findings)
        out.extend(["", f"### {t('ai.findings_heading')}", "", t("ai.findings_body"), "", *kept])
        if over:
            omissions.append(t("ai.omitted_findings", count=over))


def _add_related(out, omissions, subject, related, sources, label) -> None:
    """The rest of its panel, for context."""
    if related:
        kept, over = _capped(_rank_related(related), MAX_RELATED)
        out += [
            f"## {t('ai.related_heading', panel=subject.get('related_label') or label)}",
            "",
            t("ai.related_body"),
            "",
        ]
        out += [_result_line(card, sources) for card in kept]
        if over:
            omissions.append(t_plural("ai.omitted_related", over))
        out.append("")


def _add_elsewhere(out, omissions, subject, related, attention, sources) -> None:
    """Flagged elsewhere, one line each."""
    scoped_ids = {
        str(card["id"])
        for group in (subject.get("cards") or (), related)
        for card in group
    }
    scoped_ids |= {f"device:{item['metric_key']}" for item in subject.get("device_summaries") or ()}
    elsewhere = [card for card in attention if str(card["id"]) not in scoped_ids]
    out += [f"## {t('ai.elsewhere_heading')}", ""]
    if elsewhere:
        kept, over = _capped(elsewhere, MAX_ELSEWHERE)
        out += [t_plural("ai.elsewhere_body", len(elsewhere)), ""]
        out += [_result_line(card, sources) for card in kept]
        if over:
            omissions.append(t("ai.omitted_attention", count=over))
    else:
        out.append(t("ai.elsewhere_none"))
    out.append("")


def build_subject_prompt(
    connection,
    owner_user_id: str,
    *,
    subject: dict[str, object],
    include: Collection[str],
    patient=None,
    counts: dict[str, object] | None = None,
    catalog: Sequence[dict[str, object]] = (),
    attention: Sequence[dict[str, object]] = (),
    guidance: dict[str, dict[str, object]] | None = None,
) -> str:
    """The excerpt: one page's subject in full, plus the context to read it.

    The whole-record prompt exists because a single value without its record is
    how a confident wrong answer gets written.  This is the other failure mode
    fixed: a hundred and forty thousand characters of everything is how the one
    value the person is actually asking about drowns.  So the subject travels
    complete — every retained reading, its intervals, its plain-language
    explanation — the rest of its panel travels as context, everything flagged
    elsewhere travels as one line each, and the excerpt says what it is and how
    to get the rest.
    """
    include = set(include) & SECTION_KEYS
    counts = counts or {}
    guidance = guidance or {}
    sources = Sources(connection, by_use=True)
    label = str(subject["label"])
    omissions: list[str] = []
    out = _head(
        t("ai.excerpt_title"),
        t("ai.task_body_scoped", subject=label, language=t(f"lang.name_{get_locale()}")),
    )
    out += _about_lines(patient, counts, include, catalog)

    # --- the subject, complete ---------------------------------------------
    out += [f"## {t('ai.subject_heading', subject=label)}", ""]
    _add_subject(out, omissions, subject, sources, guidance, include)

    related = list(subject.get("related_cards") or ())
    _add_related(out, omissions, subject, related, sources, label)
    _add_elsewhere(out, omissions, subject, related, attention, sources)

    _add_factors(out, connection, owner_user_id)

    # --- what an excerpt is not --------------------------------------------
    lab_cards = [card for card in catalog if not card.get("is_device")]
    out += [
        f"## {t('ai.gaps_heading')}",
        "",
        t(
            "ai.excerpt_note",
            subject=label,
            analytes=len(lab_cards),
            documents=counts.get("documents", 0),
            latest=str(counts.get("latest_result") or "-")[:10],
        ),
        "",
        t("ai.gaps_body"),
        "",
    ]
    # Every switched-off section is named, never silently absent.
    for key in ("findings", "guidance", "identity"):
        if key not in include:
            out.append(f"- {t('ai.section_' + key)} - {t('ai.gaps_excluded')}")
    return _finish(out, omissions, sources)
