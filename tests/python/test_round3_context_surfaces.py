"""A shared concept and unit do not establish a shared specimen or method."""
from __future__ import annotations

import pytest

from anamna.web import app as web
from anamna.i18n import activate_locale, reset_locale


ROW = {
    "id": "latest", "concept_id": "kidney-length", "canonical_name": "Kidney length",
    "category": "renal", "patient_id": "synthetic-patient", "document_id": "synthetic-report",
    "observed_at": "2025-03-01", "created_at": "2025-03-02", "confidence": .9,
    "value_numeric": 10., "value_text": None, "unit_raw": "mm", "preferred_unit": "mm",
    "unit_canonical": "mm", "comparator": None, "raw_name": "Kidney length",
    "specimen": None, "sample_condition": None, "note": None,
    "vendor": "Synthetic clinic", "verification_status": "extracted", "evidence_count": 1,
}


class Concepts:
    def execute(self, _sql):
        return [{"id": ROW["concept_id"], "canonical_name": ROW["canonical_name"], "preferred_unit": "mm"}]


@pytest.fixture(autouse=True)
def verdict(monkeypatch):
    monkeypatch.setattr(web, "_reading_verdict", lambda *args: ("mm", {"interpretation": "unjudged", "label": "Unjudged"}))


def _card(rows):
    return web._lab_card(None, str(rows[0]["concept_id"]), rows, {}, None, None, {})


@pytest.mark.parametrize("context,other", [
    ({"specimen": "right"}, {"specimen": "left"}),
    ({"specimen": "urine"}, {"specimen": "serum"}),
    ({"sample_condition": "fasting"}, {"sample_condition": "postprandial"}),
    ({"note": "synthetic isolate A"}, {"note": "synthetic isolate B"}),
    ({"concept_id": "estimated-glomerular-filtration-rate-reported", "raw_name": "eGFR (MDRD)"},
     {"concept_id": "estimated-glomerular-filtration-rate-reported", "raw_name": "eGFR (CKD-EPI 2009)"}),
])
def test_card_chart_and_correlation_keep_latest_source_context(monkeypatch, context, other):
    latest = {**ROW, **context}
    rows = [latest, {**ROW, **other, "id": "other", "observed_at": "2025-02-01", "value_numeric": 200.},
            {**latest, "id": "prior", "observed_at": "2025-01-01", "value_numeric": 5.}]
    card = _card(rows)
    assert card["count"] == 3  # All evidence remains available in history.
    assert [point["value"] for point in card["series"]] == [5., 10.]
    assert card["trend"] is not None
    for key in ("specimen", "sample_condition", "note"):
        if context.get(key):
            assert context[key] in card["context_note"]
    monkeypatch.setattr(web, "_chart_point", lambda row, *args, **kwargs: row)
    assert [row["id"] for row in web._chart_payload(rows, "mm")] == ["prior", "latest"]
    monkeypatch.setattr(web, "_linked_observation_rows", lambda *args: rows)
    connection = Concepts()
    connection.execute = lambda _sql: [{"id": latest["concept_id"], "canonical_name": latest["canonical_name"], "preferred_unit": "mm"}]
    series = web._correlation_lab_series(connection, "synthetic-owner")[latest["concept_id"]]["series"]
    assert series == [("2025-01-01", 5.), ("2025-03-01", 10.)]


def test_reported_equations_printed_on_same_report_are_not_one_result():
    rows = [{**ROW, "concept_id": "estimated-glomerular-filtration-rate-reported", "raw_name": "eGFR (MDRD)"},
            {**ROW, "id": "other", "concept_id": "estimated-glomerular-filtration-rate-reported", "raw_name": "eGFR (CKD-EPI 2009)"}]
    assert len(web._one_per_day(rows)) == 2


def test_censored_and_mismatched_values_never_enter_exact_series(monkeypatch):
    rows = [dict(ROW), {**ROW, "id": "censored", "observed_at": "2025-02-01", "comparator": "<"},
            {**ROW, "id": "mismatch", "observed_at": "2025-01-01", "unit_mismatch": True,
             "unit_raw": "U/mL", "preferred_unit": "U/mL", "unit_canonical": "U/mL"}]
    assert len(_card(rows)["series"]) == 1
    monkeypatch.setattr(web, "_chart_point", lambda row, *args, **kwargs: row)
    assert [row["id"] for row in web._chart_payload(rows, "mm")] == ["latest"]
    monkeypatch.setattr(web, "_linked_observation_rows", lambda *args: rows)
    assert web._correlation_lab_series(Concepts(), "synthetic-owner")[ROW["concept_id"]]["series"] == [("2025-03-01", 10.)]


def test_microbiology_remains_evidence_without_a_numeric_line(monkeypatch):
    rows = [{**ROW, "category": "microbiology"}]
    assert _card(rows)["series"] == []
    assert web._chart_payload(rows, "mm") == []
    monkeypatch.setattr(web, "_linked_observation_rows", lambda *args: rows)
    assert web._correlation_lab_series(Concepts(), "synthetic-owner") == {}


def test_censored_latest_side_does_not_select_an_older_opposite_side(monkeypatch):
    rows = [{**ROW, "specimen": "right", "comparator": "<"},
            {**ROW, "id": "opposite", "specimen": "left", "observed_at": "2025-02-01"}]
    assert _card(rows)["series"] == []
    assert web._chart_payload(rows, "mm") == []
    monkeypatch.setattr(web, "_linked_observation_rows", lambda *args: rows)
    assert web._correlation_lab_series(Concepts(), "synthetic-owner")[ROW["concept_id"]]["series"] == []


@pytest.mark.parametrize("source,english,ukrainian", [
    ("права", "right", "права"), ("ліва", "left", "ліва"),
    ("права грудна залоза", "Right breast", "Права молочна залоза"),
    ("ліва молочна залоза", "Left breast", "Ліва молочна залоза"),
])
def test_known_parser_sides_are_bilingual_without_reversing_source_prose(source, english, ukrainian):
    for locale, expected in (("en", english), ("uk", ukrainian)):
        token = activate_locale(locale)
        try:
            assert web._report_context({"specimen": source, "note": "original source prose"}) == expected + " · original source prose"
        finally:
            reset_locale(token)
