-- Indexes for the lookups the intake and review pages make on every request.
--
-- Each one is a column that a page filters or joins on and that had no index:
-- a document's upload job, the audit trail of one entity, the review task that
-- belongs to one entity, the findings of one report, and the parser issue
-- reports raised against one observation.  Plain statements only: the runner
-- wraps each migration in its own transaction.
CREATE INDEX IF NOT EXISTS idx_upload_jobs_document ON upload_jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, action);
CREATE INDEX IF NOT EXISTS idx_review_tasks_entity ON review_tasks(owner_user_id, entity_type, entity_id, state);
CREATE INDEX IF NOT EXISTS idx_clinical_findings_report ON clinical_findings(report_id);
CREATE INDEX IF NOT EXISTS idx_parser_issue_reports_observation ON parser_issue_reports(observation_id);
