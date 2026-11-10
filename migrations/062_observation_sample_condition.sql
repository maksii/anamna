-- What the person said about how a blood sample was taken: 'fasting' (nothing
-- but water for at least 8 hours) or 'not_fasting'.  The laboratory's printed
-- name ("Глюкоза натще") is only a hint and is not stored here.  NULL means
-- not stated, and a published band that needs a fasting sample then speaks
-- only as far as the laboratory's own range does.
ALTER TABLE observations ADD COLUMN sample_condition TEXT CHECK (sample_condition IN ('fasting', 'not_fasting'));
