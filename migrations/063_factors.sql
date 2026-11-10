-- Medicines and other factors that can move a result: a medicine, a supplement,
-- an operation, an illness, a diet, a training load.  One row per factor; a
-- procedure is a single date (started_on), everything else a period.
--
-- status         'current' taken now, 'prescribed' written but not started,
--                'past' finished.  effective_status() in factors.py also
--                reports 'past' from ended_on, whatever is stored.
-- reference_*    where the reference notes came from: the site's path name
--                (reference_name), its optional product number
--                (reference_code), and the page the link opens.
-- purpose ... cautions   reference notes, written by the person or accepted
--                from an AI suggestion.  ai_fields names the ones still
--                carrying an accepted AI text the person has not changed.
-- suggestion_json  the last AI suggestion, kept until accepted or dismissed.
CREATE TABLE IF NOT EXISTS factors (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('medicine','supplement','procedure','illness','diet','activity','other')),
    name TEXT NOT NULL,
    substance TEXT NOT NULL DEFAULT '',
    atc_code TEXT NOT NULL DEFAULT '',
    strength TEXT NOT NULL DEFAULT '',
    dose TEXT NOT NULL DEFAULT '',
    schedule TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('current','prescribed','past')),
    started_on TEXT,
    ended_on TEXT,
    dates_approximate INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    prescriber TEXT NOT NULL DEFAULT '',
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    usual_dose TEXT NOT NULL DEFAULT '',
    interactions TEXT NOT NULL DEFAULT '',
    monitoring TEXT NOT NULL DEFAULT '',
    cautions TEXT NOT NULL DEFAULT '',
    ai_fields TEXT NOT NULL DEFAULT '',
    reference_source TEXT NOT NULL DEFAULT '',
    reference_name TEXT NOT NULL DEFAULT '',
    reference_code TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    suggestion_json TEXT,
    suggestion_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (ended_on IS NULL OR started_on IS NULL OR started_on <= ended_on)
);
CREATE INDEX IF NOT EXISTS idx_factors_owner ON factors(owner_user_id, status);

-- An effect is one measurable result a factor is known or suspected to move.
-- concept_id links it to the concept the charts draw; label keeps the words
-- the person (or the suggestion) used when there is no concept.
-- origin 'ai' means an AI suggestion the person accepted; evidence keeps the
-- quotation from the source it came from.
CREATE TABLE IF NOT EXISTS factor_effects (
    id TEXT PRIMARY KEY,
    factor_id TEXT NOT NULL REFERENCES factors(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id TEXT REFERENCES concepts(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('raises','lowers','changes')),
    note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL CHECK (origin IN ('person','ai')),
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_factor_effects_factor ON factor_effects(factor_id);
CREATE INDEX IF NOT EXISTS idx_factor_effects_concept ON factor_effects(owner_user_id, concept_id);

-- Planning a pregnancy is a clinical state the reference engine reads as a
-- fact; 0 unless the person says otherwise.
ALTER TABLE patients ADD COLUMN planning_pregnancy INTEGER NOT NULL DEFAULT 0;
