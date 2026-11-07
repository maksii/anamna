-- The curated library also describes device metrics (blood oxygen, VO2 max,
-- resting heart rate), whose keys live in device_metric_days, not in concepts.
-- Rebuild curated_reference_rules without the concepts foreign key so one
-- table can hold guidance for both kinds of measurement.  The reference_sets
-- foreign key stays: every rule must still cite a real published source.
--
-- Migration 006 has already been applied where the database existed before
-- this file, so this had to be a separate version rather than an edit.
CREATE TABLE IF NOT EXISTS curated_reference_rules_new (
    id TEXT PRIMARY KEY,
    reference_set_id TEXT NOT NULL REFERENCES reference_sets(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL,
    label TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    unit TEXT,
    lower_bound REAL,
    upper_bound REAL,
    lower_inclusive INTEGER,
    upper_inclusive INTEGER,
    interpretation TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    sex TEXT,
    age_min_years REAL,
    age_max_years REAL
);

INSERT OR IGNORE INTO curated_reference_rules_new
    SELECT id, reference_set_id, concept_id, label, context_json, unit,
           lower_bound, upper_bound, lower_inclusive, upper_inclusive,
           interpretation, priority, notes, sex, age_min_years, age_max_years
    FROM curated_reference_rules;

DROP TABLE curated_reference_rules;
ALTER TABLE curated_reference_rules_new RENAME TO curated_reference_rules;

CREATE INDEX IF NOT EXISTS idx_curated_rules_concept
    ON curated_reference_rules(concept_id, priority DESC);
