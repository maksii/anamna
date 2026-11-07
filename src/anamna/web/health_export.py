"""Selection, aggregation and PDF rendering for health-history exports.

The HTML preview and the downloadable document consume the same prepared
structure.  Keeping aggregation here prevents a long series from meaning one
thing on screen and another after download.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Callable


AUTO_AGGREGATE_AFTER = 60
AUTO_MAX_BUCKETS = 36
AGGREGATION_KEYS = frozenset({"auto", "exact", "month", "quarter", "year"})


def _date(value: object) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def short_date(value: object) -> str:
    """Export dates stay compact and unambiguous in every locale."""

    parsed = _date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else ""


def _bucket_key(day: date, mode: str) -> tuple[int, int]:
    if mode == "year":
        return day.year, 1
    if mode == "quarter":
        return day.year, ((day.month - 1) // 3) + 1
    return day.year, day.month


def _bucket_count(rows: list[dict[str, object]], mode: str) -> int:
    return len(
        {
            (_bucket_key(day, mode), str(row.get("unit") or ""))
            for row in rows
            if row.get("numeric") is not None and (day := _date(row.get("date"))) is not None
        }
    )


def choose_aggregation(rows: list[dict[str, object]], requested: str) -> str:
    """Resolve ``auto`` to the finest useful bucket size.

    The limit is based on buckets, not only elapsed time: a sparse 15-year
    laboratory history can remain monthly while a dense wearable-like series
    over two years becomes quarterly.
    """

    requested = requested if requested in AGGREGATION_KEYS else "auto"
    if requested != "auto":
        return requested
    numeric = [row for row in rows if row.get("numeric") is not None and _date(row.get("date"))]
    if len(numeric) <= AUTO_AGGREGATE_AFTER:
        return "exact"
    for mode in ("month", "quarter", "year"):
        if _bucket_count(numeric, mode) <= AUTO_MAX_BUCKETS:
            return mode
    return "year"


def _period_text(days: list[date], datefmt: Callable[[str | None], str]) -> str:
    start, end = min(days), max(days)
    if start == end:
        return datefmt(start.isoformat())
    return f"{datefmt(start.isoformat())} - {datefmt(end.isoformat())}"


def _exact_row(row: dict[str, object]) -> dict[str, object]:
    return {**row, "is_aggregate": False, "period_text": row.get("date_text") or ""}


def _aggregate_rows(
    rows: list[dict[str, object]],
    mode: str,
    datefmt: Callable[[str | None], str],
    numfmt: Callable[[float | int | None, int | None], str],
    labels: dict[str, str],
) -> list[dict[str, object]]:
    """One averaged row per bucket and unit; rows without a number or date stay exact."""
    groups: dict[tuple[tuple[int, int], str], list[dict[str, object]]] = defaultdict(list)
    exact: list[dict[str, object]] = []
    for row in rows:
        day = _date(row.get("date"))
        if row.get("numeric") is None or day is None:
            exact.append(_exact_row(row))
            continue
        groups[(_bucket_key(day, mode), str(row.get("unit") or ""))].append(row)

    shown: list[dict[str, object]] = []
    for bucket_rows in groups.values():
        values = [float(row["numeric"]) for row in bucket_rows]
        clean_days = [day for day in (_date(row["date"]) for row in bucket_rows) if day is not None]
        providers = list(dict.fromkeys(str(row.get("provider") or "") for row in bucket_rows if row.get("provider")))
        documents = list(dict.fromkeys(str(row.get("document_title") or "") for row in bucket_rows if row.get("document_title")))
        average = sum(values) / len(values)
        shown.append(
            {
                "date": max(clean_days).isoformat(),
                "period_text": _period_text(clean_days, datefmt),
                "value_text": numfmt(average, None),
                "numeric": average,
                "unit": bucket_rows[0].get("unit") or "",
                "reference": labels["aggregated_reference"].format(
                    minimum=numfmt(min(values), None),
                    maximum=numfmt(max(values), None),
                    count=len(values),
                ),
                "provider": ", ".join(providers),
                "document_title": ", ".join(documents),
                "status": labels["average"],
                "sample_count": len(values),
                "is_aggregate": True,
            }
        )
    shown.extend(exact)
    shown.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    return shown


def prepare_metric(
    metric: dict[str, object],
    rows: list[dict[str, object]],
    requested: str,
    *,
    datefmt: Callable[[str | None], str],
    numfmt: Callable[[float | int | None, int | None], str],
    labels: dict[str, str],
) -> dict[str, object]:
    """Return one metric with exact or safely summarized history rows."""

    rows = sorted(rows, key=lambda row: str(row.get("date") or ""), reverse=True)
    chosen = choose_aggregation(rows, requested)
    if chosen == "exact":
        shown = [_exact_row(row) for row in rows]
    else:
        shown = _aggregate_rows(rows, chosen, datefmt, numfmt, labels)

    dated = [day for row in rows if (day := _date(row.get("date"))) is not None]
    latest = rows[0] if rows else None
    return {
        **metric,
        "rows": shown,
        "point_count": len(rows),
        "displayed_count": len(shown),
        "start_text": datefmt(min(dated).isoformat()) if dated else labels["unknown_date"],
        "end_text": datefmt(max(dated).isoformat()) if dated else labels["unknown_date"],
        "period_text": _period_text(dated, datefmt) if dated else labels["unknown_date"],
        "latest": latest,
        "aggregation": chosen,
        "aggregation_label": labels[chosen],
        "was_aggregated": chosen != "exact",
    }


def _font_paths() -> tuple[Path | None, Path | None]:
    candidates = (
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    )
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            return regular, bold
    return None, None


_COMPARISON_KEYS = ("interval", "reference", "also_printed")


def _pdf_paragraph(paragraph_class, value: object, style):
    text = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return paragraph_class(text, style)


def _latest_text(latest: dict[str, object], labels: dict[str, str]) -> str:
    text = f"{labels['latest']}: {latest.get('value_text', '')} {latest.get('unit', '')}"
    return f"{text} · {latest['verdict']}" if latest.get("verdict") else text


def _source_text(row: dict[str, object], labels: dict[str, str]) -> str:
    source = row.get("provider") or labels["unknown_source"]
    return f"{source} - {row['document_title']}" if row.get("document_title") else str(source)


def _register_export_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular, bold = _font_paths()
    if not (regular and bold):
        return "Helvetica", "Helvetica-Bold"
    font_name, bold_name = "AnamnaExport", "AnamnaExport-Bold"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(regular)))
        pdfmetrics.registerFont(TTFont(bold_name, str(bold)))
    return font_name, bold_name


def _comparison_cell(row: dict[str, object], paragraph, small_style, verdict_style, labels: dict[str, str]):
    """The verdict, the interval it was judged against, then the lab's own
    range -- the three facts a reader of a handed-over history needs."""
    lines = [paragraph(row["verdict"], verdict_style)] if row.get("verdict") else []
    lines += [paragraph(row[key], small_style) for key in _COMPARISON_KEYS if row.get(key)]
    return lines or paragraph(labels["not_available"], small_style)


def _metric_story(metric: dict[str, object], add_gap: bool, paragraph, styles: tuple,
                  labels: dict[str, str], bold_name: str) -> list:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, LongTable, Paragraph, Spacer, Table, TableStyle

    heading_style, body_style, small_style, verdict_style = styles
    navy = colors.HexColor("#132A3A")
    line = colors.HexColor("#D8E1E5")
    story = []
    latest = metric.get("latest") or {}
    summary = Table(
        [[
            paragraph(_latest_text(latest, labels), body_style),
            paragraph(f"{labels['period']}: {metric.get('period_text')}", small_style),
        ]],
        colWidths=[90 * mm, 145 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F8F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, line),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]),
    )
    story.append(KeepTogether([Paragraph(str(metric.get("name") or ""), heading_style), summary, Spacer(1, 3 * mm)]))
    table_rows = [[
        paragraph(labels["column_date"], small_style),
        paragraph(labels["column_result"], small_style),
        paragraph(labels["column_comparison"], small_style),
        paragraph(labels["column_source"], small_style),
    ]]
    for row in metric.get("rows") or []:
        source = _source_text(row, labels)
        table_rows.append([
            paragraph(row.get("period_text"), body_style),
            paragraph(f"{row.get('value_text', '')} {row.get('unit', '')}", body_style),
            _comparison_cell(row, paragraph, small_style, verdict_style, labels),
            paragraph(source, small_style),
        ])
    table = LongTable(
        table_rows,
        colWidths=[45 * mm, 45 * mm, 66 * mm, 86 * mm],
        repeatRows=1,
        hAlign="LEFT",
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_name),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFB")]),
            ("GRID", (0, 0), (-1, -1), 0.35, line),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]),
    )
    story.append(table)
    if add_gap:
        story.append(Spacer(1, 7 * mm))
    return story


def render_pdf(export: dict[str, object], labels: dict[str, str]) -> bytes:
    """Render an A4 landscape clinical-history handoff with repeating headers."""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font_name, bold_name = _register_export_fonts()

    navy = colors.HexColor("#132A3A")
    teal = colors.HexColor("#197A68")
    pale = colors.HexColor("#EAF4F1")
    line = colors.HexColor("#D8E1E5")
    muted = colors.HexColor("#60717A")
    ink = colors.HexColor("#16252D")

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=15 * mm,
        title=str(labels["title"]),
        author="Anamna",
        subject=str(labels["subtitle"]),
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle", parent=styles["Title"], fontName=bold_name, fontSize=22,
        leading=26, textColor=navy, alignment=TA_LEFT, spaceAfter=5,
    )
    subtitle_style = ParagraphStyle(
        "ExportSubtitle", parent=styles["BodyText"], fontName=font_name, fontSize=9.5,
        leading=14, textColor=muted, spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "MetricHeading", parent=styles["Heading2"], fontName=bold_name, fontSize=14,
        leading=18, textColor=navy, spaceBefore=3, spaceAfter=5,
    )
    body_style = ParagraphStyle(
        "ExportBody", parent=styles["BodyText"], fontName=font_name, fontSize=8.3,
        leading=11, textColor=ink,
    )
    small_style = ParagraphStyle(
        "ExportSmall", parent=body_style, fontSize=7.2, leading=9.4, textColor=muted,
    )
    def paragraph(value: object, style=body_style) -> Paragraph:
        return _pdf_paragraph(Paragraph, value, style)

    verdict_style = ParagraphStyle("ExportVerdict", parent=body_style, fontName=bold_name)

    metrics = list(export.get("metrics") or [])
    story = [
        Paragraph(str(labels["title"]), title_style),
        Paragraph(str(labels["subtitle"]), subtitle_style),
        Table(
            [
                [paragraph(labels["patient"], small_style), paragraph(export.get("patient_name"), body_style),
                 paragraph(labels["date_of_birth"], small_style), paragraph(export.get("date_of_birth_text"), body_style)],
                [paragraph(labels["created"], small_style), paragraph(export.get("created_text"), body_style),
                 paragraph(labels["included"], small_style), paragraph(export.get("selection_text"), body_style)],
            ],
            colWidths=[28 * mm, 72 * mm, 30 * mm, 105 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), pale),
                ("BOX", (0, 0), (-1, -1), 0.6, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, line),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Spacer(1, 8 * mm),
    ]

    for metric_index, metric in enumerate(metrics):
        story += _metric_story(
            metric, metric_index < len(metrics) - 1, paragraph,
            (heading_style, body_style, small_style, verdict_style), labels, bold_name,
        )

    def page_frame(canvas, doc) -> None:
        canvas.saveState()
        width, _height = landscape(A4)
        canvas.setStrokeColor(teal)
        canvas.setLineWidth(1.1)
        canvas.line(15 * mm, 12 * mm, width - 15 * mm, 12 * mm)
        canvas.setFont(font_name, 7.2)
        canvas.setFillColor(muted)
        canvas.drawRightString(width - 15 * mm, 7.5 * mm, f"{labels['page']} {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return buffer.getvalue()
