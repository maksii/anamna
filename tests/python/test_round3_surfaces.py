"""Exact source context must survive merging and patient-facing history."""
from __future__ import annotations

import pytest

from anamna.ingest.pipeline import _result_fingerprint
from anamna.web import app as web


ROW = {
    "id": "synthetic-result", "patient_id": "synthetic-patient",
    "document_id": "synthetic-report", "report_id": "synthetic-draw",
    "concept_id": "synthetic-concept", "value_numeric": 1.0000000000001,
    "value_text": None, "unit_canonical": "U/mL", "unit_raw": "U/mL",
    "preferred_unit": "U/mL",
    "observed_at": "2025-01-01T09:00:00", "comparator": None,
    "specimen": "synthetic specimen", "sample_condition": None, "note": None,
    "confidence": .9, "created_at": "2025-01-02",
}


@pytest.mark.parametrize("changes", [
    {"value_numeric": 1.0000000000002}, {"comparator": "<"},
    {"observed_at": "2025-01-01T10:00:00"}, {"specimen": "another specimen"},
    {"note": "another isolate"}, {"sample_condition": "fasting"},
    {"value_text": "a distinct qualifier"}, {"unit_raw": "IU/L"},
])
def test_duplicate_identity_preserves_exact_value_and_source_context(changes):
    assert _result_fingerprint(ROW) != _result_fingerprint({**ROW, **changes})


@pytest.mark.parametrize("changes", [
    {"report_id": "another draw"}, {"document_id": "another source", "report_id": None},
    {"specimen": "another specimen"}, {"note": "another isolate"},
    {"comparator": "<"}, {"observed_at": "2025-01-01T10:00:00"},
    {"is_device": True},
])
def test_same_day_never_proves_same_draw(changes):
    rows = web._one_per_day([dict(ROW), {**ROW, "id": "synthetic-second", **changes}])
    assert len(rows) == 2


def test_repeat_printings_in_same_report_keep_disagreement_count():
    rows = web._one_per_day([dict(ROW), {**ROW, "id": "synthetic-copy", "value_numeric": 2}])
    assert len(rows) == 1
    assert rows[0]["same_day_count"] == 2
