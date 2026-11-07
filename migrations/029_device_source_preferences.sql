-- Presentation preferences preserve every original measurement and its provenance.
CREATE TABLE device_source_preferences (
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preference_group TEXT NOT NULL,
    source_key TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_user_id, preference_group)
);
