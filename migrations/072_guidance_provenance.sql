-- Preserve the complete published provenance and assay/jurisdiction caveats,
-- including concepts that intentionally have no numeric reference bands.
ALTER TABLE concept_guidance ADD COLUMN source_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE concept_guidance ADD COLUMN no_universal_target_reason TEXT;
ALTER TABLE concept_guidance ADD COLUMN no_universal_target_reason_uk TEXT;
ALTER TABLE concept_guidance ADD COLUMN jurisdiction_note TEXT;
ALTER TABLE concept_guidance ADD COLUMN jurisdiction_note_uk TEXT;
