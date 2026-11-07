-- Narrative findings carry the report's conclusion in the language it was
-- written in: `summary_en` held Ukrainian text on every row, so the English
-- page showed Ukrainian under an English label.  `summary_uk` takes the
-- Ukrainian wording, `summary_en` is left empty unless the source is English,
-- and the UI labels an untranslated original as such.  `recommendations` is
-- the report's own «Рекомендовано» block; `attention_reasons` names the
-- explanation families (comma-separated) that made a conclusion `attention`.
-- All three are rebuilt by health.sync_clinical_findings on start-up.
ALTER TABLE clinical_findings ADD COLUMN summary_uk TEXT NOT NULL DEFAULT '';
ALTER TABLE clinical_findings ADD COLUMN recommendations TEXT NOT NULL DEFAULT '';
ALTER TABLE clinical_findings ADD COLUMN attention_reasons TEXT NOT NULL DEFAULT '';
