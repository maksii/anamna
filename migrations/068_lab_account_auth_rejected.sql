-- When the lab last refused this account's stored sign-in (a check or a sync
-- that ended in an authentication error).  NULL while the sign-in works; set
-- back to NULL by a new sign-in, a successful check or a successful sync.
-- The Connections tab reads it to offer "sign in again" in place.
ALTER TABLE lab_accounts ADD COLUMN auth_rejected_at TEXT;
