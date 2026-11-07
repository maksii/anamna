CREATE TABLE IF NOT EXISTS clinical_findings (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    report_id TEXT REFERENCES reports(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    health_area TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_en TEXT NOT NULL,
    original_text TEXT NOT NULL,
    finding_date TEXT,
    vendor_id TEXT REFERENCES vendors(id),
    status TEXT NOT NULL CHECK (status IN ('stable', 'attention', 'information')),
    confidence REAL NOT NULL DEFAULT 0,
    verification_status TEXT NOT NULL DEFAULT 'extracted',
    created_at TEXT NOT NULL,
    UNIQUE(document_id, page_number, health_area, title)
);

CREATE INDEX IF NOT EXISTS idx_findings_owner_area_date
    ON clinical_findings(owner_user_id, health_area, finding_date DESC);
CREATE INDEX IF NOT EXISTS idx_findings_document_page
    ON clinical_findings(document_id, page_number);
