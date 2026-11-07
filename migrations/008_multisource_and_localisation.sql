-- Multi-source citations and Ukrainian curated text.
--
-- Two changes driven by the same requirement: every interval should be backed
-- by more than one official body, and the curated text a reader sees should be
-- in their language. Curated guidance was English-only, so a Ukrainian reader
-- saw English descriptions under a Ukrainian interface.

-- Which region an authority speaks for, so the UI can show that a band is
-- backed by both a US and an EU body rather than just naming one.
ALTER TABLE reference_sets ADD COLUMN region TEXT;

-- Sources that independently agree with a rule, as a JSON array of
-- reference_sets ids. Stored on the rule rather than a join table: it is a
-- citation list, never queried by member.
ALTER TABLE curated_reference_rules ADD COLUMN corroborated_by TEXT;

-- Whether the authorities agree about this analyte at all. 'divergent' means
-- the UI must show both positions instead of choosing one.
ALTER TABLE curated_reference_rules ADD COLUMN agreement TEXT;
ALTER TABLE curated_reference_rules ADD COLUMN divergence_note TEXT;

-- Localised band label, e.g. "Prediabetes range" -> "Діапазон предіабету".
ALTER TABLE curated_reference_rules ADD COLUMN label_uk TEXT;

-- Localised guidance prose.
ALTER TABLE concept_guidance ADD COLUMN short_description_uk TEXT;
ALTER TABLE concept_guidance ADD COLUMN why_it_matters_uk TEXT;
ALTER TABLE concept_guidance ADD COLUMN retest_rationale_uk TEXT;
ALTER TABLE concept_guidance ADD COLUMN name_uk TEXT;

CREATE INDEX IF NOT EXISTS idx_reference_sets_region ON reference_sets(region);
