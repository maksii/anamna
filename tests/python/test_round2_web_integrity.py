"""Synthetic cache and evidence identity regressions from the second audit."""
from anamna.db import connect
from anamna.derived import refresh_derived_observations
from anamna.web import app as web
from test_linked_metrics import _build, _document, _observation


def test_in_place_observation_edit_invalidates_memo_without_timestamp_change(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "synthetic", "Synthetic lab", "laboratory", "2025-01-01")
    _observation(settings, owner, "value", "synthetic", "hemoglobin", 140, "g/L", "2025-01-01")
    with connect(settings) as db:
        old_created = db.execute("SELECT created_at FROM observations WHERE id='value'").fetchone()[0]
        first = web._memoised(db, owner, "round2-value", lambda: db.execute("SELECT value_numeric FROM observations WHERE id='value'").fetchone()[0])
    with connect(settings) as other_process:
        other_process.execute("UPDATE observations SET value_numeric=150 WHERE id='value'")
    with connect(settings) as db:
        second = web._memoised(db, owner, "round2-value", lambda: db.execute("SELECT value_numeric FROM observations WHERE id='value'").fetchone()[0])
        assert db.execute("SELECT created_at FROM observations WHERE id='value'").fetchone()[0] == old_created
    assert (first, second) == (140, 150)


def test_equal_numbers_with_distinct_units_or_limits_remain_distinct_evidence(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "synthetic", "Synthetic lab", "laboratory", "2025-01-01")
    for oid, unit in (("grams", "g/L"), ("decilitre", "g/dL"), ("limit", "g/L")):
        _observation(settings, owner, oid, "synthetic", "hemoglobin", 14, unit, "2025-01-01")
    with connect(settings) as db:
        db.execute("UPDATE observations SET comparator='<' WHERE id='limit'")
        rows = web._deduped_observation_rows(db, owner, "hemoglobin")
    assert {row["id"] for row in rows} == {"grams", "decilitre", "limit"}
    assert all(row["evidence_count"] == 1 for row in rows)


def test_owner_deletion_cascades_observation_revision_without_trigger_orphan(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _document(settings, owner, "synthetic", "Synthetic lab", "laboratory", "2025-01-01")
    _observation(settings, owner, "value", "synthetic", "hemoglobin", 140, "g/L", "2025-01-01")
    with connect(settings) as db:
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert db.execute("SELECT COUNT(*) FROM observation_revisions").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_clinical_calculation_displays_original_inputs_and_source_links(tmp_path):
    settings, owner, client = _build(tmp_path)
    _document(settings, owner, "synthetic", "Synthetic lab", "laboratory", "2025-01-01")
    _observation(settings, owner, "protein", "synthetic", "total-protein", 7, "g/dL", "2025-01-01")
    _observation(settings, owner, "albumin", "synthetic", "albumin", 40, "g/L", "2025-01-01")
    with connect(settings) as db:
        db.execute("UPDATE observations SET verification_status='verified'")
        refresh_derived_observations(db)
        result = web._linked_observation_rows(db, owner, "globulin-calculated")[0]
        inputs = result["calculation_inputs"]
    assert {(item["input_id"], item["input_value"], item["input_unit"]) for item in inputs} == {
        ("protein", 7, "g/dL"), ("albumin", 40, "g/L"),
    }
    page = client.get("/metrics/globulin-calculated")
    assert page.status_code == 200
    assert '/documents/synthetic#observation-protein' in page.text
    assert '/documents/synthetic#observation-albumin' in page.text


def test_incompatible_reported_unit_is_preserved_and_explained(tmp_path):
    settings, owner, client = _build(tmp_path)
    _document(settings, owner, "synthetic", "Synthetic lab", "laboratory", "2025-01-01")
    _observation(settings, owner, "pct", "synthetic", "plateletcrit", 0.2, "10^9/L", "2025-01-01")
    for lang, phrase in (("en", "The reported unit cannot be converted"), ("uk", "Зазначену одиницю неможливо перерахувати")):
        client.cookies.set("anamna_lang", lang)
        page = client.get("/metrics/plateletcrit")
        assert page.status_code == 200 and phrase in page.text
    with connect(settings) as db:
        raw = db.execute("SELECT value_numeric, unit_raw FROM observations WHERE id='pct'").fetchone()
        assert tuple(raw) == (0.2, "10^9/L")
