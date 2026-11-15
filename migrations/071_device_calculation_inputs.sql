-- Calculated device values keep the exact inputs and their dates.  A profile
-- height has no measurement date; NULL preserves that limitation explicitly.
CREATE TABLE IF NOT EXISTS device_calculation_inputs (
    row_id TEXT NOT NULL REFERENCES device_metric_days(id) ON DELETE CASCADE,
    input_kind TEXT NOT NULL,
    input_id TEXT NOT NULL,
    input_day TEXT,
    input_value REAL NOT NULL,
    input_unit TEXT NOT NULL,
    PRIMARY KEY (row_id, input_kind)
);
-- A monotonic cache stamp, independent of source measurement timestamps.
CREATE TABLE IF NOT EXISTS device_calculation_revisions (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);
