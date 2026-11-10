-- New installations route AI requests only to providers that do not keep or
-- train on what is sent.  An installation that already has accounts keeps the
-- routing it had, so nothing that worked yesterday stops working; its
-- administrator can switch to the stricter setting on the AI page.
INSERT OR IGNORE INTO app_settings(key, value, updated_at)
SELECT 'ai_openrouter_data_collection', 'allow', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
WHERE EXISTS (SELECT 1 FROM users);
