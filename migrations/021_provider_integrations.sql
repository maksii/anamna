-- Wearable provider linking (Garmin, Oura): the OAuth connection a person
-- holds, the transient state of a sign-in attempt in flight, and the raw
-- webhook arrivals. Contract and registration URLs: docs/provider-integrations.md.
--
-- `provider` is TEXT without a CHECK on purpose: the provider list lives in
-- code (integrations.PROVIDERS), and adding Withings later should be a code
-- change, not a migration. Client ids and secrets are app-level and live in
-- app_settings (seeded from the environment), so no table here carries them.

-- One row per (person, provider). Tokens are stored in plaintext for the same
-- reason paperless_accounts stores its token that way (019): they must be
-- replayed to the provider on every request, so a hash would make them
-- unusable. Deleting the row is disconnecting; there is no status column.
CREATE TABLE IF NOT EXISTS provider_connections (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    access_token TEXT NOT NULL DEFAULT '',
    refresh_token TEXT NOT NULL DEFAULT '',
    token_expires_at TEXT,
    external_user_id TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL DEFAULT '',
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, provider)
);

-- One in-flight OAuth attempt: written when the person presses Connect, read
-- and deleted when the provider redirects back. The state value is the CSRF
-- defence for the callback; code_verifier is the PKCE half for providers that
-- use it (Garmin). Rows older than integrations.STATE_TTL_SECONDS are dead and
-- are swept whenever the same person starts a new attempt.
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    code_verifier TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Raw webhook arrivals, insert-only at receipt time. Deliberately no user
-- foreign key: the payload arrives identified by the provider's own user id,
-- and resolving that to one of our accounts is the processing step's job —
-- a webhook handler must answer 200 in seconds, not think. processed_at NULL
-- means "not yet turned into observations"; providers redeliver, so the
-- processor must be idempotent over payload content, not over row count.
CREATE TABLE IF NOT EXISTS provider_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_provider_events_pending ON provider_events(provider, processed_at);
