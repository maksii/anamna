-- A share was honoured for whoever held an account under the address it
-- named, and nothing verifies an address at sign-up: sharing with someone who
-- had no account yet handed the record to the first person to register that
-- address.  A share now names the account it was given to.
ALTER TABLE record_shares ADD COLUMN grantee_user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
UPDATE record_shares
   SET grantee_user_id = (SELECT u.id FROM users u WHERE u.email = record_shares.grantee_email COLLATE NOCASE);
-- A share addressed to nobody's account grants nothing from now on; keeping
-- the row would only keep showing the owner a share that does not exist.
DELETE FROM record_shares WHERE grantee_user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_record_shares_grantee_user ON record_shares(grantee_user_id);
