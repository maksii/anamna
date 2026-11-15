-- Cache identity follows device data and selection rules across processes.
CREATE TABLE device_metric_revisions (
    owner_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TRIGGER device_metric_days_revision_insert AFTER INSERT ON device_metric_days
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_metric_days_revision_update AFTER UPDATE ON device_metric_days
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_metric_days_revision_delete AFTER DELETE ON device_metric_days
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_source_preferences_revision_insert AFTER INSERT ON device_source_preferences
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_source_preferences_revision_update AFTER UPDATE ON device_source_preferences
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_source_preferences_revision_delete AFTER DELETE ON device_source_preferences
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_exclusions_revision_insert AFTER INSERT ON device_exclusions
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_exclusions_revision_update AFTER UPDATE ON device_exclusions
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER device_exclusions_revision_delete AFTER DELETE ON device_exclusions
BEGIN
    INSERT INTO device_metric_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;
