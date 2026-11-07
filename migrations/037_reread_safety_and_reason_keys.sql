-- Re-reads that cannot quietly damage the record, and review reasons that can
-- be said in either language.
--
-- 1. Review reasons as a key and its parameters.  `reason` held one English
--    sentence per task, assembled with counts baked in ("Verify 57 extracted
--    observation(s) ..."), which is why the Ukrainian page showed English, why
--    every count read "(s)", and why a re-read that found a changed value had
--    nowhere to put *which* value changed.  `reason_key` is the first part's
--    catalogue key; `reason_params_json` is {"parts": [{"key": ..., "params":
--    {...}}, ...]}.  `reason` stays, in English, as the fallback for rows this
--    migration could not read back (pipeline.backfill_review_reason_keys reads
--    the known sentences back apart on start).
ALTER TABLE review_tasks ADD COLUMN reason_key TEXT;
ALTER TABLE review_tasks ADD COLUMN reason_params_json TEXT;

-- 2. The value as the page printed it.  «1,80» stored as REAL is 1.8, and the
--    trailing zero is the laboratory saying how precisely it measured; the
--    formatter shows at least this many decimals when the stored number is
--    still the printed one.
ALTER TABLE observations ADD COLUMN value_printed TEXT;

-- 3. Who chose the report date.  The title had `title_set_by`; the date had
--    nothing, so a re-read replaced a date the owner typed with whatever the
--    classifier found -- for three ultrasound reports, nothing at all.
--    Backfilled from the audit trail: a date a person submitted that is still
--    the stored date was set by that person.
ALTER TABLE documents ADD COLUMN report_date_set_by TEXT;
UPDATE documents SET report_date_set_by = 'human'
 WHERE report_date IS NOT NULL
   AND EXISTS (
       SELECT 1 FROM audit_events a
        WHERE a.entity_type = 'document' AND a.entity_id = documents.id
          AND a.action IN ('document_metadata_edited', 'ai_document_details_applied', 'document_reclassified')
          AND json_valid(a.details_json)
          AND json_extract(a.details_json, '$.report_date') = documents.report_date
   );

-- 4. The printed number of a report that can arrive as more than one file
--    (a pathology report № 40217/24 exported under two orders).  Matching on it
--    is what links the two copies; see pipeline.record_document_relations.
ALTER TABLE documents ADD COLUMN report_number TEXT;

-- 5. `attachment_of`: an export whose order cover is a separate document (the
--    ALEX² cover says "the result is in the attached PDF").  The CHECK cannot be
--    altered in place, so the table is rebuilt with the same columns and key.
--    Relationship meanings, source → target:
--      duplicate     the same report (same printed number and issue date, or
--                    the same results) held twice
--      reprint       the same printed report number and study date, issued again
--      contains      every result of target is also in source
--      overlaps      some results are in both
--      attachment_of source holds the results the target cover points to
--    Rows written by the pipeline carry notes starting 'auto:' so a re-read can
--    replace its own conclusions without touching a person's.
CREATE TABLE document_relations_new (
    source_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('duplicate', 'reprint', 'supersedes', 'contains', 'overlaps', 'attachment_of')
    ),
    confidence REAL NOT NULL DEFAULT 1.0,
    notes TEXT,
    PRIMARY KEY(source_document_id, target_document_id, relationship)
);
INSERT INTO document_relations_new
    SELECT source_document_id, target_document_id, relationship, confidence, notes
      FROM document_relations;
DROP TABLE document_relations;
ALTER TABLE document_relations_new RENAME TO document_relations;
CREATE INDEX IF NOT EXISTS idx_document_relations_target ON document_relations(target_document_id);
