-- Compact OpenWearables raw archive (one compressed blob per account, UTC day
-- and series type) and an exact running sample total for the status pages.
--
-- Structures only. The per-sample table `openwearables_raw_samples` (7.4 M rows,
-- ~7 GB on the sandbox) is copied out by the background, resumable job
-- `openwearables_archive.run_conversion`, one verified batch of account-days per
-- short transaction. From migration 040 on nothing writes to the old table; it
-- is dropped, with the space reclaimed, by
-- `python -m anamna.openwearables_archive reclaim`. Startup never waits.
CREATE TABLE openwearables_raw_days (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL,
    day TEXT NOT NULL,
    series_type TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    value_sum REAL NOT NULL,
    received_at TEXT NOT NULL,
    -- zlib(JSON [[sample_key, timestamp, received_at, payload_json], ...]):
    -- the exact former rows, so device, source app and unmapped fields survive.
    samples BLOB NOT NULL,
    PRIMARY KEY(owner_user_id, server_url, remote_user_id, day, series_type)
);

-- One row per account-day the archive owns while the old table still exists:
-- old rows of such a day are superseded and never read again. The fingerprint
-- is the old rows' content taken at conversion (the "before" side of the
-- comparison); NULL when a sync or delivery has since replaced the day.
CREATE TABLE openwearables_raw_conversion (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_url TEXT NOT NULL,
    remote_user_id TEXT NOT NULL,
    day TEXT NOT NULL,
    sample_count INTEGER,
    value_sum REAL,
    digest TEXT,
    converted_at TEXT NOT NULL,
    PRIMARY KEY(owner_user_id, server_url, remote_user_id, day)
);

-- Read by every /profile and /admin/openwearables render instead of count(*).
-- `samples` is the archive, kept exact by the triggers below. While the old
-- table exists, legacy_base (its row count, taken once by the background job)
-- minus legacy_done (rows on days the archive has taken over) is what it still
-- holds. Meaningless once that table is gone.
CREATE TABLE openwearables_raw_totals (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    samples INTEGER NOT NULL DEFAULT 0,
    legacy_done INTEGER NOT NULL DEFAULT 0,
    legacy_base INTEGER
);
INSERT INTO openwearables_raw_totals(owner_user_id) SELECT id FROM users;

CREATE TRIGGER ow_raw_days_insert AFTER INSERT ON openwearables_raw_days BEGIN
    INSERT OR IGNORE INTO openwearables_raw_totals(owner_user_id) VALUES (NEW.owner_user_id);
    UPDATE openwearables_raw_totals SET samples = samples + NEW.sample_count WHERE owner_user_id = NEW.owner_user_id;
END;
CREATE TRIGGER ow_raw_days_update AFTER UPDATE OF sample_count ON openwearables_raw_days BEGIN
    UPDATE openwearables_raw_totals SET samples = samples + NEW.sample_count - OLD.sample_count WHERE owner_user_id = NEW.owner_user_id;
END;
CREATE TRIGGER ow_raw_days_delete AFTER DELETE ON openwearables_raw_days BEGIN
    UPDATE openwearables_raw_totals SET samples = samples - OLD.sample_count WHERE owner_user_id = OLD.owner_user_id;
END;
