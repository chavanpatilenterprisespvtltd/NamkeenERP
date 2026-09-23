-- v87 approval queue index
CREATE INDEX IF NOT EXISTS ix_master_change_request_validation_queue ON master_change_request (organization_id, status, validation_status, requested_at DESC);
