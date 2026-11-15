-- Structured, portable source links for clinical arithmetic. NULL denotes
-- a reported value or an older calculation awaiting its normal refresh.
ALTER TABLE observations ADD COLUMN calculation_inputs_json TEXT;
