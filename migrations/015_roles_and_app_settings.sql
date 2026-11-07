-- Two roles, because two is what the instance actually distinguishes: the
-- person who runs it and the people who have an account on it.  A roles table
-- with a join table would model permissions nobody has asked for; a CHECK
-- constraint keeps the column honest and costs nothing.
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
    CHECK (role IN ('user', 'admin'));

-- "Last seen" cannot be read from `sessions`: rows there are deleted on sign
-- out and on expiry, so the only accounts with one are those signed in right
-- now, and everyone else would read as never having visited.
ALTER TABLE users ADD COLUMN last_login_at TEXT;

-- Seeded from the newest session that is still open, so an account with live
-- sessions does not read "signed in now: 3" beside "last sign-in: never" until
-- the next time somebody happens to sign in.  Accounts with none stay NULL,
-- which is the honest answer rather than a fabricated date.
UPDATE users SET last_login_at = (
    SELECT MAX(s.created_at) FROM sessions s WHERE s.user_id = users.id
) WHERE last_login_at IS NULL;

-- The earliest account is the one that set the instance up, so it owns it.
-- Naming an email here would bake one machine's fixture into every clone.
UPDATE users SET role = 'admin'
 WHERE id = (SELECT id FROM users ORDER BY created_at, rowid LIMIT 1);

-- Instance-wide switches.  Key/value rather than a column per flag: the next
-- toggle is an INSERT, not a migration.  Absent key means "use the default in
-- the code", so a fresh database needs no seed row.
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
