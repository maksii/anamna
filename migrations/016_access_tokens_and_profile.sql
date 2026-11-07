-- Bearer credentials.
--
-- One table for three kinds rather than three tables, because they differ only
-- in what the bearer may reach, and that difference is a column:
--
--   agent  an automated caller acting as the owner -- it opens pages the way a
--          person does, so a deployment can be checked without a password
--   api    the same caller restricted to /api/*, which is the surface an
--          integration test drives and the only one that returns JSON
--   guest  a temporary read-only visitor: the patient hands a doctor a link,
--          the doctor sees the record, and the link stops working on its own
--
-- Only the SHA-256 of the secret is stored, exactly as `sessions` stores its
-- own: a database that leaks must not hand over working credentials.  `hint`
-- is the last four characters of the plaintext, which is what lets an owner
-- tell two of their own tokens apart in a list without the list holding a
-- secret.
CREATE TABLE IF NOT EXISTS access_tokens (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('agent', 'api', 'guest')),
    label TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    -- NULL means "until revoked".  A guest link is always given one; the other
    -- two kinds exist to outlive a deployment, so an expiry there is optional.
    expires_at TEXT,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_access_tokens_owner ON access_tokens(owner_user_id, kind);

-- A browser cannot send an Authorization header by following a link, so a
-- guest link has to become an ordinary session cookie.  Recording which token
-- minted the session is what keeps that session read-only afterwards -- and
-- the cascade means revoking the token closes the sessions it opened, in the
-- same statement, rather than leaving a doctor signed in to a revoked link.
ALTER TABLE sessions ADD COLUMN token_id TEXT REFERENCES access_tokens(id) ON DELETE CASCADE;

-- What the header calls you.  `display_name` is the legal-ish full name that
-- belongs on a medical record; a nickname is what a person wants to be greeted
-- by, and conflating the two forces a choice between the two audiences.
ALTER TABLE users ADD COLUMN nickname TEXT;

-- Body measurements and lifestyle context: facts a clinician asks for in the
-- first minute of a consultation and that a lab report never carries.  Stored
-- on `patients` rather than `users` because they describe the person the
-- record is about, and they are read beside `sex_at_birth` and `blood_type`
-- when a reference interval is chosen.
--
-- Numeric columns are the measured quantity in one fixed unit, so no row can
-- mean 70 kg or 70 lb depending on where it came from.  Device data outranks
-- these the way a lab blood group outranks a typed one: the application shows
-- the measurement and stops storing the manual copy while one exists.
ALTER TABLE patients ADD COLUMN height_cm REAL CHECK (height_cm IS NULL OR (height_cm > 30 AND height_cm < 280));
ALTER TABLE patients ADD COLUMN weight_kg REAL CHECK (weight_kg IS NULL OR (weight_kg > 1 AND weight_kg < 700));
ALTER TABLE patients ADD COLUMN waist_cm REAL CHECK (waist_cm IS NULL OR (waist_cm > 20 AND waist_cm < 300));
ALTER TABLE patients ADD COLUMN chest_cm REAL CHECK (chest_cm IS NULL OR (chest_cm > 20 AND chest_cm < 300));
ALTER TABLE patients ADD COLUMN hip_cm REAL CHECK (hip_cm IS NULL OR (hip_cm > 20 AND hip_cm < 300));

-- Enumerations rather than free text, so the value can be translated, compared
-- and used by a rule.  The vocabularies are the published ones: WHO physical
-- activity levels, the Fitzpatrick phototype scale, and the CDC/WHO smoking
-- and alcohol status categories -- see `profile.*_hint` in the message catalog
-- for what each one is told to the reader, with its source.
ALTER TABLE patients ADD COLUMN activity_level TEXT
    CHECK (activity_level IS NULL OR activity_level IN ('sedentary', 'light', 'moderate', 'active', 'athlete'));
ALTER TABLE patients ADD COLUMN skin_type TEXT
    CHECK (skin_type IS NULL OR skin_type IN ('I', 'II', 'III', 'IV', 'V', 'VI'));
ALTER TABLE patients ADD COLUMN smoking_status TEXT
    CHECK (smoking_status IS NULL OR smoking_status IN ('never', 'former', 'current'));
ALTER TABLE patients ADD COLUMN alcohol_use TEXT
    CHECK (alcohol_use IS NULL OR alcohol_use IN ('none', 'occasional', 'moderate', 'frequent'));
