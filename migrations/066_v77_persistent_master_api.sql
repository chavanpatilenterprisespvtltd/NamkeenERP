CREATE TABLE IF NOT EXISTS master_record (
    master_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    entity_id UUID NULL,
    data JSONB NOT NULL,
    normalized_key VARCHAR(512) NULL,
    version_no INTEGER NOT NULL DEFAULT 1,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from TIMESTAMPTZ NULL,
    effective_to TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_master_record_scope ON master_record (organization_id, master_type, entity_id, active, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_master_active_key ON master_record (organization_id, master_type, entity_id, normalized_key) WHERE active = TRUE AND normalized_key IS NOT NULL AND normalized_key <> '';

CREATE TABLE IF NOT EXISTS master_change_request_v77 (
    request_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    requested_by UUID NOT NULL,
    master_id UUID NULL,
    entity_id UUID NULL,
    payload JSONB NOT NULL,
    effective_from TIMESTAMPTZ NULL,
    effective_to TIMESTAMPTZ NULL,
    base_version_no INTEGER NULL,
    client_event_id VARCHAR(128) UNIQUE NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_APPROVAL',
    rejection_reason TEXT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_master_change_request_pending ON master_change_request_v77 (organization_id, entity_id, status, requested_at DESC);

CREATE TABLE IF NOT EXISTS master_audit_snapshot_v77 (
    snapshot_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    version_no INTEGER NOT NULL,
    data JSONB NOT NULL,
    active BOOLEAN NOT NULL,
    effective_from TIMESTAMPTZ NULL,
    effective_to TIMESTAMPTZ NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by UUID NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_master_snapshot_v77 ON master_audit_snapshot_v77 (organization_id, master_id, version_no DESC);
