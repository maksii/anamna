-- Operational honesty for three things the admin and profile pages describe.
--
-- telegram_config.last_error_at: when the error now on record was written, so
-- the admin page can put it beside last_success_at and say which is newer
-- instead of calling a bot "Active" that has not reached Telegram for weeks.
ALTER TABLE telegram_config ADD COLUMN last_error_at TEXT;

-- access_tokens.seeded: the row ensure_seeded_token keeps alive from
-- ANAMNA_AGENT_TOKEN.  Flagged so the page can say where it comes from,
-- and so a changed secret retires the previous seeded row -- and only that row:
-- a credential somebody minted by hand is never touched.  Rows created by the
-- seeder before this column existed carry its fixed label and no creator.
ALTER TABLE access_tokens ADD COLUMN seeded INTEGER NOT NULL DEFAULT 0;
UPDATE access_tokens SET seeded = 1
 WHERE kind = 'agent' AND created_by_user_id IS NULL AND label = 'Seeded agent token';

-- sessions.user_agent: written once at sign-in (never per request), so the
-- session list on /profile can tell "this phone" from "that laptop".
ALTER TABLE sessions ADD COLUMN user_agent TEXT;
