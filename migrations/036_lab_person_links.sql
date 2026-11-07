-- Lab connections, part two: one lab account feeds several people.
--
-- A family usually signs in to a lab with one phone number, and the lab lists
-- everybody tested under it (the account holder, a partner, the children).
-- Until now a connection fed exactly one person — the account holder's own
-- record.  Now each person on the lab account can be linked to the holder
-- *or* to another Anamna user the holder shares records with, and a
-- result only enters that other user's record once they accept it.
--
-- Also: the provider list is no longer a CHECK constraint.  Which providers
-- exist is code (labsync.PROVIDERS); a new lab — or another lab on a
-- white-label platform — must not need a table rebuild.  The rebuild here is
-- the last one for that reason.  `refresh_secret` holds a mobile app's refresh
-- token where the lab issues one (never rendered, logged or audited, like
-- `secret`).

-- lab_accounts: same columns minus the single-person mapping, which moves to
-- lab_person_links.  `persons_json` is no longer cleared on a choice: the
-- holder maps every person on the list, one by one.
CREATE TABLE lab_accounts_new (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    refresh_secret TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    secret_expires_at TEXT,
    persons_json TEXT,
    checked_at TEXT,
    sync_state TEXT NOT NULL DEFAULT 'idle'
        CHECK (sync_state IN ('idle', 'running', 'done', 'failed')),
    sync_detail_key TEXT,
    sync_started_at TEXT,
    sync_finished_at TEXT,
    sync_summary_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, provider)
);

-- Which lab person feeds whose record.
--
--   account_user_id   whose lab credential fetches it (the lab account holder)
--   target_user_id    whose record receives it — the holder, or a user they
--                     share records with (either direction)
--   consent           owner     target is the holder: imported straight away
--                     asked     every result waits for the target's "accept"
--                     accepted  the target chose to accept future results from
--                               this link without asking
--                     refused   the target stopped this link; nothing more is
--                               fetched for it until the holder links again
--   mismatch_confirmed  the holder's explicit "yes, this lab person is that
--                     user" when date of birth or sex differ or are unknown.
CREATE TABLE IF NOT EXISTS lab_person_links (
    account_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    remote_person_id TEXT NOT NULL,
    remote_person_json TEXT NOT NULL,
    target_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent TEXT NOT NULL CHECK (consent IN ('owner', 'asked', 'accepted', 'refused')),
    mismatch_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (mismatch_confirmed IN (0, 1)),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_user_id, provider, remote_person_id)
);

CREATE INDEX IF NOT EXISTS idx_lab_person_links_target ON lab_person_links(target_user_id, consent);

INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json, target_user_id,
                             consent, mismatch_confirmed, created_at, updated_at)
SELECT user_id, provider, remote_person_id, remote_person_json, user_id, 'owner', mismatch_confirmed,
       updated_at, updated_at
  FROM lab_accounts
 WHERE remote_person_id IS NOT NULL AND remote_person_id <> '' AND remote_person_json IS NOT NULL;

INSERT INTO lab_accounts_new(user_id, provider, secret, phone, secret_expires_at, persons_json, checked_at,
                             sync_state, sync_detail_key, sync_started_at, sync_finished_at, sync_summary_json,
                             updated_at)
SELECT user_id, provider, secret, phone, secret_expires_at, persons_json, checked_at, sync_state,
       sync_detail_key, sync_started_at, sync_finished_at, sync_summary_json, updated_at
  FROM lab_accounts;

DROP TABLE lab_accounts;
ALTER TABLE lab_accounts_new RENAME TO lab_accounts;

-- lab_orders: `owner_user_id` stays the record that receives the order;
-- `account_user_id` is whose credential fetched it.  Two new states:
--
--   awaiting   fetched for another user through a link they have not
--              accepted yet: the lab's rows are kept so they can see what it
--              is; no PDF is downloaded and nothing enters their record
--   accepted   they accepted it; the next sync of the holder's account
--              downloads and imports it (then: imported / linked / ...)
--   declined   they declined it; never offered again
CREATE TABLE lab_orders_new (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    remote_person_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    remote_ref TEXT,
    ordered_at TEXT,
    lab_status TEXT,
    ready INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN
        ('pending', 'importing', 'imported', 'linked', 'unavailable', 'removed', 'failed',
         'awaiting', 'accepted', 'declined')),
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

INSERT INTO lab_orders_new(owner_user_id, account_user_id, provider, remote_person_id, order_id, remote_ref,
                           ordered_at, lab_status, ready, total, state, document_id, upload_job_id, rows_hash,
                           rows_json, rows_changed_at, crosscheck_json, crosscheck_at, error_key, first_seen_at,
                           last_synced_at)
SELECT owner_user_id, owner_user_id, provider, remote_person_id, order_id, remote_ref, ordered_at, lab_status,
       ready, total, state, document_id, upload_job_id, rows_hash, rows_json, rows_changed_at, crosscheck_json,
       crosscheck_at, error_key, first_seen_at, last_synced_at
  FROM lab_orders;

DROP TABLE lab_orders;
ALTER TABLE lab_orders_new RENAME TO lab_orders;

CREATE INDEX IF NOT EXISTS idx_lab_orders_document ON lab_orders(owner_user_id, document_id);
CREATE INDEX IF NOT EXISTS idx_lab_orders_account ON lab_orders(account_user_id, provider, remote_person_id);
