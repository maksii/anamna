-- The expected due date the person records in the profile, when they are
-- pregnant (or may be).  A result taken in the 40 weeks before it (280 days)
-- is judged as taken during pregnancy: the bands written for people who are
-- not pregnant -- thyroid, HbA1c, glucose, and the female haemoglobin and
-- haematocrit intervals -- do not judge it.  NULL means no date recorded.
ALTER TABLE patients ADD COLUMN pregnancy_due_date TEXT;
