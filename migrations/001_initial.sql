PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    created_at TEXT NOT NULL,
    disabled_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_expiry ON sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    date_of_birth TEXT,
    sex_at_birth TEXT CHECK (sex_at_birth IN ('female', 'male', 'intersex', 'unknown') OR sex_at_birth IS NULL),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patients_owner ON patients(owner_user_id);

CREATE TABLE IF NOT EXISTS vendors (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    website TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id TEXT NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    alias TEXT NOT NULL COLLATE NOCASE,
    UNIQUE(vendor_id, alias)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    vendor_id TEXT REFERENCES vendors(id),
    original_filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    content_sha256 TEXT,
    page_count INTEGER NOT NULL,
    title TEXT NOT NULL,
    clinical_type TEXT NOT NULL,
    extraction_strategy TEXT NOT NULL,
    classification_confidence REAL NOT NULL DEFAULT 0,
    order_identifier TEXT,
    report_date TEXT,
    collected_at TEXT,
    issued_at TEXT,
    imported_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'final',
    duplicate_of_document_id TEXT REFERENCES documents(id),
    notes TEXT,
    UNIQUE(owner_user_id, sha256, original_filename)
);
CREATE INDEX IF NOT EXISTS idx_documents_owner_date ON documents(owner_user_id, report_date DESC);
CREATE INDEX IF NOT EXISTS idx_documents_patient_type ON documents(patient_id, clinical_type);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(owner_user_id, sha256);

CREATE TABLE IF NOT EXISTS document_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    native_text TEXT,
    ocr_text TEXT,
    native_text_sha256 TEXT,
    render_sha256 TEXT,
    extraction_method TEXT NOT NULL,
    native_char_count INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'not_reviewed',
    UNIQUE(document_id, page_number)
);
CREATE INDEX IF NOT EXISTS idx_pages_document ON document_pages(document_id, page_number);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'numeric',
    preferred_unit TEXT,
    coding_system TEXT,
    code TEXT,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    vendor_id TEXT REFERENCES vendors(id) ON DELETE CASCADE,
    alias TEXT NOT NULL COLLATE NOCASE,
    normalized_alias TEXT NOT NULL,
    UNIQUE(vendor_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS idx_concept_alias_normalized ON concept_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    concept_id TEXT REFERENCES concepts(id),
    raw_name TEXT NOT NULL,
    value_type TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    comparator TEXT,
    unit_raw TEXT,
    unit_canonical TEXT,
    observed_at TEXT,
    specimen TEXT,
    vendor_reference_text TEXT,
    vendor_reference_low REAL,
    vendor_reference_high REAL,
    vendor_reference_low_inclusive INTEGER,
    vendor_reference_high_inclusive INTEGER,
    vendor_interpretation TEXT,
    verification_status TEXT NOT NULL DEFAULT 'extracted',
    extraction_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    evidence_text TEXT NOT NULL,
    evidence_bbox_json TEXT,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(value_numeric IS NOT NULL OR value_text IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_observations_owner_concept_date ON observations(owner_user_id, concept_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_document_page ON observations(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_observations_review ON observations(owner_user_id, verification_status);

CREATE TABLE IF NOT EXISTS reference_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    publisher TEXT NOT NULL,
    jurisdiction TEXT,
    version TEXT,
    effective_from TEXT,
    effective_to TEXT,
    source_url TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS curated_reference_rules (
    id TEXT PRIMARY KEY,
    reference_set_id TEXT NOT NULL REFERENCES reference_sets(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    unit TEXT,
    lower_bound REAL,
    upper_bound REAL,
    lower_inclusive INTEGER,
    upper_inclusive INTEGER,
    interpretation TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_curated_rules_concept ON curated_reference_rules(concept_id, priority DESC);

CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE,
    color TEXT NOT NULL DEFAULT '#497f76',
    UNIQUE(owner_user_id, name)
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(document_id, tag_id)
);

CREATE TABLE IF NOT EXISTS observation_tags (
    observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(observation_id, tag_id)
);

CREATE TABLE IF NOT EXISTS review_tasks (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    assigned_user_id TEXT REFERENCES users(id),
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_owner_state ON review_tasks(owner_user_id, state, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_user_id TEXT REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_owner_created ON audit_events(owner_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS search_index (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_owner ON search_index(owner_user_id);
