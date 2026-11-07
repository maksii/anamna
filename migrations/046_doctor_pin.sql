-- A six-digit code that opens a guest session, for the doctor's office.
--
-- Not a second kind of credential: a PIN is a short way to reach the same
-- read-only guest row that /t/<secret> reaches, so scope, expiry, revocation
-- and the sessions it opens (through sessions.token_id ON DELETE CASCADE) are
-- the guest token's own.  The row's token_hash is the digest of a random
-- secret nobody is ever shown; the PIN is the only way in.
--
-- pin_hash         HMAC-SHA256 of the six digits under ANAMNA_SECRET.
--                  Keyed, because a plain hash of a 10^6 space is reversed by
--                  enumeration the moment the database leaks.
-- pin_redeem_by    the end of the short window in which the code is accepted.
-- pin_redeemed_at  set once, atomically, by the redemption that used it: a
--                  code works exactly once.
ALTER TABLE access_tokens ADD COLUMN pin_hash TEXT;
ALTER TABLE access_tokens ADD COLUMN pin_redeem_by TEXT;
ALTER TABLE access_tokens ADD COLUMN pin_redeemed_at TEXT;
CREATE INDEX IF NOT EXISTS idx_access_tokens_pin ON access_tokens(pin_hash) WHERE pin_hash IS NOT NULL;
