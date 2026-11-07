-- Readings a person says are not theirs: a shared scale, a phone that also
-- records a partner's weigh-ins, a watch handed down from one person to the
-- next.  The raw archive is never touched; every aggregation entry point skips
-- what a rule here covers, so an exclusion is reversible and survives re-sync.
--
-- origin_*       the writer of the reading: provider (OpenWearables' upstream
--                provider such as 'apple', or a file adapter key such as
--                'apple_health'), source app, device model.  Always app plus
--                device, never a device model alone: a watch handed down
--                between two people keeps its model.
-- scope          'reading': one instant (from_utc); every series written at
--                  that instant, e.g. weight, BMI and fat of one weigh-in.
--                'window': from_utc..until_utc inclusive, for values derived
--                  from a wrong reading (energy computed from someone else's
--                  weight).  A daily total overlapping the window goes whole.
--                'origin': everything this source app and device wrote.
-- series         JSON array of metric keys the rule is limited to, or NULL for
--                every series ('workouts' and 'events' name those tables).
-- applied_at     when the stored days were last recalculated for this rule;
--                NULL while a recalculation is pending (shown as such).
-- revoked_at     the undo.  The row stays so the recalculation that restores
--                the values can be tracked; audit_events holds the history.
CREATE TABLE IF NOT EXISTS device_exclusions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    origin_provider TEXT NOT NULL,
    origin_source TEXT NOT NULL CHECK (origin_source <> ''),
    origin_device TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL CHECK (scope IN ('reading', 'window', 'origin')),
    from_utc TEXT,
    until_utc TEXT,
    series TEXT,
    belongs_to_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    revoked_at TEXT,
    revoked_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    CHECK (scope <> 'reading' OR from_utc IS NOT NULL),
    CHECK (scope <> 'window' OR (from_utc IS NOT NULL AND until_utc IS NOT NULL AND from_utc <= until_utc))
);
CREATE INDEX IF NOT EXISTS idx_device_exclusions_owner ON device_exclusions(owner_user_id, revoked_at);
