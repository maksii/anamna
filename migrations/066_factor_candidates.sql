-- Entries found in a person's documents, waiting for the person to accept them.
--
-- "Find in my documents" reads each consultation or clinical report once
-- (factor_scans remembers which) and writes what the document says the person
-- takes, was prescribed, underwent or was ill with (factor_candidates).  A
-- candidate is not part of the record: the Medicines page offers it, and only
-- an accepted one becomes a row of factors.
--
-- name_key        the name folded for comparison, so the same medicine in ten
--                 consultations is offered once.
-- how_written     the regimen in the document's own words.
-- timing          'now' the document prescribes it or says it is present,
--                 'past' it happened or ended before the document,
--                 'planned' it is scheduled for later.
-- event_date      the date the document itself gives for the item, as a full
--                 date; date_exact is 0 when the document gave only a month or
--                 a year.  NULL means no date was given: the document's own
--                 date then stands for a 'now' item and nothing for the rest.
-- quote           the passage that states the item.  A candidate whose quote
--                 was not found in the document text is never stored.
-- state           'new' offered, 'accepted' became factor_id, 'dismissed' the
--                 person said no and is not asked again.
CREATE TABLE IF NOT EXISTS factor_scans (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scanned_at TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    found INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_factor_scans_owner ON factor_scans(owner_user_id);

CREATE TABLE IF NOT EXISTS factor_candidates (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('medicine','supplement','procedure','illness','diet','activity','other')),
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    substance TEXT NOT NULL DEFAULT '',
    strength TEXT NOT NULL DEFAULT '',
    dose_amount REAL,
    dose_unit TEXT NOT NULL DEFAULT '',
    schedule_json TEXT NOT NULL DEFAULT '',
    how_written TEXT NOT NULL DEFAULT '',
    timing TEXT NOT NULL DEFAULT 'now' CHECK (timing IN ('now','past','planned')),
    event_date TEXT,
    date_exact INTEGER NOT NULL DEFAULT 0,
    duration_days INTEGER NOT NULL DEFAULT 0,
    long_term INTEGER NOT NULL DEFAULT 0,
    stopped INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'new' CHECK (state IN ('new','accepted','dismissed')),
    factor_id TEXT REFERENCES factors(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_factor_candidates_owner ON factor_candidates(owner_user_id, state);
CREATE INDEX IF NOT EXISTS idx_factor_candidates_document ON factor_candidates(document_id);
