CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    vendor_id TEXT REFERENCES vendors(id),
    title TEXT NOT NULL,
    clinical_type TEXT NOT NULL,
    report_date TEXT,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    order_identifier TEXT,
    status TEXT NOT NULL DEFAULT 'final',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_patient_date ON reports(patient_id, report_date DESC);
CREATE INDEX IF NOT EXISTS idx_reports_document_pages ON reports(document_id, start_page, end_page);

ALTER TABLE observations ADD COLUMN report_id TEXT REFERENCES reports(id);
CREATE INDEX IF NOT EXISTS idx_observations_report ON observations(report_id);

CREATE TABLE IF NOT EXISTS document_relations (
    source_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (relationship IN ('duplicate', 'reprint', 'supersedes', 'contains', 'overlaps')),
    confidence REAL NOT NULL DEFAULT 1.0,
    notes TEXT,
    PRIMARY KEY(source_document_id, target_document_id, relationship)
);
