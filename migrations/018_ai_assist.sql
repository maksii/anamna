-- AI assist: free-model hints, strictly optional.  Two tables, both additive.
--
-- `ai_usage` is operator telemetry: one row per outbound model request, kept
-- regardless of outcome so the admin page can show spend against the free-tier
-- budget and show failures instead of hiding them.  No user foreign key — the
-- request belongs to the instance, and deleting an account must not falsify
-- the day's request count that a rate limit was enforced against.
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    feature TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    error TEXT
);

-- Budget checks scan today's rows; the admin page scans a month.
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at);

-- Who last chose the document's title.  NULL means the classifier's answer is
-- standing and a rescan may replace it; 'human' means a person picked the
-- title (typed or adopted from a suggestion) and reingest must keep it, the
-- same way a human classification survives a re-read.
ALTER TABLE documents ADD COLUMN title_set_by TEXT;

-- One cached analysis per document and locale.  Content is the model's parsed
-- JSON answer (summary, suggested title, likely-missed values, suspicious
-- rows).  Hints are advisory text, never observations: nothing here feeds
-- `evaluate()` or verification, and deleting the document deletes its hints.
CREATE TABLE IF NOT EXISTS ai_document_hints (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    locale TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, locale)
);
