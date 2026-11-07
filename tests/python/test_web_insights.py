"""Insights, search ranking, pagination and formatting.

These are the audit's B5/B6/C1/C2/C11 items expressed as assertions: a default
search that shows laboratory results, counts that admit what they are hiding,
and numbers that arrive rounded rather than rounded in Jinja.
"""

from __future__ import annotations

from pathlib import Path

from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale
from anamna.web import app as web

from test_web_panels import build, catalog_for


def test_numbers_are_formatted_for_their_unit_and_locale():
    token = activate_locale("en")
    try:
        assert web.format_quantity(0.853957, "km") == "0.85"
        assert web.format_quantity(52.6706, "dBA") == "52.7"
        assert web.format_quantity(95.9524, "%") == "96"
        assert web.format_quantity(8.91667, "hours") == "8.9"
        assert web.format_quantity(2.07184, "count") == "2"
        assert web.format_quantity(68.457, "bpm") == "68"
        assert web.format_quantity(5.61, "mmol/L") == "5.61"
        assert web.format_count(5591981) == "5,591,981"
        assert web.format_count(58075) == "58,075"
        assert web.format_quantity(None, "kg") == "-"
    finally:
        reset_locale(token)
    token = activate_locale("uk")
    try:
        # Ukrainian groups with a non-breaking space and separates with a comma.
        assert web.format_count(58075) == "58 075"
        assert web.format_quantity(5.61, "mmol/L") == "5,61"
    finally:
        reset_locale(token)


def test_delta_keeps_a_decimal_a_reading_would_drop():
    token = activate_locale("en")
    try:
        trend = web._trend(69.4, 68.5, "bpm", "2026-01-01")
        assert trend["direction"] == "up"
        assert trend["delta_text"] == "0.9 bpm"
        assert trend["meaningful"] is True
        assert web._trend(68.5, 68.5, "bpm", "2026-01-01")["meaningful"] is False
    finally:
        reset_locale(token)


def test_default_search_leads_with_laboratory_results(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    cards = list(catalog_for(settings, user_id).values())
    assert cards, "fixture produced no cards"
    # Device aggregates never displace lab results in the default ordering.
    first_device = next((index for index, card in enumerate(cards) if card["is_device"]), len(cards))
    last_lab = max(index for index, card in enumerate(cards) if not card["is_device"])
    assert last_lab < first_device or first_device == len(cards)
    payload = client.get("/api/metrics/search?q=").json()
    assert {"html", "title", "count_text", "totals", "order"} <= set(payload)
    # Nothing typed: body-system sections, laboratory ones before devices.
    html = payload["html"]
    assert 'data-section="lab-' in html
    assert 'href="/metrics/ldl-cholesterol"' in html
    if 'data-section="device-' in html:
        assert html.index('data-section="lab-') < html.index('data-section="device-')


def test_pagination_counts_are_honest():
    page = web._pagination(total=295, offset=0, limit=40, base="/metrics?q=allergy")
    assert (page["total"], page["shown"], page["first"], page["last"]) == (295, 40, 1, 40)
    assert page["has_more"] is True
    assert page["next_url"] == "/metrics?q=allergy&offset=40"
    assert page["prev_url"] is None
    last = web._pagination(total=295, offset=280, limit=40, base="/documents")
    assert (last["shown"], last["has_more"], last["next_url"]) == (15, False, None)
    assert last["prev_url"] == "/documents?offset=240"


def test_representative_members_never_repeat_the_same_number(tmp_path: Path):
    cards = [
        {"id": "pulse", "value_text": "77", "unit": "bpm", "latest_date": "2026-01-01", "count": 3,
         "verdict": {"interpretation": "normal"}},
        {"id": "ecg", "value_text": "77", "unit": "bpm", "latest_date": "2026-01-01", "count": 3,
         "verdict": {"interpretation": "normal"}},
        {"id": "ldl", "value_text": "4.42", "unit": "mmol/L", "latest_date": "2025-02-13", "count": 2,
         "verdict": {"interpretation": "high"}},
    ]
    picked = web._representative(cards, 2)
    assert [card["id"] for card in picked] == ["ldl", "pulse"]


def test_insights_sections_are_data_driven(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as connection:
        panels = web._panel_cards(connection, user_id)
    gaps = [panel["id"] for panel in panels if not panel["present_count"]]
    assert "thyroid" in gaps and "lipids" not in gaps
    # /insights is retired; its sections are status filters on /metrics.
    moved = client.get("/insights", follow_redirects=False)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/metrics?status=attention"
    page = client.get("/metrics?status=attention").text
    assert 'data-chip="status:attention" data-tone="attention" aria-current="page"' in page
    assert "ldl-cholesterol" in page, "the abnormal LDL is the attention list"
    assert "/insights" not in client.get("/").text, "no page links the retired route"


def test_review_queue_carries_the_values_being_certified(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        observations = web._document_observations(connection, user_id, "doc-1")
    assert len(observations) == len(
        [row for row in observations if "verdict" in row and "display_value" in row]
    )
    assert observations, "the review queue must be able to show what it asks you to certify"
    assert all(row["display_value"] != "" for row in observations)


def test_documents_facets_are_labelled_not_spelled_out_of_the_enum(tmp_path: Path):
    _, _, client = build(tmp_path)
    body = client.get("/documents").text
    assert "radiology mri" not in body
    assert "Laboratory report" in body
