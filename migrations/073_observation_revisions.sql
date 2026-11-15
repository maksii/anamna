-- A cross-process cache stamp for edits that preserve row count/created_at.
CREATE TABLE observation_revisions (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TRIGGER observation_revision_insert AFTER INSERT ON observations
WHEN NEW.owner_user_id IS NOT NULL BEGIN
    INSERT INTO observation_revisions(owner_user_id, revision)
    VALUES (NEW.owner_user_id, 1)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER observation_revision_delete AFTER DELETE ON observations
WHEN OLD.owner_user_id IS NOT NULL BEGIN
    INSERT INTO observation_revisions(owner_user_id, revision)
    SELECT OLD.owner_user_id, 1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER observation_revision_update AFTER UPDATE ON observations BEGIN
    INSERT INTO observation_revisions(owner_user_id, revision)
    SELECT NEW.owner_user_id, 1 WHERE NEW.owner_user_id IS NOT NULL
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO observation_revisions(owner_user_id, revision)
    SELECT OLD.owner_user_id, 1 WHERE OLD.owner_user_id IS NOT NULL
        AND OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;
