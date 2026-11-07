from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

from pypdf import PdfReader

from anamna.db import connect, utc_now
from anamna.ingest.pipeline import ensure_concept
from anamna.web.health_export import choose_aggregation, prepare_metric, short_date

from test_web_panels import build, seed_device_days


def _row(day: date, value: float) -> dict[str, object]:
    return {
        "date": day.isoformat(),
        "date_text": day.isoformat(),
        "numeric": value,
        "value_text": str(value),
        "unit": "mmol/L",
        "reference": "< 5.0 mmol/L",
        "provider": "Test Lab",
        "document_title": "Laboratory report",
        "status": "Checked",
    }


def test_auto_aggregation_keeps_spread_and_sample_count_visible():
    start = date(2025, 1, 1)
    rows = [_row(start + timedelta(days=index), float(index + 1)) for index in range(75)]
    assert choose_aggregation(rows, "auto") == "month"
    prepared = prepare_metric(
        {"id": "total-cholesterol", "name": "Total cholesterol"},
        rows,
        "auto",
        datefmt=lambda value: str(value),
        numfmt=lambda value, _decimals=None: f"{float(value):g}",
        labels={
            "aggregated_reference": "Min {minimum} · max {maximum} · n={count}",
            "average": "Average",
            "unknown_date": "Unknown",
            "auto": "Automatic",
            "exact": "Exact",
            "month": "Monthly averages",
            "quarter": "Quarterly averages",
            "year": "Yearly averages",
        },
    )
    assert prepared["point_count"] == 75
    assert prepared["displayed_count"] == 3
    assert sum(row["sample_count"] for row in prepared["rows"]) == 75
    assert all("Min " in row["reference"] and "n=" in row["reference"] for row in prepared["rows"])


def test_export_period_is_compact_and_never_duplicates_one_date():
    labels = {
        "aggregated_reference": "Min {minimum} · max {maximum} · n={count}",
        "average": "Average",
        "unknown_date": "Unknown",
        "auto": "Automatic",
        "exact": "Exact",
        "month": "Monthly averages",
        "quarter": "Quarterly averages",
        "year": "Yearly averages",
    }
    one = prepare_metric(
        {"id": "creatinine", "name": "Creatinine"}, [_row(date(2025, 8, 8), 88)], "exact",
        datefmt=short_date, numfmt=lambda value, _decimals=None: f"{float(value):g}", labels=labels,
    )
    span = prepare_metric(
        {"id": "creatinine", "name": "Creatinine"},
        [_row(date(2022, 12, 22), 80), _row(date(2025, 8, 8), 88)], "exact",
        datefmt=short_date, numfmt=lambda value, _decimals=None: f"{float(value):g}", labels=labels,
    )
    assert one["period_text"] == "08.08.2025"
    assert span["period_text"] == "22.12.2022 - 08.08.2025"


def test_lipid_export_defaults_to_recorded_panel_members_and_can_be_rebuilt(tmp_path):
    _, _, client = build(tmp_path)
    panel = client.get("/panels/lipids")
    assert panel.status_code == 200
    assert 'href="/panels/lipids/export"' in panel.text

    default = client.get("/panels/lipids/export")
    assert default.status_code == 200
    assert 'value="ldl-cholesterol" checked' in default.text
    assert 'value="hdl-cholesterol" checked' in default.text
    assert "LDL cholesterol" in default.text
    assert "HDL cholesterol" in default.text

    rebuilt = client.get(
        "/panels/lipids/export",
        params=[("custom", "1"), ("metric", "ldl-cholesterol"), ("metric", "creatinine"), ("aggregation", "exact")],
    )
    assert rebuilt.status_code == 200
    assert 'value="hdl-cholesterol" checked' not in rebuilt.text
    assert 'value="creatinine" checked' in rebuilt.text
    assert "Every exact value" in rebuilt.text


def test_every_recorded_panel_and_metric_has_a_clean_export_entry(tmp_path):
    _, _, client = build(tmp_path)

    panel = client.get("/panels/kidney")
    assert panel.status_code == 200
    assert 'class="button secondary an-export-entry" href="/panels/kidney/export"' in panel.text
    panel_export = client.get("/panels/kidney/export")
    assert panel_export.status_code == 200
    assert 'value="creatinine" checked' in panel_export.text

    metric = client.get("/metrics/creatinine")
    assert metric.status_code == 200
    assert 'href="/metrics/creatinine/export"' in metric.text
    metric_export = client.get("/metrics/creatinine/export")
    assert metric_export.status_code == 200
    assert 'href="/metrics/creatinine"' in metric_export.text
    # One date format per locale: the record's own "13 Feb 2025", never a
    # second numeric spelling beside the date of birth.
    assert "13 Feb 2025" in metric_export.text
    assert "13.02.2025" not in metric_export.text
    assert "13 Feb 2025 – 13 Feb 2025" not in metric_export.text
    assert "Choose what leaves the record" not in metric_export.text
    assert "Automatic keeps exact results" not in metric_export.text
    assert "Value handling" not in metric_export.text
    assert ">Trust<" not in metric_export.text


