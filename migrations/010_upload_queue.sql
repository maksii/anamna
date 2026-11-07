-- The intake queue.
--
-- An upload is no longer one file processed while the browser waits: a
-- submission can be a dozen scans, a zip of them, or a multi-gigabyte vendor
-- export that unpacks into thousands of files. Each unit of work is one row
-- here, so the page can show what is queued, what is running and what it
-- produced, and so a crash mid-batch leaves an explicit record rather than a
-- half-imported record with nothing to point at.
--
-- `batch_id` groups one submission. An archive job enqueues its contents into
-- the same batch, which is why progress is counted per batch and not per file.
CREATE TABLE IF NOT EXISTS upload_jobs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    -- 'document'      one scan or photo through the extraction pipeline
    -- 'archive'       a zip that expands into more jobs in this batch
    -- 'device_export' a vendor export directory handed to a device adapter
    -- 'rescan'        an already-stored document re-read by today's parser
    kind TEXT NOT NULL CHECK (kind IN ('document', 'archive', 'device_export', 'rescan')),
    -- Named adapter for a device export, NULL when it is to be detected.
    adapter_key TEXT,
    filename TEXT NOT NULL,
    source_path TEXT,
    byte_size INTEGER,
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'done', 'failed', 'skipped')),
    -- A localisation key from a fixed set, never raw exception text: this
    -- table is rendered into a page and a stack trace carries file paths.
    detail_key TEXT,
    -- What the job produced, so the queue can link straight to the result.
    document_id TEXT,
    import_id TEXT,
    observation_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_upload_jobs_owner ON upload_jobs(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_batch ON upload_jobs(batch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_pending ON upload_jobs(state, created_at) WHERE state = 'queued';
