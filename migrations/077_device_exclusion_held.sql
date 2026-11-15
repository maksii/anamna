-- Rows a "not my reading" rule removed from an export whose kept copy is gone.
--
-- A rule is normally applied by re-reading the source under it, and undone the
-- same way.  When the file under sources/ no longer exists there is nothing to
-- re-read: the matching stored rows are moved here whole, and an undo moves
-- them back as they were.  Nothing else reads this table.
--
-- exclusion_id   the rule that removed the row; its undo restores it.
-- import_id      the export the row came from; removing that export removes
--                what was held for it.
-- source_table   device_metric_days, device_workouts or device_events.
-- row_json       the full row, column name to value.
CREATE TABLE device_exclusion_held (
    id INTEGER PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exclusion_id TEXT NOT NULL REFERENCES device_exclusions(id) ON DELETE CASCADE,
    import_id TEXT NOT NULL REFERENCES device_imports(id) ON DELETE CASCADE,
    source_table TEXT NOT NULL
        CHECK (source_table IN ('device_metric_days', 'device_workouts', 'device_events')),
    row_json TEXT NOT NULL
);
CREATE INDEX idx_device_exclusion_held_rule ON device_exclusion_held(exclusion_id);
CREATE INDEX idx_device_exclusion_held_import ON device_exclusion_held(import_id);
