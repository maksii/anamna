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
from collections.abc import Collection, Sequence

from ..devices.catalog import CORE_METRIC_KEYS
from ..devices.queries import device_history_summary
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
        return f"{comparator}{_num(card['value_numeric'])} {unit}".strip()
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


def _publisher(
    verdict: dict[str, object], publishers: dict[str, str], *, source_key: str = "source_id"
) -> str:
    """The body that published the governing interval, not the paper's title.

    A verdict's ``source_name`` is the full citation -- publisher, then "Fasting
    is not routinely required for determination of a lipid profile: clinical
    and laboratory implications including flagging at desirable concentration
    cut-points -- joint EAS/EFLM consensus statement" -- which is right on a
    page showing one result and is three hundred wasted characters on one line
    of five hundred.  The publisher identifies the authority just as well, and
    the full citation stays one click away in the application itself.
    """
    source_id = str(verdict.get(source_key) or verdict.get("source_id") or "")
    if source_id in publishers:
        return publishers[source_id]
    for item in verdict.get("authority_positions") or []:
        if item.get("source_id") == source_id and item.get("publisher"):
            return str(item["publisher"])
    return str(verdict.get("source_name") or "")


def _disagreeing_positions(verdict: dict[str, object], unit: object) -> str:
    """The other authorities' positions, only when the verdict records a disagreement."""
    if not verdict.get("authorities_disagree"):
        return ""
    return "; ".join(
        f"{item.get('publisher') or item.get('source_name')}: "
        f"{item.get('label')} "
        f"{_interval(item.get('low'), item.get('high'), unit, item.get('low_inclusive', True), item.get('high_inclusive', True))}".strip()
        for item in verdict.get("authority_positions") or []
        if item.get("source_id") != verdict.get("source_id")
    )


def _reference_text(card: dict[str, object], publishers: dict[str, str]) -> str:
    """Where the interval came from, and who disagrees about it.

    A verdict that averaged two disagreeing authorities is the one thing this
    record must never produce, so a disagreement is spelled out rather than
    resolved -- but only the positions that differ from the one already stated.
    """
    verdict = card.get("verdict") or {}
    parts: list[str] = []
    unit = card.get("unit")
    has_target = verdict.get("target_low") is not None or verdict.get("target_high") is not None
    prefix = "target_" if has_target else ""
    interval = _interval(
        verdict.get(f"{prefix}low"), verdict.get(f"{prefix}high"), unit,
        verdict.get(f"{prefix}low_inclusive", True), verdict.get(f"{prefix}high_inclusive", True),
    )
    # The printed number is cited to the body that published it: the non-HDL
    # 3.8 cut-point is EAS/EFLM's even when an ESC goal matched the value.
    publisher = _publisher(
        verdict, publishers, source_key="target_source_id" if has_target else "source_id"
    )
    if interval and publisher:
        parts.append(t("ai.field_reference_source", interval=interval, source=publisher))
    elif interval:
        parts.append(
            t("ai.field_reference_vendor", interval=interval)
            if verdict.get("authority") == "vendor"
            else t("ai.field_reference", interval=interval)
        )
    if verdict.get("no_universal_target"):
        parts.append(t("ai.no_universal_target"))
    others = _disagreeing_positions(verdict, unit)
    if others:
        parts.append(t("ai.authorities_disagree", positions=others))
    if verdict.get("conflicts_with_vendor"):
        parts.append(
            t(
                "ai.vendor_conflict",
                interval=_interval(verdict.get("vendor_low"), verdict.get("vendor_high"), unit)
                or "-",
            )
        )
    return "; ".join(part for part in parts if part)


