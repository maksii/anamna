-- Upgrade installations that applied 027 before its owner-cleanup trigger was
-- included. IF NOT EXISTS also makes this safe for fresh installations.
CREATE TRIGGER IF NOT EXISTS ow_receipt_last_owner_deleted
AFTER DELETE ON openwearables_receipt_targets
WHEN NOT EXISTS (SELECT 1 FROM openwearables_receipt_targets WHERE receipt_id=OLD.receipt_id)
BEGIN
    UPDATE openwearables_receipts SET body=X'',status='unlinked' WHERE id=OLD.receipt_id;
END;

-- Reconcile any payload whose last owning account was deleted before this
-- trigger existed. Unsupported but owned events have targets and are retained.
UPDATE openwearables_receipts SET body=X'',status='unlinked'
WHERE length(body)>0 AND NOT EXISTS (
    SELECT 1 FROM openwearables_receipt_targets t WHERE t.receipt_id=openwearables_receipts.id
);
