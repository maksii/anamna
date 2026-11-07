-- AI short state for the "What changed" page.  One cached answer per reader,
-- locale and scope ('all' or 'document:<id>').  `fingerprint` is a hash of the
-- exact change data that was sent, so an unchanged state is never regenerated
-- and a summary written before new results arrived is shown as out of date
-- rather than passed off as current.  Advisory text only: nothing here feeds
-- `evaluate()` or verification, and deleting the account deletes the rows.
CREATE TABLE IF NOT EXISTS ai_change_summaries (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    locale TEXT NOT NULL,
    scope TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    model TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_user_id, locale, scope)
);
