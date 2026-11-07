# Extraction and verification

## Why “100% accurate OCR” is not a machine claim

No OCR engine or document parser can prove clinical correctness from confidence alone. A decimal separator, comparator, unit, page association, or patient/date can be read plausibly and still be wrong. The application therefore treats 100% as a review objective: every accepted fact must be traceable and explicitly checked, not merely assigned a high model score.

## Evidence pipeline

1. Compute a SHA-256 for the physical file and detect exact copies.
2. Extract native PDF text page by page. Keep it byte-content-addressed and separate from OCR.
3. Inspect every PDF page for substantial embedded image regions even when native text exists. OCR the original embedded pixels when available, with a rendered crop only as fallback. Keep OCR separate from native text and label every OCR-derived fact provisional.
4. Classify each page and segment compound PDFs into logical reports by vendor, type, date, and order identifier.
5. Apply vendor-aware parsers. Store the raw line as `evidence_text` with the page number.
6. Normalize raw names through aliases. Unknown names are retained as unmapped concepts.
7. Store vendor reference text and parsed bounds on the observation itself.
8. Create a review task for every document, including duplicates, missing-result exports, and narrative-only reports.
9. A human opens the source and page evidence, corrects if needed, then verifies. The audit log records the decision.

## Acceptance criteria for a verified observation

A reviewer should confirm all of the following against the original file:

- patient and owner are correct;
- report/collection date and vendor are correct;
- metric name and specimen/context are correct;
- comparator, decimal separator, numeric or categorical value, and unit are exact;
- the vendor reference applies to the patient's displayed context;
- the observation is attached to the right logical report and page;
- no row has been duplicated, merged, or omitted.

Until that occurs, the UI labels the observation `extracted` and its trend point remains provisional. A human-edited value is `corrected`; it can then be verified through the document review.

Automated acceptance gates are read-only. Hash matches, complete page storage, parser coverage, representative pixel-to-row checks and database integrity may prove that the pipeline behaved as designed, but they never change `extracted`/`not_reviewed` to `verified` or close a review task.

## Parser safeguards already implemented

- native text and embedded-image OCR are parsed as distinct evidence channels;
- the original embedded bitmap is preferred over a re-rasterized page crop;
- small logos/QR codes and full-page decorative backgrounds are excluded from result-region OCR;
- page boundaries and physical/logical document boundaries are retained;
- exact duplicate files are linked and do not duplicate measurements;
- numeric lines cannot become analyte names;
- numeric reference lines ending in “positive/negative” cannot become duplicate categorical observations;
- PCR section headings are used instead of instrument/method lines;
- result-not-present exports are represented as orders/documents, not invented negative results;
- diagnostic images contribute no clinical interpretation automatically;
- every source has an open trust decision after import.
- Garmin account exports parse only health-bearing records, reconcile duplicate FIT/JSON representations, and retain excluded implausible scale captures in provenance metadata;
- Kardia ECG events retain the complete source PDF, reported heart rate, recording time/duration and the vendor algorithm wording without treating it as a clinician diagnosis.

`scripts/validate_source_extraction.py` and `scripts/validate_device_imports.py` write local ledgers (`work/extraction-validation.md`, `work/extraction-validation.json` and `work/device-import-validation.json`) that serve as the proof checklist for every source document and direct device import. They are intentionally git-ignored because filenames may identify a patient.

## Reader-filed parser problem reports

A person looking at a document can file "Report a problem" (on any extracted
value's row, or on the document itself for a value that is missing entirely).
Reports land in the `parser_issue_reports` table with a `context_json`
snapshot of the extraction as it stood at filing time — source path, page,
evidence line, stored value, parser version — so the report stays actionable
after re-scans regenerate observation rows.

This table is the work queue for parser fixes. To consume it, start with

```sql
SELECT * FROM parser_issue_reports WHERE status='open' ORDER BY created_at;
```

and follow the contract documented at the top of
`migrations/017_parser_issue_reports.sql`: reproduce against the snapshotted
evidence, fix `ingest/parsers.py`, add a regression test, re-read the
affected document, and only then mark the report resolved (the "Mark fixed"
control on the document page, or `POST /issues/{id}/state`). Resolving means
"the defect is fixed and the document re-read", not "seen".

That route takes `action=resolve` or `action=reopen` — anything else is a
400 — plus `csrf_token` when you hold a cookie session rather than a bearer
token, and an optional `next` to choose where it returns you. It is scoped to
the signed-in owner, so another account's report id answers 404.
