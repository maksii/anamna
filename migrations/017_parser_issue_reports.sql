-- A person's report that the parser got something wrong, filed from the page
-- where they saw it.  Corrections fix one number; these reports exist so the
-- *parser defect behind it* can be found and fixed, and they are written to be
-- consumed by whoever (human or agent) does that fixing.
--
-- How to work a report, starting from nothing but this table:
--
--   SELECT * FROM parser_issue_reports WHERE status='open' ORDER BY created_at;
--
--   `category` names the defect class:
--     wrong_value      the number or text was read incorrectly
--     wrong_unit       the unit is wrong or missing (check UNIT_PATTERN /
--                      UNIT_SYNONYMS in ingest/parsers.py and health.py)
--     wrong_metric     the value was mapped to the wrong metric (aliases,
--                      Synevo tail discriminators, homoglyphs)
--     wrong_reference  the reference interval was read incorrectly
--     missing_value    a printed result the parser never extracted at all
--                      (usually a unit missing from the UNIT_PATTERN allowlist)
--     not_a_result     parser debris - something extracted that is not a
--                      measurement
--     wrong_date_or_page  the value landed on the wrong date or page
--     other            see description
--
--   `expected_text` is what the reporter says the document actually prints;
--   `description` is their free text.  `context_json` is a server-made
--   snapshot taken at report time, so it survives re-scans that regenerate
--   observation ids:
--     .parser_version          the parser that produced the bad row
--     .document{id, source_path, original_filename, vendor, clinical_type,
--               report_date, sha256}   - source_path opens the original file
--     .observation{raw_name, value_numeric, value_text, comparator, unit_raw,
--                  unit_canonical, concept_id, canonical_name, page_number,
--                  evidence_text, vendor_reference_text, extraction_method,
--                  verification_status} - null for document-level reports.
--                  evidence_text is the exact source line the parser read:
--                  compare it against what was stored to see the defect.
--
--   The loop: reproduce against the source file, fix ingest/parsers.py, add a
--   regression test, rescan the affected document (POST /documents/{id}/rescan
--   or scripts), confirm the value now reads correctly, then mark resolved.
--   Resolving is a human/agent statement that the defect is fixed, not that
--   the report was seen.
--
-- `observation_id` is SET NULL rather than CASCADE: a re-scan deletes and
-- recreates observation rows, and the report must outlive the row it was
-- filed against - the snapshot carries everything the row knew.
CREATE TABLE IF NOT EXISTS parser_issue_reports (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,
    category TEXT NOT NULL CHECK (category IN (
        'wrong_value', 'wrong_unit', 'wrong_metric', 'wrong_reference',
        'missing_value', 'not_a_result', 'wrong_date_or_page', 'other')),
    expected_text TEXT,
    description TEXT,
    context_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_parser_issue_reports_owner_status
    ON parser_issue_reports(owner_user_id, status);
CREATE INDEX IF NOT EXISTS idx_parser_issue_reports_document
    ON parser_issue_reports(document_id);
