ALTER TABLE patients ADD COLUMN blood_type TEXT
    CHECK (blood_type IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-') OR blood_type IS NULL);

-- Read-only grants: the owner lists the emails allowed to view their record.
CREATE TABLE IF NOT EXISTS record_shares (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grantee_email TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL,
    UNIQUE (owner_user_id, grantee_email)
);
CREATE INDEX IF NOT EXISTS idx_record_shares_grantee ON record_shares(grantee_email);
