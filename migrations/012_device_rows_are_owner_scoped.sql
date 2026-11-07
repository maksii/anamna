-- A device measurement belongs to the person, not to the file it arrived in.
--
-- Every device row was unique per `import_id`, and `import_id` is derived from
-- the SHA-256 of the export. That makes re-uploading the *same* export
-- idempotent and re-uploading the *next* one a duplication event -- which is
-- backwards, because a vendor export is cumulative. Apple Health's February
-- export contains every day January's did. A person who exports monthly, as
-- Apple's own instructions suggest, got a second copy of every overlapping
-- day, workout and ECG on the second upload, a third on the third, and a
-- record whose size grew with the square of how carefully they used it.
--
-- The natural key of a daily metric is (person, source, metric, day): "on that
-- day, that device measured that". Which export delivered it is provenance,
-- and provenance lives in `import_id`, not in the identity. Same for a workout
-- (a device cannot start two identical workouts at one instant) and for an
-- event (a watch cannot record two ECGs at one instant).
--
-- `source_file` is deliberately absent from the event key. It is an absolute
-- path into the directory an upload was expanded into, and that directory name
-- carries the upload's job id -- so the same ECG read from a second copy of
-- the same zip had a different "identity" every time.
--
-- These indexes are strictly stronger than the UNIQUE(import_id, ...) table
-- constraints already in place: all rows of one import share one owner, so
-- anything the new index admits the old one admits too. The old constraints
-- become redundant rather than wrong, and SQLite does not have to rebuild
-- three tables to be rid of them.

DELETE FROM device_metric_days WHERE rowid NOT IN (
    SELECT MAX(rowid) FROM device_metric_days
    GROUP BY owner_user_id, source_name, metric_key, day
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_device_metric_days_natural
    ON device_metric_days(owner_user_id, source_name, metric_key, day);

DELETE FROM device_workouts WHERE rowid NOT IN (
    SELECT MAX(rowid) FROM device_workouts
    GROUP BY owner_user_id, source_name, workout_type, started_at
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_device_workouts_natural
    ON device_workouts(owner_user_id, source_name, workout_type, started_at);

DELETE FROM device_events WHERE rowid NOT IN (
    SELECT MAX(rowid) FROM device_events
    GROUP BY owner_user_id, event_type, started_at, source_name
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_device_events_natural
    ON device_events(owner_user_id, event_type, started_at, source_name);
