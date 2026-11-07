-- Paperless-ngx integration: strictly optional, additive only.
--
-- The operator turns the feature on and names the server in `app_settings`
-- (managed from /admin/paperless); each person then decides for themselves
-- whether their uploads leave this application, and presents their own
-- Paperless credential to do it.  The token is stored as given, not hashed:
-- unlike our own access tokens it must be replayed to Paperless on every
-- request, so a hash would make it unusable.
CREATE TABLE IF NOT EXISTS paperless_accounts (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    api_token TEXT NOT NULL DEFAULT '',
    upload_enabled INTEGER NOT NULL DEFAULT 0 CHECK (upload_enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

-- The mapping between a document here and its copy in Paperless.  An upload
-- is asynchronous on their side: post_document answers with a task id, and
-- the document id exists only once consumption (OCR included) finishes, so
-- both stages are recorded.  `paperless_task_id` set and `paperless_id` empty
-- means "handed over, not yet consumed"; both empty means "never sent".
ALTER TABLE documents ADD COLUMN paperless_task_id TEXT;
ALTER TABLE documents ADD COLUMN paperless_id INTEGER;
