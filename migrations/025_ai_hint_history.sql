-- Keep every completed AI review as an immutable round. The original table
-- cached one row per document and locale, so requesting another review
-- replaced the previous answer. Existing cached reviews become the first
-- history item for their document.
ALTER TABLE ai_document_hints RENAME TO ai_document_hints_latest;

CREATE TABLE ai_document_hints (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    locale TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO ai_document_hints(
    document_id, locale, provider, model, content_json, created_at
)
SELECT document_id, locale, provider, model, content_json, created_at
FROM ai_document_hints_latest;

DROP TABLE ai_document_hints_latest;

CREATE INDEX idx_ai_document_hints_document_locale_created
ON ai_document_hints(document_id, locale, created_at DESC, id DESC);
