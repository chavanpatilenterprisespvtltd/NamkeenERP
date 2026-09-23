-- v76 application-facing hardening for master administration
ALTER TABLE master_change_request
    ADD COLUMN IF NOT EXISTS api_version VARCHAR(16) NOT NULL DEFAULT 'v76';
ALTER TABLE master_change_request
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT NULL;
CREATE INDEX IF NOT EXISTS ix_master_change_pending_entity ON master_change_request (organization_id, entity_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS ix_master_snapshot_type_changed ON master_audit_snapshot (organization_id, master_type, changed_at DESC);
