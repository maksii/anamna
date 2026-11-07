-- Open review tasks can outlive their document: entity_id is not a foreign key,
-- so a removed document leaves a counter the insights page still counts.
UPDATE review_tasks
   SET state='resolved',
       resolution='orphaned',
       resolved_at=datetime('now')
 WHERE state='open'
   AND entity_type='document'
   AND NOT EXISTS (
         SELECT 1 FROM documents d
          WHERE d.id = review_tasks.entity_id
            AND d.owner_user_id = review_tasks.owner_user_id
       );
