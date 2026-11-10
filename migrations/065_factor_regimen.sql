-- The dose and the schedule as data, chosen with pickers on the form.
-- dose_amount, dose_unit   how much is taken at once: 1 + 'tablet'.
-- schedule_json            how often, as JSON: {"repeat": "daily", "every": 1,
--                          "weekdays": [], "per_day": 2, "times": ["morning"],
--                          "clock": ["08:00"], "meal": "after"}; '' when not given.
-- dose and schedule stay as free text: an older entry's words, and a note.
ALTER TABLE factors ADD COLUMN dose_amount REAL;
ALTER TABLE factors ADD COLUMN dose_unit TEXT NOT NULL DEFAULT '';
ALTER TABLE factors ADD COLUMN schedule_json TEXT NOT NULL DEFAULT '';
-- An AI suggestion is now reviewed on the form before saving; nothing is kept waiting.
ALTER TABLE factors DROP COLUMN suggestion_json;
ALTER TABLE factors DROP COLUMN suggestion_at;