def test_device_metric_can_be_exported_from_its_detail_page(tmp_path):
    settings, user_id, client = build(tmp_path)
    seed_device_days(settings, user_id, [("steps", "Steps")])

    metric = client.get("/devices/metrics/steps")
    assert metric.status_code == 200
    assert 'href="/devices/metrics/steps/export"' in metric.text
    export = client.get("/devices/metrics/steps/export")
    assert export.status_code == 200
    assert 'value="device:steps" checked' in export.text
    assert 'href="/devices/metrics/steps"' in export.text
    assert "01 Aug 2025" in export.text


def test_print_css_removes_application_chrome_and_duplicate_export_hero(tmp_path):
    _, _, client = build(tmp_path)
    css = client.get("/static/app.css").text
    print_rules = css[css.rindex("@media print") :]
    for selector in (".topbar", ".footer", ".skip-link", ".ai-opener", ".export-hero"):
        assert selector in print_rules


def test_total_cholesterol_export_and_downloaded_pdf_share_the_selection(tmp_path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        vendor_id = connection.execute("SELECT id FROM vendors WHERE canonical_name='Test Lab'").fetchone()[0]
        concept_id, _ = ensure_concept(connection, "Total cholesterol", vendor_id)
        patient_id = connection.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, vendor_reference_text,
                   vendor_reference_high, vendor_interpretation, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               VALUES ('obs-total-cholesterol', ?, ?, 'doc-1', 1, ?, 'Total cholesterol',
                       'numeric', 5.2, 'mmol/L', '2025-02-13', '< 5.0', 5.0, 'high',
                       'verified', 'test', 1.0, 'Total cholesterol 5.2', 'test', ?)""",
            (user_id, patient_id, concept_id, utc_now()),
        )

    metric = client.get("/metrics/total-cholesterol")
    assert metric.status_code == 200
    assert 'href="/metrics/total-cholesterol/export"' in metric.text
    page = client.get("/metrics/total-cholesterol/export")
    assert page.status_code == 200
    assert 'value="total-cholesterol" checked' in page.text

    response = client.get(
        "/exports/health-history.pdf",
        params=[("metric", "total-cholesterol"), ("metric", "ldl-cholesterol"), ("aggregation", "exact")],
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
    assert "Test Patient" in text
    assert "Total cholesterol" in text
    assert "LDL cholesterol" in text
    assert "5.2" in text
    assert "Trust" not in text
    assert "Value handling" not in text
    # A handed-over history carries the verdict and the interval it was judged
    # against, not only the laboratory's printed range.
    assert "Above range" in text
    assert "Laboratory range" in text
    # One date format: "13 Feb 2025" beside "14 Mar 1990", never "13.02.2025".
    assert "13 Feb 2025" in text and "13.02.2025" not in text
    assert "Above range" in page.text


def test_one_draw_printed_twice_is_one_export_row(tmp_path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        patient_id = connection.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
        concept_id, _ = ensure_concept(connection, "Twin marker", None)
        for index, value in enumerate((64.3, 58.0)):
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                       value_type, value_numeric, unit_raw, observed_at, verification_status,
                       extraction_method, confidence, evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-1', 1, ?, 'Twin marker', 'numeric', ?, '%', '2016-07-19',
                           'extracted', 'test', ?, 'fixture', 'test', ?)""",
                (f"twin-{index}", user_id, patient_id, concept_id, value, 0.9 - index * 0.1, utc_now()),
            )
    page = client.get(f"/metrics/{concept_id}/export")
    assert page.status_code == 200
    metric = page.context["export"]["metrics"][0]
    assert len(metric["rows"]) == 1
    assert metric["rows"][0]["value_text"] == "64.3"
    assert "58" in metric["rows"][0]["also_printed"]


def test_export_requires_a_selection_for_pdf(tmp_path):
    _, _, client = build(tmp_path)
    response = client.get("/exports/health-history.pdf")
    assert response.status_code == 400
    assert "Select a metric" in response.text