def _result_line(
    card: dict[str, object], publishers: dict[str, str], *, with_area: bool = False
) -> str:
    verdict = card.get("verdict") or {}
    bits = [f"{_marker(card)}{card['name']}: {_value_text(card)} ({card['latest_date'] or '-'})"]
    label = str(verdict.get("label") or "").strip()
    if label:
        bits.append(label)
    reference = _reference_text(card, publishers)
    if reference:
        bits.append(reference)
    if with_area and card.get("area_name"):
        bits.append(str(card["area_name"]))
    # A same-measurement twin is one line read from documents and devices.
    if card.get("sources_text"):
        bits.append(str(card["sources_text"]))
    # Almost every value in a record like this is provisional, so the legend
    # declares that once and only the exceptions are marked.  Repeating
    # "provisional, not yet checked against the source page" on five hundred
    # lines spends twenty-six thousand characters saying nothing new.
    if str(card.get("verification_status")) in {"verified", "corrected"}:
        bits.append(t("ai.verified"))
    return "- " + " - ".join(bits)


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
    values = [float(point["value"]) for point in series]
    path = ", ".join(f"{point['date']} {_num(point['value'])}" for point in kept)
    unit = str(card.get("unit") or "").strip()
    span = t(
        "ai.history_span",
        count=len(series),
        first=series[0]["date"],
        last=series[-1]["date"],
        low=_num(min(values)),
        high=_num(max(values)),
    )
    thinned = f" {t('ai.history_thinned', count=dropped)}" if dropped else ""
    return f"- {card['name']}{f' ({unit})' if unit else ''}: {path} [{span}]{thinned}"


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
            latest=_num(summary["latest_value"]),
            latest_day=summary["latest_day"],
            days=summary["day_count"],
            first=summary["first_day"],
            rows=summary["row_count"],
            vendors=", ".join(str(item) for item in summary["vendors"]),
        ),
    ]
    recent, _ = _capped(summary["recent_days"], MAX_DEVICE_RECENT_DAYS)
    if recent:
        lines.append(
            t("ai.device_recent", days=len(recent))
            + " "
            + ", ".join(f"{day['day']} {_num(day['value'])}" for day in recent)
        )
    months, _ = _capped(summary["months"], MAX_DEVICE_MONTHS)
    if months:
        lines.append(
            t("ai.device_monthly")
            + " "
            + "; ".join(
                f"{bucket['period']} {_num(bucket['mean'], 4)} "
                f"({_num(bucket['min'], 4)}-{_num(bucket['max'], 4)}, {bucket['days']}d)"
                for bucket in months
            )
        )
    if summary["years"]:
        lines.append(
            t("ai.device_yearly")
            + " "
            + "; ".join(
                f"{bucket['period']} {_num(bucket['mean'], 4)} "
                f"({_num(bucket['min'], 4)}-{_num(bucket['max'], 4)}, {bucket['days']}d)"
                for bucket in summary["years"]
            )
        )
    return lines


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
    return "- " + " - ".join(
        part
        for part in (
            f"{summary['name']}: {_num(summary['latest_value'])} {unit}".strip()
            + f" ({summary['latest_day']})",
            recent,
            t("ai.device_span", days=summary["day_count"], first=summary["first_day"],
              rows=summary["row_count"]),
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
    summary = str(item.get("summary_en") or "").strip().replace("\n", " ")
    return (
        f"- {item.get('finding_date') or '-'} - {item.get('title')}"
        + (f" - {summary}" if summary else "")
        + f" ({item.get('vendor')})"
    )


def _add_attention(out, omissions, attention, publishers) -> None:
    """Attention first: everything flagged, most alarming first."""
    flagged, flagged_over = _capped(attention, MAX_ATTENTION)
    out += [f"## {t('ai.attention_heading')}", ""]
    if flagged:
        out.append(t("ai.attention_body", count=len(attention)))
        out.append("")
        out += [_result_line(card, publishers, with_area=True) for card in flagged]
        if flagged_over:
            omissions.append(t("ai.omitted_attention", count=flagged_over))
    else:
        out.append(t("ai.attention_none"))
    out.append("")


def _add_results(out, catalog, publishers) -> None:
    """Every current value, grouped the way the pages group them."""
    out += [f"## {t('ai.results_heading')}", "", t("ai.results_body"), ""]
    by_area: dict[str, list[dict[str, object]]] = {}
    for card in catalog:
        if card.get("is_device"):
            continue  # devices have their own section, with their own history
        by_area.setdefault(str(card.get("area_name") or t("ai.area_other")), []).append(card)
    # Body systems with something flagged come first, the most alarming first,
    # so a reader -- or a model with a short attention span -- meets them
    # before three hundred negative allergens.
    for area_name in sorted(by_area, key=lambda name: (_area_rank(by_area[name]), name)):
        out += ["", f"### {area_name}", ""]
        rows = sorted(by_area[area_name], key=lambda card: (_severity(card), str(card["name"])))
        rows, collapsed = _collapse_negative_allergens(rows)
        out += [_result_line(card, publishers) for card in rows]
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
    # A scale's weight and a cuff's pressure are already results above, their
    # daily values in the history; listing them here again would be twice.
    summaries = [
        item for item in device_history_summary(connection, owner_user_id)
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


def _add_findings(out, omissions, findings) -> None:
    """Narrative findings."""
    kept, over = _capped(findings, MAX_FINDINGS)
    out += [f"## {t('ai.findings_heading')}", ""]
    if not kept:
        out += [t("ai.findings_none"), ""]
        return
    out += [t("ai.findings_body"), ""]
    out += [_finding_line(item) for item in kept]
    out.append("")
    if over:
        omissions.append(t("ai.omitted_findings", count=over))


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
    publishers = _publishers(connection)
    omissions: list[str] = []
    out: list[str] = [f"# {t('ai.doc_title')}", ""]

    # --- what the assistant is being asked to do ---------------------------
    out += [
        f"## {t('ai.task_heading')}",
        "",
        t("ai.task_body", language=t(f"lang.name_{get_locale()}")),
        "",
        f"## {t('ai.legend_heading')}",
        "",
        t("ai.legend_body"),
        "",
    ]
    if focus:
        out += [t("ai.focus", subject=focus), ""]

    # --- who ----------------------------------------------------------------
    out += _about_lines(patient, counts, include, catalog)

    _add_attention(out, omissions, attention, publishers)
    _add_results(out, catalog, publishers)
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

    # --- what is not here ---------------------------------------------------
    out += [f"## {t('ai.gaps_heading')}", "", t("ai.gaps_body"), ""]
    for key, _default in SECTIONS:
        if key not in include:
            out.append(f"- {t(f'ai.section_{key}')} - {t('ai.gaps_excluded')}")
    for note in omissions:
        out.append(f"- {note}")
    out += ["", t("ai.footer")]
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


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
    publishers: dict[str, str],
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
    lines = [_result_line(card, publishers)]
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


def _add_subject(out, omissions, subject, publishers, guidance, include) -> None:
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
        out += [_result_line(_observation_card(row), publishers) for row in kept]
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
            card, publishers, guidance.get(key), with_guidance=detailed and "guidance" in include
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
        kept, over = _capped(findings, MAX_FINDINGS)
        out.extend(["", f"### {t('ai.findings_heading')}", "", t("ai.findings_body"), ""])
        out.extend(_finding_line(item) for item in kept)
        if over:
            omissions.append(t("ai.omitted_findings", count=over))


def _add_related(out, omissions, subject, related, publishers, label) -> None:
    """The rest of its panel, for context."""
    if related:
        kept, over = _capped(_rank_related(related), MAX_RELATED)
        out += [
            f"## {t('ai.related_heading', panel=subject.get('related_label') or label)}",
            "",
            t("ai.related_body"),
            "",
        ]
        out += [_result_line(card, publishers) for card in kept]
        if over:
            omissions.append(t_plural("ai.omitted_related", over))
        out.append("")


def _add_elsewhere(out, omissions, subject, related, attention, publishers) -> None:
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
        out += [_result_line(card, publishers, with_area=True) for card in kept]
        if over:
            omissions.append(t("ai.omitted_attention", count=over))
    else:
        out.append(t("ai.elsewhere_none"))
    out.append("")


def build_subject_prompt(
    connection,
    _owner_user_id: str,
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
    publishers = _publishers(connection)
    label = str(subject["label"])
    omissions: list[str] = []
    out: list[str] = [f"# {t('ai.excerpt_title')}", ""]

    out += [
        f"## {t('ai.task_heading')}",
        "",
        t("ai.task_body_scoped", subject=label, language=t(f"lang.name_{get_locale()}")),
        "",
        f"## {t('ai.legend_heading')}",
        "",
        t("ai.legend_body"),
        "",
    ]
    out += _about_lines(patient, counts, include, catalog)

    # --- the subject, complete ---------------------------------------------
    out += [f"## {t('ai.subject_heading', subject=label)}", ""]
    _add_subject(out, omissions, subject, publishers, guidance, include)

    related = list(subject.get("related_cards") or ())
    _add_related(out, omissions, subject, related, publishers, label)
    _add_elsewhere(out, omissions, subject, related, attention, publishers)

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
    for note in omissions:
        out.append(f"- {note}")
    out += ["", t("ai.footer")]
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"
