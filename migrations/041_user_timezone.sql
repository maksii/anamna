-- The calendar a person's device days are cut on.
--
-- Daily totals (steps, energy, sleep nights) used to be cut at UTC midnight by
-- the API adapters and at the export-time offset by the file adapters, so the
-- same evening walk landed on different days depending on which route carried
-- it. Every adapter now converts timestamps into this zone (IANA name, read
-- with DST-aware zoneinfo) before taking the date. Europe/Kyiv is the zone
-- every current account lives in; a person elsewhere changes it on /profile.
ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/Kyiv';

-- The device half of the page memo's fingerprint: every device write stamps
-- created_at, so MAX(created_at) per person says "something changed" in one
-- index probe instead of a scan of 160k rows (PERF-02).
CREATE INDEX IF NOT EXISTS idx_device_metric_days_owner_created
    ON device_metric_days(owner_user_id, created_at);
