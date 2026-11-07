CREATE TABLE IF NOT EXISTS device_imports (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    vendor_id TEXT NOT NULL REFERENCES vendors(id),
    adapter_key TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    source_bytes INTEGER NOT NULL,
    export_started_at TEXT,
    export_ended_at TEXT,
    raw_record_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'complete',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL,
    UNIQUE(owner_user_id, adapter_key, source_fingerprint)
);

CREATE TABLE IF NOT EXISTS device_metric_days (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    import_id TEXT NOT NULL REFERENCES device_imports(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_vendor TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    category TEXT NOT NULL,
    day TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    unit TEXT,
    value REAL NOT NULL,
    value_min REAL,
    value_max REAL,
    value_sum REAL,
    sample_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, source_name, metric_key, day)
);
CREATE INDEX IF NOT EXISTS idx_device_metric_owner_key_day
    ON device_metric_days(owner_user_id, metric_key, day DESC);
CREATE INDEX IF NOT EXISTS idx_device_metric_patient_category_day
    ON device_metric_days(patient_id, category, day DESC);

CREATE TABLE IF NOT EXISTS device_workouts (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    import_id TEXT NOT NULL REFERENCES device_imports(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_vendor TEXT NOT NULL,
    workout_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_minutes REAL,
    energy_kcal REAL,
    distance_km REAL,
    route_file TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, source_name, workout_type, started_at)
);
CREATE INDEX IF NOT EXISTS idx_device_workouts_owner_started
    ON device_workouts(owner_user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS device_events (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    import_id TEXT NOT NULL REFERENCES device_imports(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_vendor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    value_text TEXT,
    value_numeric REAL,
    unit TEXT,
    source_file TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, event_type, started_at, source_name, source_file)
);
CREATE INDEX IF NOT EXISTS idx_device_events_owner_type_started
    ON device_events(owner_user_id, event_type, started_at DESC);
