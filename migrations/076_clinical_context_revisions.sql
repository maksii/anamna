-- Clinical verdicts also depend on profile and medicine context.

CREATE TRIGGER patients_clinical_revision_insert AFTER INSERT ON patients BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER patients_clinical_revision_update AFTER UPDATE ON patients BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER patients_clinical_revision_delete AFTER DELETE ON patients BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factors_clinical_revision_insert AFTER INSERT ON factors BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factors_clinical_revision_update AFTER UPDATE ON factors BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factors_clinical_revision_delete AFTER DELETE ON factors BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factor_effects_clinical_revision_insert AFTER INSERT ON factor_effects BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factor_effects_clinical_revision_update AFTER UPDATE ON factor_effects BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT NEW.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=NEW.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE OLD.owner_user_id IS NOT NEW.owner_user_id
        AND EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER factor_effects_clinical_revision_delete AFTER DELETE ON factor_effects BEGIN
    INSERT INTO observation_revisions(owner_user_id,revision)
    SELECT OLD.owner_user_id,1 WHERE EXISTS (SELECT 1 FROM users WHERE id=OLD.owner_user_id)
    ON CONFLICT(owner_user_id) DO UPDATE SET revision=revision+1;
END;
