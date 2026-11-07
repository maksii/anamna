-- `part_of`: one report that arrived as several files, one screenshot per page
-- or scroll position, uploaded together.  Source is a later part, target the
-- first part of the same report; each part keeps its own pages and values.
-- The CHECK cannot be altered in place, so the table is rebuilt with the same
-- columns and key (as in 037).
CREATE TABLE document_relations_new (
    source_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('duplicate', 'reprint', 'supersedes', 'contains', 'overlaps', 'attachment_of', 'part_of')
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
