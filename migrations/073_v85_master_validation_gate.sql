-- v85: validation results become part of the master-change control record.
-- PostgreSQL deployment migration; use JSONB for efficient inspection/querying.
CREATE TABLE IF NOT EXISTS master_validation_run (
    validation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    request_id UUID NULL,
    master_id UUID NULL,
    master_type VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('PASS','WARNING','BLOCKED')),
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    validator_version VARCHAR(32) NOT NULL DEFAULT 'v84',
    validated_by UUID NOT NULL,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome VARCHAR(32) NULL,
    note TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_master_validation_org_req ON master_validation_run (organization_id, request_id);
CREATE INDEX IF NOT EXISTS ix_master_validation_org_master ON master_validation_run (organization_id, master_id);
CREATE INDEX IF NOT EXISTS ix_master_validation_status ON master_validation_run (organization_id, status, validated_at DESC);

-- Stamp the authoritative change request with the latest validation snapshot.
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_status VARCHAR(16);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_id UUID;
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_version VARCHAR(32);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_master_change_validation_status ON master_change_request (organization_id, validation_status);
