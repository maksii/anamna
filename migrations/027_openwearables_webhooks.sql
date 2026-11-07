-- Durable outgoing-webhook receipts and account-scoped synchronization.
CREATE TABLE openwearables_subscriptions (
    id TEXT PRIMARY KEY,
    server_url TEXT NOT NULL,
    endpoint_id TEXT NOT NULL DEFAULT '',
    callback_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL DEFAULT '',
    filter_types_json TEXT NOT NULL DEFAULT '[]',
    secret TEXT NOT NULL DEFAULT '',
    previous_secret TEXT NOT NULL DEFAULT '',
    previous_secret_until REAL NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE openwearables_sync_jobs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL,
    link_generation TEXT NOT NULL,
    reason TEXT NOT NULL,
    start_day TEXT NOT NULL,
    end_day TEXT NOT NULL,
    next_day TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL DEFAULT 0,
    lease_until REAL NOT NULL DEFAULT 0,
    lease_token TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    counts_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ow_jobs_ready ON openwearables_sync_jobs(status, available_at, lease_until);
CREATE INDEX ow_jobs_owner ON openwearables_sync_jobs(owner_user_id, link_generation, status);
CREATE TABLE openwearables_receipts (
    id INTEGER PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES openwearables_subscriptions(id),
    message_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    remote_user_id TEXT NOT NULL DEFAULT '',
    body BLOB NOT NULL,
    body_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(subscription_id, message_id)
);
CREATE TABLE openwearables_receipt_targets (
    receipt_id INTEGER NOT NULL REFERENCES openwearables_receipts(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    link_generation TEXT NOT NULL,
    job_id TEXT REFERENCES openwearables_sync_jobs(id),
    PRIMARY KEY(receipt_id, owner_user_id)
);
-- An account deletion cascades its target rows. Retain delivery idempotency
-- metadata, but erase health bytes once no owning account remains.
CREATE TRIGGER ow_receipt_last_owner_deleted AFTER DELETE ON openwearables_receipt_targets
WHEN NOT EXISTS (SELECT 1 FROM openwearables_receipt_targets WHERE receipt_id=OLD.receipt_id)
BEGIN
    UPDATE openwearables_receipts SET body=X'',status='unlinked' WHERE id=OLD.receipt_id;
END;
CREATE TABLE openwearables_raw_samples (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL,
    sample_key TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    series_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(owner_user_id, server_url, remote_user_id, sample_key)
);
CREATE INDEX ow_samples_window ON openwearables_raw_samples(owner_user_id, server_url, remote_user_id, timestamp);
CREATE TABLE openwearables_raw_records (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL,
    datatype TEXT NOT NULL,
    record_key TEXT NOT NULL,
    day TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(owner_user_id, server_url, remote_user_id, datatype, record_key)
);
CREATE TABLE openwearables_schedule (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    link_generation TEXT NOT NULL,
    next_catchup_at REAL NOT NULL DEFAULT 0,
    next_backfill_at REAL NOT NULL DEFAULT 0
);
