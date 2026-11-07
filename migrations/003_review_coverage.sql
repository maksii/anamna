-- Every imported document must have an explicit human trust decision, including
-- narrative reports that intentionally produce no scalar observation.
INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, created_at)
SELECT lower(hex(randomblob(16))), d.owner_user_id, 'document', d.id,
       'Review the narrative or visual report; no structured scalar observation was inferred automatically.',
       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
FROM documents d
WHERE NOT EXISTS (
    SELECT 1 FROM review_tasks rt
    WHERE rt.entity_type='document' AND rt.entity_id=d.id
);
