-- Diagnoses: what the person's record says they have, the diagnoses a document
-- mentions and is waiting for the person to accept, the possible diagnoses the
-- results point to, and the last fingerprint each account's refresh saw.
--
-- diagnoses.status    'active' still applies, 'resolved' is over, 'outdated'
--                     no longer applies or was never confirmed.  An active
--                     diagnosis never has resolved_on.
-- diagnoses.certainty 'confirmed', or 'provisional': a working diagnosis
--                     written with «?» or «попередній», or the person's own
--                     suspicion.
-- diagnoses.code      an ICD-10 code (normalized, Latin letters).  Empty for a
--                     diagnosis written as words only; then name is required.
-- diagnoses.dates_approximate  1 when the dates came from a document's date
--                     rather than from the day the diagnosis was made.
-- diagnoses.origin    'person' typed by the person, 'document' accepted from a
--                     document, 'suspicion' confirmed from a possible diagnosis.
CREATE TABLE IF NOT EXISTS diagnoses (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','outdated')),
    certainty TEXT NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('confirmed','provisional')),
    diagnosed_on TEXT,
    resolved_on TEXT,
    dates_approximate INTEGER NOT NULL DEFAULT 0,
    clinician TEXT NOT NULL DEFAULT '',
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'person' CHECK (origin IN ('person','document','suspicion')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (code <> '' OR name <> ''),
    CHECK (resolved_on IS NULL OR diagnosed_on IS NULL OR diagnosed_on <= resolved_on)
);
CREATE INDEX IF NOT EXISTS idx_diagnoses_owner ON diagnoses(owner_user_id, status);

-- One row per document the diagnosis reader has looked at, so a document is
-- read once.  found is how many diagnoses the reader took from it; failed
-- documents are not recorded here and are tried again.
CREATE TABLE IF NOT EXISTS diagnosis_scans (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scanned_at TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    found INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_scans_owner ON diagnosis_scans(owner_user_id);

-- A diagnosis read from a document, not yet part of the record.
-- method      'code' when the document printed an ICD-10 code and a name we
--             could check against the catalogue; 'text' a statement of the
--             document's conclusion, word for word, with no code; 'ai' when
--             the model read it.
-- code_printed 1 when the code itself is written in the document.
-- name_key    the name casefolded with single spaces; with code it is what
--             makes two mentions of the same diagnosis one candidate.
-- timing      'now' the document prescribes or describes it as present;
--             'past' a history entry.  event_date is the date the diagnosis
--             was made when the document says so, else the document's date.
-- state       'new' waiting for the person, 'accepted' linked to a diagnosis,
--             'dismissed' never offered again (restore brings it back).
-- diagnosis_id the diagnosis an accepted candidate became part of.
CREATE TABLE IF NOT EXISTS diagnosis_candidates (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    method TEXT NOT NULL CHECK (method IN ('code','text','ai')),
    code TEXT NOT NULL DEFAULT '',
    code_printed INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    certainty TEXT NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('confirmed','provisional')),
    timing TEXT NOT NULL DEFAULT 'now' CHECK (timing IN ('now','past')),
    event_date TEXT,
    date_exact INTEGER NOT NULL DEFAULT 0,
    quote TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'new' CHECK (state IN ('new','accepted','dismissed')),
    diagnosis_id TEXT REFERENCES diagnoses(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, method, code, name_key)
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_candidates_owner ON diagnosis_candidates(owner_user_id, state);

-- A possible diagnosis: the results match a published rule (rule_id) for a
-- code the record does not already cover.
-- state       'open' shown to the person; 'muted' never shown again until
--             restored; 'confirmed' became a diagnosis (diagnosis_id);
--             'cleared' the results no longer match.
-- evidence_json the results that matched, as the rule's evidence list.
-- UNIQUE (owner_user_id, rule_id): one row per rule and person, so a rule
-- that clears and matches again reopens the same row.
CREATE TABLE IF NOT EXISTS diagnosis_suspicions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    code TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','muted','confirmed','cleared')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    diagnosis_id TEXT REFERENCES diagnoses(id) ON DELETE SET NULL,
    UNIQUE (owner_user_id, rule_id)
);

-- The fingerprint of the person's documents, diagnoses and results the last
-- time the candidates and possible diagnoses were recomputed.  A different
-- fingerprint means the work is due again; the same one means it is skipped.
CREATE TABLE IF NOT EXISTS diagnosis_refresh (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    refreshed_at TEXT NOT NULL
);

-- Which of the person's medicines and supplements (factors) belong to a
-- diagnosis, in the person's own word.  linked 1: "I take this for this
-- diagnosis".  linked 0: "not for this diagnosis", which hides a match the
-- application made from the medicine's ATC group.  No row: the ATC group
-- alone decides.
CREATE TABLE IF NOT EXISTS diagnosis_medicines (
    diagnosis_id TEXT NOT NULL REFERENCES diagnoses(id) ON DELETE CASCADE,
    factor_id TEXT NOT NULL REFERENCES factors(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked INTEGER NOT NULL CHECK (linked IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (diagnosis_id, factor_id)
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_medicines_owner ON diagnosis_medicines(owner_user_id);
