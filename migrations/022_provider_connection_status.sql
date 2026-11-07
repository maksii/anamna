-- A connection whose refresh token was refused is not gone — the person's
-- data is still here — but it can no longer fetch anything new until they
-- reconnect. Oura refresh tokens are single-use, so one lost race or one
-- revocation at the provider strands the row silently; the status makes that
-- visible on the profile instead of looking like a ring that stopped syncing.
-- Values: 'active' | 'reauthorize'. Reconnecting overwrites the row and
-- resets it to 'active'.
ALTER TABLE provider_connections ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
