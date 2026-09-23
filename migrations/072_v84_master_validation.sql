-- v84: cross-field master validation metadata and audit hooks.
CREATE TABLE IF NOT EXISTS master_validation_run (
    validation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    requested_by UUID NOT NULL,
    valid BOOLEAN NOT NULL,
    error_count INTEGER NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_master_validation_run_org_type
    ON master_validation_run (organization_id, master_type, created_at DESC);
