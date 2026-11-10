"""Read-only corpus validator for source, page, extraction and clinical coverage.

The validator proves mechanical invariants that hold for any corpus.
It deliberately reports human verification state separately; passing this
script never marks clinical data verified or resolves a review task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import cast

from pypdf import PdfReader

from anamna.config import ROOT, Settings, get_settings, resolve_source_path
from anamna.health import _extract_clinical_assessment, _extract_date
from anamna.ingest.parsers import SYNEVO_SUMMARY_FOOTER


# ".json": the lab's own record of an order it issued no PDF for (labsync).
SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".json"}
STRUCTURED_TYPES = {"laboratory", "allergy", "microbiology", "blood_pressure", "electrocardiogram"}
NARRATIVE_TYPES = {
    "consultation", "diagnostic_image", "pathology", "radiology_mri",
    "radiology_xray", "ultrasound", "electrocardiogram",
}
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_count(path: Path) -> int:
    return len(PdfReader(path).pages) if path.suffix.casefold() == ".pdf" else 1


def add_issue(record: dict[str, object], severity: str, code: str, detail: str) -> None:
    issue = {"severity": severity, "code": code, "detail": detail}
    record.setdefault("issues", []).append(issue)


def rows_by_status(connection: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column} ORDER BY {column}"
        )
    }


def collect_files(source_root: Path) -> list[Path]:
    return sorted(
        (path.resolve() for path in source_root.rglob("*") if path.is_file() and path.suffix.casefold() in SUPPORTED),
        key=lambda path: str(path).casefold(),
    )


def find_corpus_issues(
    files: list[Path], by_path: dict[Path, sqlite3.Row], rejected: set[Path]
) -> list[dict[str, str]]:
    missing_db = sorted(set(files) - set(by_path), key=str)
    missing_source = sorted(set(by_path) - set(files), key=str)
    corpus_issues: list[dict[str, str]] = []
    for path in missing_db:
        corpus_issues.append(
            {"severity": "warning", "code": "upload_rejected_and_kept", "detail": str(path)}
            if path in rejected
            else {"severity": "error", "code": "source_not_imported", "detail": str(path)}
        )
    for path in missing_source:
        corpus_issues.append({"severity": "error", "code": "database_source_missing", "detail": str(path)})
    return corpus_issues


def check_file_facts(record: dict[str, object], path: Path, row: sqlite3.Row) -> int:
    """Hash, size and page count of the file against the stored row; returns the page count."""
    actual_hash = sha256(path)
    actual_pages = page_count(path)
    if actual_hash != row["sha256"]:
        add_issue(record, "error", "hash_mismatch", "Stored SHA-256 does not match the source bytes.")
    if path.stat().st_size != int(row["byte_size"]):
        add_issue(record, "error", "size_mismatch", "Stored byte size does not match the source file.")
    if actual_pages != int(row["page_count"]):
        add_issue(record, "error", "page_count_mismatch", f"Source has {actual_pages}; database has {row['page_count']}.")
    return actual_pages


def filed_under(connection: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    """The document a person filed this one as a part of: a photographed page
    of a protocol, an image sheet beside its report.  Its text and conclusion
    live there."""
    parent = connection.execute(
        """SELECT target_document_id FROM document_relations
           WHERE source_document_id=? AND relationship='part_of' AND notes LIKE 'person:%' LIMIT 1""",
        (row["id"],),
    ).fetchone()
    return str(parent[0]) if parent else None


def check_pages(
    record: dict[str, object], connection: sqlite3.Connection, row: sqlite3.Row, actual_pages: int
) -> tuple[list[sqlite3.Row], list[int]]:
    pages = connection.execute(
        "SELECT * FROM document_pages WHERE document_id=? ORDER BY page_number", (row["id"],)
    ).fetchall()
    page_numbers = [int(page["page_number"]) for page in pages]
    if page_numbers != list(range(1, actual_pages + 1)):
        add_issue(record, "error", "stored_page_gap", f"Stored pages are {page_numbers}.")
    for stored in pages:
        native = str(stored["native_text"] or "").strip()
        ocr = str(stored["ocr_text"] or "").strip()
        if not native and not ocr and row["clinical_type"] != "diagnostic_image":
            parent = filed_under(connection, row)
            if parent:
                add_issue(record, "warning", "part_without_text_evidence",
                          f"Page {stored['page_number']} has no text; a person filed it as part of {parent}.")
            else:
                add_issue(record, "error", "page_without_text_evidence", f"Page {stored['page_number']} has no native or OCR text.")
    if "embedded_image_ocr" in str(row["extraction_strategy"]) and not any(str(page["ocr_text"] or "").strip() for page in pages):
        add_issue(record, "error", "declared_ocr_missing", "Document declares embedded-image OCR but stores no OCR text.")
    return pages, page_numbers


def check_report_coverage(
    record: dict[str, object], connection: sqlite3.Connection, row: sqlite3.Row, actual_pages: int
) -> None:
    reports = connection.execute(
        "SELECT start_page, end_page FROM reports WHERE document_id=? ORDER BY start_page", (row["id"],)
    ).fetchall()
    covered = {
        number
        for report in reports
        for number in range(int(report["start_page"]), int(report["end_page"]) + 1)
        if 1 <= number <= actual_pages
    }
    if not reports or covered != set(range(1, actual_pages + 1)):
        add_issue(record, "error", "report_page_coverage", f"Logical reports cover pages {sorted(covered)}.")


def check_observations(
    record: dict[str, object], row: sqlite3.Row, observations: list[sqlite3.Row], page_numbers: list[int],
    pages: list[sqlite3.Row] | None = None,
) -> None:
    # A copy set aside as another document's duplicate gives its values to
    # the kept one (pipeline.mark_document_duplicate); it holds none.
    if (row["clinical_type"] in STRUCTURED_TYPES and row["status"] != "result_not_present" and not observations
            and not row["duplicate_of_document_id"]):
        # Synevo's package summary re-prints the main report's values as
        # infographics; the parser reads none of it on purpose (COMPANION_SUMMARY).
        if any(SYNEVO_SUMMARY_FOOTER.search(str(page["native_text"] or "")) for page in pages or []):
            add_issue(record, "warning", "companion_summary", "A package summary; its values are read from the main report.")
        else:
            add_issue(record, "error", "structured_results_missing", "A final structured report has no observations.")
    for observation in observations:
        values = int(observation["value_numeric"] is not None) + int(observation["value_text"] is not None)
        if values != 1:
            add_issue(record, "error", "invalid_typed_value", f"Observation {observation['id']} has {values} typed values.")
        if int(observation["page_number"]) not in page_numbers:
            add_issue(record, "error", "observation_page_missing", f"Observation {observation['id']} points to page {observation['page_number']}.")
        if not str(observation["raw_name"] or "").strip() or not str(observation["evidence_text"] or "").strip():
            add_issue(record, "error", "observation_provenance_missing", f"Observation {observation['id']} lacks raw name/evidence.")


def check_missing_findings(
    record: dict[str, object], connection: sqlite3.Connection, row: sqlite3.Row, combined_text: str
) -> None:
    # A re-issued or re-uploaded report, or an image set beside the
    # same day's written report, is deliberately folded into one
    # finding (health._deduplicate_findings).  That study is covered.
    study_date = _extract_date(combined_text, row["report_date"])
    covered = study_date and connection.execute(
        """SELECT 1 FROM clinical_findings f JOIN documents d ON d.id=f.document_id
           WHERE d.patient_id=? AND d.id<>? AND f.finding_date=? LIMIT 1""",
        (row["patient_id"], row["id"], study_date),
    ).fetchone()
    parent = filed_under(connection, row)
    if covered:
        add_issue(record, "warning", "clinical_finding_covered_elsewhere", f"Same study on {study_date} is filed from another document.")
    elif parent and connection.execute("SELECT 1 FROM clinical_findings WHERE document_id=? LIMIT 1", (parent,)).fetchone():
        add_issue(record, "warning", "clinical_finding_in_parent", f"A person filed this as part of {parent}, which holds the finding.")
    else:
        add_issue(record, "error", "clinical_finding_missing", "Narrative/visual document has no first-class finding.")


def check_findings(
    record: dict[str, object], connection: sqlite3.Connection, row: sqlite3.Row,
    findings: list[sqlite3.Row], pages: list[sqlite3.Row], page_numbers: list[int],
) -> None:
    combined_text = "\n".join(
        f"{page['native_text'] or ''}\n{page['ocr_text'] or ''}" for page in pages
    )
    is_narrative = row["clinical_type"] in NARRATIVE_TYPES
    if is_narrative and not findings:
        check_missing_findings(record, connection, row, combined_text)
    has_assessment = bool(_extract_clinical_assessment(combined_text))
    placeholder_findings = [finding for finding in findings if finding["original_text"] == "No written conclusion in the source."]
    if has_assessment and placeholder_findings:
        add_issue(record, "error", "assessment_not_attached", "Source has a written assessment, but a finding uses the no-conclusion placeholder.")
    if is_narrative and not has_assessment and row["clinical_type"] != "diagnostic_image":
        add_issue(record, "warning", "no_labeled_assessment", "No labeled conclusion/assessment section was detected; review the full page text.")
    for finding in findings:
        if int(finding["page_number"]) not in page_numbers:
            add_issue(record, "error", "finding_page_missing", f"Finding {finding['id']} points to page {finding['page_number']}.")


def validate_document(
    connection: sqlite3.Connection, record: dict[str, object], path: Path, row: sqlite3.Row
) -> None:
    actual_pages = check_file_facts(record, path, row)
    pages, page_numbers = check_pages(record, connection, row, actual_pages)
    check_report_coverage(record, connection, row, actual_pages)

    observations = connection.execute(
        "SELECT * FROM observations WHERE document_id=? ORDER BY page_number", (row["id"],)
    ).fetchall()
    findings = connection.execute(
        "SELECT * FROM clinical_findings WHERE document_id=? ORDER BY page_number", (row["id"],)
    ).fetchall()
    record["pages"] = actual_pages
    record["observations"] = len(observations)
    record["clinical_findings"] = len(findings)
    check_observations(record, row, observations, page_numbers, pages)
    check_findings(record, connection, row, findings, pages, page_numbers)

    task = connection.execute(
        "SELECT state FROM review_tasks WHERE entity_type='document' AND entity_id=?", (row["id"],)
    ).fetchone()
    if task is None:
        add_issue(record, "error", "review_task_missing", "Document has no trust-review task.")


def build_summary(
    connection: sqlite3.Connection, files: list[Path], documents: list[sqlite3.Row],
    records: list[dict[str, object]], all_issues: list[dict[str, str]], integrity: str, foreign_key_violations: int,
) -> dict[str, object]:
    severity_counts = Counter(str(issue["severity"]) for issue in all_issues)
    return {
        "sources": len(files),
        "documents": len(documents),
        "pages": sum(int(record.get("pages", 0)) for record in records),
        "reports": int(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0]),
        "observations": int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]),
        "clinical_findings": int(connection.execute("SELECT COUNT(*) FROM clinical_findings").fetchone()[0]),
        "errors": severity_counts["error"],
        "warnings": severity_counts["warning"],
        "database_integrity": integrity,
        "foreign_key_violations": foreign_key_violations,
        "page_review_statuses": rows_by_status(connection, "document_pages", "review_status"),
        "observation_verification_statuses": rows_by_status(connection, "observations", "verification_status"),
        "finding_verification_statuses": rows_by_status(connection, "clinical_findings", "verification_status"),
        "review_task_states": rows_by_status(connection, "review_tasks", "state"),
        "automated_pass_grants_clinical_verification": False,
    }


def render_markdown(
    summary: dict[str, object], records: list[dict[str, object]]
) -> str:
    lines = [
        "# Source extraction validation",
        "",
        "> Local-only report. Filenames may contain private health information.",
        "",
        f"- Sources/documents: {summary['sources']} / {summary['documents']}",
        f"- Pages/logical reports: {summary['pages']} / {summary['reports']}",
        f"- Structured observations/clinical findings: {summary['observations']} / {summary['clinical_findings']}",
        f"- Blocking errors/warnings: {summary['errors']} / {summary['warnings']}",
        f"- SQLite integrity/foreign-key violations: {summary['database_integrity']} / {summary['foreign_key_violations']}",
        "- Automated checks grant clinical verification: no",
        "",
        "## Documents requiring attention",
        "",
    ]
    flagged = [record for record in records if record["issues"]]
    if not flagged:
        lines.append("No blocking or warning-level document issues were found by the automated validator.")
    for record in flagged:
        lines.append(f"### {record['source']}")
        lines.append("")
        for issue in record["issues"]:
            lines.append(f"- {str(issue['severity']).upper()} `{issue['code']}` — {issue['detail']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "anamna.sqlite3")
    parser.add_argument("--sources", type=Path, default=ROOT / "sources")
    parser.add_argument("--json-output", type=Path, default=ROOT / "work" / "extraction-validation.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "work" / "extraction-validation.md")
    args = parser.parse_args()

    source_root = args.sources.resolve()
    files = collect_files(source_root)
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    documents = connection.execute(
        """SELECT d.*, v.canonical_name vendor FROM documents d
           JOIN vendors v ON v.id=d.vendor_id ORDER BY d.source_path"""
    ).fetchall()
    # The app's own resolver: a database copied from the container records
    # /data/sources/... paths that live here under the local sources directory.
    located = cast(Settings, replace(get_settings(), source_dir=source_root))
    by_path = {resolve_source_path(located, row["source_path"]).resolve(): row for row in documents}
    records: list[dict[str, object]] = []

    # A file the intake queue turned away is kept on purpose and the queue row
    # names it, so it is a recorded rejection rather than a lost import. Left as
    # an error, one corrupt upload made this script's exit code permanently
    # non-zero, and the cleanup contract in CLAUDE.md rests on that exit code
    # meaning something. Clearing the finished queue removes both.
    rejected = {
        resolve_source_path(located, str(row[0])).resolve()
        for row in connection.execute(
            "SELECT source_path FROM upload_jobs WHERE state='failed' AND source_path IS NOT NULL"
        )
    }
    # An unpacked device export (Garmin, Apple Health) is read by the device
    # importer; the pictures inside it (profile images) are not documents.
    device_dirs = [
        resolve_source_path(located, str(row[0])).resolve()
        for row in connection.execute("SELECT source_path FROM device_imports WHERE source_path IS NOT NULL")
    ]
    files = [path for path in files if path in by_path or not any(path.is_relative_to(d) for d in device_dirs)]
    corpus_issues = find_corpus_issues(files, by_path, rejected)

    for path in files:
        row = by_path.get(path)
        record: dict[str, object] = {
            "source": path.relative_to(source_root).as_posix(),
            "clinical_type": row["clinical_type"] if row else None,
            "issues": [],
        }
        if row is not None:
            validate_document(connection, record, path, row)
        records.append(record)

    unmapped = int(connection.execute(
        """SELECT COUNT(*) FROM observations o JOIN concepts c ON c.id=o.concept_id
           WHERE c.category='unmapped'"""
    ).fetchone()[0])
    if unmapped:
        corpus_issues.append({"severity": "warning", "code": "unmapped_concepts", "detail": f"{unmapped} observations remain unmapped."})
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    all_issues = corpus_issues + [issue for record in records for issue in record["issues"]]
    summary = build_summary(connection, files, documents, records, all_issues, integrity, foreign_key_violations)
    connection.close()
    payload = {
        "summary": summary,
        "corpus_issues": corpus_issues,
        "documents": records,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(summary, records), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"] or integrity != "ok" or foreign_key_violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
