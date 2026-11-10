"""Ingest pipeline audit: censored lab flags, urine glucose, bracket-code
fallback, re-read of AI-suggested rows, the ingest write lock, undated reports,
file names kept out of the log, and migration 058.

Every test builds its own temporary record; nothing touches data/ or sources/.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from pathlib import Path

from anamna import db
from anamna.config import Settings
from anamna.db import connect
from anamna.ingest import concepts, pipeline
from anamna.ingest.concepts import concept_for_alias
from anamna.ingest.parsers import ParsedObservation

from test_ingest_reread_pairing import empty_document, parsed, rows, stored
from test_rescan import build, classification, rescanner  # noqa: F401  (fixture)


def lab_row(value, low=None, high=None, comparator=None, low_inclusive=True, high_inclusive=True):
    return ParsedObservation(
        raw_name="Тестовий показник", value_numeric=value, value_text=None, comparator=comparator,
        unit_raw="мг/л", reference_text=None, reference_low=low, reference_high=high,
        page_number=1, evidence_text="Тестовий показник", confidence=0.95,
        reference_low_inclusive=low_inclusive, reference_high_inclusive=high_inclusive,
    )


# --- 1. A censored result is placed only where its side is certain ------------


def test_a_greater_than_result_below_a_range_is_not_flagged_low():
    # «>60» against 90-120: the true value may be 95, which is inside.
    assert pipeline.interpretation(lab_row(60.0, 90.0, 120.0, comparator=">")) is None


def test_a_greater_than_result_above_a_small_range_is_not_flagged_low():
    assert pipeline.interpretation(lab_row(1.0, 3.0, 10.0, comparator=">")) is None


def test_a_less_than_result_against_a_range_that_starts_above_zero_is_not_within_range():
    # «<0.5» against 0.4-4: the true value may be 0.45, below the range.
    assert pipeline.interpretation(lab_row(0.5, 0.4, 4.0, comparator="<")) is None


def test_a_less_than_result_against_an_upper_only_range_is_not_flagged_high():
    # «<60» against «до 50»: the true value may be 55, which is inside.
    assert pipeline.interpretation(lab_row(60.0, None, 50.0, comparator="<")) is None


def test_a_certain_less_than_result_below_the_lower_bound_is_low():
    assert pipeline.interpretation(lab_row(0.3, 0.4, 4.0, comparator="<")) == "low"


def test_a_certain_greater_than_result_above_the_upper_bound_is_high():
    assert pipeline.interpretation(lab_row(130.0, 90.0, 120.0, comparator=">")) == "high"


def test_a_less_than_result_inside_a_range_starting_at_zero_is_within_range():
    assert pipeline.interpretation(lab_row(0.5, 0.0, 4.0, comparator="<")) == "within_vendor_range"


def test_an_uncensored_result_is_judged_as_before():
    assert pipeline.interpretation(lab_row(2.0, 3.0, 10.0)) == "low"
    assert pipeline.interpretation(lab_row(5.0, 3.0, 10.0)) == "within_vendor_range"
    assert pipeline.interpretation(lab_row(11.0, 3.0, 10.0)) == "high"
    # A strict bound excludes the value equal to it, as it always has.
    assert pipeline.interpretation(lab_row(10.0, 3.0, 10.0, high_inclusive=False)) == "high"


# --- 2. Urine glucose is a mixed-type concept ---------------------------------


def test_a_numeric_glucose_in_urinalysis_is_urine_glucose():
    found = concept_for_alias("Глюкоза", "numeric", category="urinalysis", specimen="urinalysis")
    assert found["name"] == "Urine glucose"


def test_a_text_glucose_in_urinalysis_is_still_urine_glucose():
    found = concept_for_alias("Глюкоза", "text", category="urinalysis", specimen="urinalysis")
    assert found["name"] == "Urine glucose"


def test_a_glucose_without_a_specimen_is_still_blood_glucose():
    assert concept_for_alias("Глюкоза", "numeric")["name"] == "Blood glucose"


# --- 3. The bracketed code cannot decide a label that names its specimen --------


def test_a_creatinine_in_24_hour_urine_is_not_serum_creatinine():
    assert concept_for_alias("Креатинін в добовій сечі (creatinine)") is None


def test_a_urine_leukocyte_count_is_not_the_blood_wbc():
    assert concept_for_alias("Лейкоцити в сечі (WBC)") is None


def test_a_urine_glucose_with_a_code_is_not_blood_glucose():
    assert concept_for_alias("Глюкоза в сечі (glucose)") is None


def test_a_direct_bilirubin_is_not_blocked_by_its_own_word():
    direct = concepts._BY_NAME["Direct bilirubin"]
    assert not concepts._fallback_blocked("Білірубін прямий", direct)
    assert concepts._fallback_blocked("Білірубін прямий", concepts._BY_NAME["Alanine aminotransferase"])


def test_cbc_and_liver_rows_with_codes_still_resolve():
    assert concept_for_alias("Аланінамінотрансфераза (АЛТ)")["name"] == "Alanine aminotransferase"
    assert concept_for_alias("ALT (ALT)")["name"] == "Alanine aminotransferase"
    assert concept_for_alias("Гемоглобін (HGB)")["name"] == "Hemoglobin"


# --- 4. A re-read keeps rows a person added from an AI suggestion ---------------


def _mark_ai(settings, raw_name: str, method: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET extraction_method=? WHERE document_id='doc-1' AND raw_name=?",
            (method, raw_name),
        )
        connection.commit()


def test_a_reread_keeps_an_ai_suggested_entry_and_still_replaces_ordinary_extracted_rows(
    tmp_path: Path, rescanner
):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Холестерин загальний", 5.2, unit="ммоль/л", status="extracted")
    stored(settings, user_id, "Ферритин", 48.0, unit="нг/мл", status="extracted")
    _mark_ai(settings, "Ферритин", "ai_suggested_entry")
    # The parser now reads a different analyte, and no longer reads cholesterol.
    rescanner([parsed("Креатинін", 80.0, unit="мкмоль/л")])

    pipeline.reingest_document(settings, user_id, "doc-1")

    after = {row["raw_name"]: row for row in rows(settings)}
    assert "Холестерин загальний" not in after
    assert after["Ферритин"]["extraction_method"] == "ai_suggested_entry"
    assert after["Ферритин"]["value_numeric"] == 48.0
    assert "Креатинін" in after


def test_a_reread_pairs_a_corrected_value_with_its_parsed_original_instead_of_duplicating_it(
    tmp_path: Path, rescanner
):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Глюкоза", 7.5, unit="ммоль/л", status="extracted")
    _mark_ai(settings, "Глюкоза", "ai_suggested_correction")
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")])

    pipeline.reingest_document(settings, user_id, "doc-1")

    glucose = [row for row in rows(settings) if row["raw_name"] == "Глюкоза"]
    assert [row["value_numeric"] for row in glucose] == [7.5]


# --- 5. ingest_file takes the write lock up front -----------------------------


def test_ingest_file_takes_the_write_lock_immediately_and_waits_for_it():
    source = inspect.getsource(pipeline.ingest_file)
    assert "BEGIN IMMEDIATE" in source
    assert "PRAGMA busy_timeout = 60000" in source


# --- 6. An undated report asks for its date -----------------------------------


def _ingest_and_keys(settings, user_id: str, tmp_path: Path, klass, found) -> set[str]:
    source = settings.source_dir / f"{klass.title}-{len(found)}.pdf"
    source.write_text(klass.title, encoding="utf-8")
    result = pipeline.ingest_file(settings, user_id, f"patient-{user_id}", source)
    with connect(settings) as connection:
        task = connection.execute(
            "SELECT reason_params_json FROM review_tasks WHERE entity_id=? AND state='open'",
            (result["document_id"],),
        ).fetchone()
    if task is None or not task["reason_params_json"]:
        return set()
    return {part["key"] for part in json.loads(task["reason_params_json"])["parts"]}


def test_an_undated_report_with_an_undated_result_asks_for_its_date(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    undated = classification(title="Undated panel", report_date=None)
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=undated, per_page=[undated])

    keys = _ingest_and_keys(settings, user_id, tmp_path, undated, found=[1])

    assert "review.no_date" in keys


def test_a_dated_report_does_not_ask_for_its_date(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    dated = classification(title="Dated panel", report_date="2025-02-13")
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=dated, per_page=[dated])

    keys = _ingest_and_keys(settings, user_id, tmp_path, dated, found=[1])

    assert "review.no_date" not in keys


def test_an_undated_report_whose_results_are_dated_does_not_ask_for_its_date(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    undated = classification(title="Undated panel with dated rows", report_date=None)
    rescanner(
        [parsed("Глюкоза", 5.0, unit="ммоль/л", observed_at="2025-01-03")],
        klass=undated, per_page=[undated],
    )

    keys = _ingest_and_keys(settings, user_id, tmp_path, undated, found=[1])

    assert "review.no_date" not in keys


# --- 7. A file name stays out of the log ----------------------------------------


def test_an_unreadable_file_is_logged_by_type_not_by_name(tmp_path: Path, monkeypatch, caplog):
    settings, user_id, _ = build(tmp_path)
    scans = tmp_path / "scans"
    scans.mkdir()
    (scans / "Ivanenko-Maksym.pdf").write_bytes(b"%PDF-1.4 not really")

    def unreadable(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(pipeline, "ingest_file", unreadable)
    with caplog.at_level(logging.DEBUG, logger="anamna.ingest.pipeline"):
        results = pipeline.ingest_directory(settings, user_id, "patient", source_dir=scans)

    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == ["ingest: a .pdf file could not be read (RuntimeError)"]
    assert not any("Ivanenko" in record.getMessage() for record in caplog.records)
    assert results == [{"filename": "Ivanenko-Maksym.pdf", "action": "failed", "error": "RuntimeError"}]


# --- 8. Migration 058 -----------------------------------------------------------

MIGRATION_058 = db.MIGRATIONS_DIR / "058_ingest_indexes.sql"
NEW_INDEXES = {
    "idx_upload_jobs_document",
    "idx_audit_events_entity",
    "idx_review_tasks_entity",
    "idx_clinical_findings_report",
    "idx_parser_issue_reports_observation",
}


def test_migration_058_has_no_self_managed_statements():
    sql = MIGRATION_058.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(BEGIN|COMMIT|PRAGMA)\b", sql, re.IGNORECASE | re.MULTILINE)


def test_migration_058_applies_on_a_fresh_database(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "fresh.sqlite3", source_dir=tmp_path / "sources", secret_key="x")

    db.migrate(settings)

    with connect(settings) as connection:
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    assert NEW_INDEXES <= indexes
    assert 58 in applied
