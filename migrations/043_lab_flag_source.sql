-- Where an observation's `vendor_interpretation` came from.
--
-- NULL: derived from the interval printed on the report (pipeline.interpretation),
-- re-derived by repair_observation_semantics on every start.
-- 'lab_record': the laboratory's own structured record flagged the value
-- (labsync, audited as `observation_flag_from_lab`).  The printed range may say
-- "in range" for a value the lab itself calls out — pH 5.5 against «5.5 - 7.0»
-- — and a re-derivation from the printed bounds must not paint it green again.
ALTER TABLE observations ADD COLUMN vendor_interpretation_source TEXT;
