-- Telegram is explicitly enabled by an administrator; each owner links separately.
CREATE TABLE telegram_config (
    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'polling' CHECK(mode IN ('polling','webhook')),
    bot_username TEXT NOT NULL DEFAULT '', public_url TEXT NOT NULL DEFAULT '',
    poll_offset INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
    last_error TEXT, last_success_at TEXT
);
INSERT INTO telegram_config(id) VALUES(1);
CREATE TABLE telegram_links (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    telegram_user_id INTEGER NOT NULL UNIQUE, chat_id INTEGER NOT NULL UNIQUE,
    locale TEXT NOT NULL CHECK(locale IN ('en','uk')), linked_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '', search_query TEXT NOT NULL DEFAULT ''
);
CREATE TABLE telegram_link_tokens (
    token_hash TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX idx_telegram_tokens_owner ON telegram_link_tokens(owner_user_id);
CREATE TABLE telegram_updates (
    update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, received_at REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL DEFAULT 0, error_key TEXT
);
CREATE INDEX idx_telegram_updates_pending ON telegram_updates(state,available_at);
CREATE TABLE telegram_outbox (
    id TEXT PRIMARY KEY, owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL, method TEXT NOT NULL, payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL, error_key TEXT
);
CREATE INDEX idx_telegram_outbox_pending ON telegram_outbox(state,available_at);
CREATE TABLE telegram_uploads (
    update_id INTEGER PRIMARY KEY REFERENCES telegram_updates(update_id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL, batch_id TEXT NOT NULL, notified_state TEXT NOT NULL DEFAULT ''
);
