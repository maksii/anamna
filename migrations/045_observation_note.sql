-- Free text a report prints beside a reading -- Garmin's «Примітки» column --
-- kept with the reading instead of dropped.  Shown as the source printed it;
-- never judged and never part of the value.
ALTER TABLE observations ADD COLUMN note TEXT;
