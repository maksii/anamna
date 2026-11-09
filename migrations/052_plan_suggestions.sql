-- A doctor's selection on /plan-tests, saved for the patient to review.
--
-- A doctor reads the record through a guest credential (an access code or a
-- link), which may plan but never order.  "Save for the patient" keeps the
-- planner's own query string (the tests ticked, the city, the mode), so the
-- owner reopens exactly that selection, changes what they want and orders it
-- themselves.  `token_id` says which credential saved it; the credential may
-- be revoked later, the suggestion stays.  `author` is that credential's
-- label as it read at the time.

CREATE TABLE IF NOT EXISTS plan_suggestions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    test_count INTEGER NOT NULL,
    token_id TEXT REFERENCES access_tokens(id) ON DELETE SET NULL,
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    dismissed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_plan_suggestions_owner ON plan_suggestions(owner_user_id, created_at);
