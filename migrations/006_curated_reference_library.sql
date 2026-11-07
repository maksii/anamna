-- Curated reference library: demographic scoping for curated rules plus the
-- plain-language guidance that explains an analyte to the person reading it.
--
-- Runs exactly once per database (db.migrate keys on the integer prefix), so a
-- plain ADD COLUMN is correct here.  Everything else is IF NOT EXISTS so the
-- file is safe to re-run against a fresh database in tests.
ALTER TABLE curated_reference_rules ADD COLUMN sex TEXT;
ALTER TABLE curated_reference_rules ADD COLUMN age_min_years REAL;
ALTER TABLE curated_reference_rules ADD COLUMN age_max_years REAL;

CREATE TABLE IF NOT EXISTS concept_guidance (
    concept_id TEXT PRIMARY KEY,
    short_description TEXT,
    why_it_matters TEXT,
    retest_interval_months INTEGER,
    retest_rationale TEXT,
    panel_id TEXT,
    source_id TEXT REFERENCES reference_sets(id),
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_curated_rules_concept
    ON curated_reference_rules(concept_id, priority DESC);
