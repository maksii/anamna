-- A delivery that cannot be processed is retried on every webhook and every
-- scheduler pass.  Counting the tries lets a poisoned one be set aside instead
-- of being retried forever and holding up everything queued behind it.
ALTER TABLE provider_events ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE provider_events ADD COLUMN last_error TEXT;
