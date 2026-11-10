import importlib.util
import sqlite3
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_source_extraction.py"
spec = importlib.util.spec_from_file_location("validate_source_extraction", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE documents(id TEXT, patient_id TEXT, report_date TEXT, clinical_type TEXT, status TEXT,
                                  duplicate_of_document_id TEXT, extraction_strategy TEXT);
           CREATE TABLE document_relations(source_document_id TEXT, target_document_id TEXT, relationship TEXT, notes TEXT);
           CREATE TABLE clinical_findings(id TEXT, document_id TEXT, finding_date TEXT, page_number INTEGER);
           CREATE TABLE document_pages(document_id TEXT, page_number INTEGER, native_text TEXT, ocr_text TEXT);
           INSERT INTO documents VALUES ('protocol', 'p', NULL, 'clinical_report', 'final', NULL, 'ocr_image_metadata'),
                                        ('photo', 'p', NULL, 'ultrasound', 'final', NULL, 'ocr_image_metadata');
           INSERT INTO clinical_findings VALUES ('f', 'protocol', NULL, 1);
           INSERT INTO document_pages VALUES ('photo', 1, '', '');"""
    )
    return connection


def _codes(record):
    return {(issue["severity"], issue["code"]) for issue in record.get("issues", [])}


def test_a_page_a_person_filed_under_its_report_is_covered_by_that_report():
    connection = _db()
    row = connection.execute("SELECT * FROM documents WHERE id='photo'").fetchone()
    record: dict = {}
    validator.check_pages(record, connection, row, 1)
    validator.check_missing_findings(record, connection, row, "")
    assert ("error", "page_without_text_evidence") in _codes(record)
    assert ("error", "clinical_finding_missing") in _codes(record)

    connection.execute("INSERT INTO document_relations VALUES ('photo', 'protocol', 'part_of', 'person:part_of')")
    record = {}
    validator.check_pages(record, connection, row, 1)
    validator.check_missing_findings(record, connection, row, "")
    assert _codes(record) == {("warning", "part_without_text_evidence"), ("warning", "clinical_finding_in_parent")}

    # A suggestion nobody confirmed is not a person's filing.
    connection.execute("UPDATE document_relations SET notes='auto:same_order'")
    record = {}
    validator.check_pages(record, connection, row, 1)
    assert ("error", "page_without_text_evidence") in _codes(record)


def test_a_synevo_package_summary_is_not_a_report_that_lost_its_results():
    row = {"clinical_type": "laboratory", "status": "final", "duplicate_of_document_id": None}
    summary = [{"native_text": "Лейкоцити 6.35\n/ Пакет № 183 Все під контролем для жінок / 12.05.2023 / стор. 2"}]
    plain = [{"native_text": "Лейкоцити 6.35 x10^9/л"}]
    record: dict = {}
    validator.check_observations(record, row, [], [1], summary)
    assert _codes(record) == {("warning", "companion_summary")}
    record = {}
    validator.check_observations(record, row, [], [1], plain)
    assert _codes(record) == {("error", "structured_results_missing")}
