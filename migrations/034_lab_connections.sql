-- Lab connections: optional result sync from laboratory customer portals
-- (EskuLab, Synevo).  Additive only.
--
-- Both labs serve their customer sites from unofficial, undocumented JSON
-- APIs.  The operator enables each provider and names its base URL in
-- `app_settings` (`labsync_<provider>_enabled`, `labsync_<provider>_url`,
-- managed from /admin/lab-connections); each person then stores the credential
-- their own signed-in browser holds and chooses which person on that lab
-- account feeds *their* record.
--
-- `secret` is stored as given, not hashed: like the Paperless token it has to
-- be replayed on every request (EskuLab: the `accessKey` JWT sent as a bearer
-- token; Synevo: the `next-auth.session-token` cookie, which the server may
-- re-issue and which is then stored again so the session keeps rolling).  It
-- is never rendered back (the page shows the last six characters and the
-- expiry), never logged and never written into an audit row.  Only identity
-- fields of the lab's person list are kept (id, names, date of birth, sex);
-- the APIs also answer with logins, phone numbers, e-mail addresses and
-- password fields, which are dropped before anything reaches this table.
CREATE TABLE IF NOT EXISTS lab_accounts (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('eskulab', 'synevo')),
    secret TEXT NOT NULL DEFAULT '',
    -- EskuLab's `AccessPhone` header; empty for Synevo.
    phone TEXT NOT NULL DEFAULT '',
    -- EskuLab: the JWT's own `exp`, read without verifying the signature.
    -- Synevo: the session's `expires`.  Only to warn, never to trust.
    secret_expires_at TEXT,
    -- The last "Check" answer, filtered to identity fields, so the person
    -- picker survives the POST -> redirect -> GET round trip.  Cleared once a
    -- person is chosen: the others on the lab account are somebody else.
    persons_json TEXT,
    checked_at TEXT,
    -- Which lab person feeds this record.  `mismatch_confirmed` is the
    -- explicit "yes, these are my results" given when that person's date of
    -- birth or sex differs from (or cannot be compared with) the Anamna
    -- profile: importing somebody else's results is the main risk.
    remote_person_id TEXT,
    remote_person_json TEXT,
    mismatch_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (mismatch_confirmed IN (0, 1)),
    sync_state TEXT NOT NULL DEFAULT 'idle'
        CHECK (sync_state IN ('idle', 'running', 'done', 'failed')),
    -- A localisation key from a fixed set, never raw exception text.
    sync_detail_key TEXT,
    sync_started_at TEXT,
    sync_finished_at TEXT,
    sync_summary_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, provider)
);

-- One row per lab order a person's sync has seen, so a sync is idempotent.
--
--   pending      the lab has not finished every test; nothing is imported, a
--                later sync imports it once complete
--   importing    the official PDF is in the intake queue
--   imported     the sync downloaded the PDF and the normal pipeline read it
--   linked       the order was already in the record (a manual upload with
--                the same order number, or the same date and matching values);
--                no second document was created
--   unavailable  the lab offers no downloadable PDF for it (a Synevo in-lab
--                order without a web id, or one behind an eHealth one-time
--                code); its values are still cross-checked if linked later
--   removed      the person deleted the document afterwards; never re-imported
--   failed       this order could not be fetched or read; `error_key` says why
--
-- `order_id` is the number printed on the report (EskuLab order number,
-- Synevo barcode) — what documents.order_identifier holds.  `remote_ref` is
-- the lab's own handle when it differs (Synevo WebOrderId).
-- `rows_json` holds the lab's structured result rows — the second, independent
-- reading the cross-check compares the parsed PDF against.  `rows_hash`
-- changes when the lab amends a result; `rows_changed_at` records it.
CREATE TABLE IF NOT EXISTS lab_orders (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('eskulab', 'synevo')),
    remote_person_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    remote_ref TEXT,
    ordered_at TEXT,
    lab_status TEXT,
    ready INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN
        ('pending', 'importing', 'imported', 'linked', 'unavailable', 'removed', 'failed')),
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    upload_job_id TEXT,
    rows_hash TEXT,
    rows_json TEXT,
    rows_changed_at TEXT,
    crosscheck_json TEXT,
    crosscheck_at TEXT,
    error_key TEXT,
    first_seen_at TEXT NOT NULL,
    last_synced_at TEXT NOT NULL,
    PRIMARY KEY (owner_user_id, provider, order_id)
);

CREATE INDEX IF NOT EXISTS idx_lab_orders_document ON lab_orders(owner_user_id, document_id);
