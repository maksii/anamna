-- Reference engine, fix batch F4 (sandbox audit 2026-11-06).
--
-- notes_uk: a band's explanatory note in Ukrainian. The note was the one piece
--   of curated prose that had no Ukrainian column, so 329 Ukrainian metric
--   pages printed English notes under Ukrainian labels. Seeded from the
--   library's `uk.band_notes` (data/reference_library.json stays the source).
-- retest_condition_json: when a published retest cadence applies at all.
--   "Repeat a raised TSH after 2-3 months" is not a routine 3-month schedule;
--   staleness() reads the condition and declines the cadence when it is unmet.
-- official: whether a reference set is an official guideline. A peer-reviewed
--   review was presented under the "Official guidance" badge.
-- patients.cv_risk_category: the person's cardiovascular risk category, set on
--   the profile. LDL/non-HDL/ApoB goals are defined per category and must not
--   judge without one.
ALTER TABLE curated_reference_rules ADD COLUMN notes_uk TEXT;
ALTER TABLE concept_guidance ADD COLUMN retest_condition_json TEXT;
ALTER TABLE reference_sets ADD COLUMN official INTEGER;
ALTER TABLE patients ADD COLUMN cv_risk_category TEXT;
