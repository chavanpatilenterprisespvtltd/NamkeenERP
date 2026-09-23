-- v75: master-data administration, approvals and audit control.
CREATE TABLE IF NOT EXISTS master_change_request (
    request_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    entity_id UUID NULL,
    master_type VARCHAR(64) NOT NULL,
    master_id UUID NULL,
    action VARCHAR(32) NOT NULL,
    payload_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_APPROVAL',
    requested_by UUID NOT NULL,
    approved_by UUID NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ NULL,
    decision_reason TEXT NULL,
    client_event_id VARCHAR(128) NULL,
    CONSTRAINT ck_master_change_status CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED')),
    CONSTRAINT ck_master_change_action CHECK (action IN ('CREATE','UPDATE','DEACTIVATE')),
    CONSTRAINT uq_master_change_client_event UNIQUE (organization_id, client_event_id)
);
CREATE INDEX IF NOT EXISTS ix_master_change_org_status ON master_change_request (organization_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS ix_master_change_type_master ON master_change_request (organization_id, master_type, master_id);

CREATE TABLE IF NOT EXISTS master_audit_snapshot (
    snapshot_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    master_id UUID NOT NULL,
    version_no BIGINT NOT NULL,
    data_json JSONB NOT NULL,
    changed_by UUID NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_request_id UUID NULL REFERENCES master_change_request(request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_master_snapshot_version ON master_audit_snapshot (organization_id, master_type, master_id, version_no);
CREATE INDEX IF NOT EXISTS ix_master_snapshot_lookup ON master_audit_snapshot (organization_id, master_type, master_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS master_effective_period (
    period_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    master_id UUID NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    CONSTRAINT ck_master_period_status CHECK (status IN ('DRAFT','ACTIVE','EXPIRED','INACTIVE'))
);
CREATE INDEX IF NOT EXISTS ix_master_period_lookup ON master_effective_period (organization_id, master_type, master_id, effective_from DESC);

CREATE TABLE IF NOT EXISTS master_scope_assignment (
    assignment_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    master_id UUID NOT NULL,
    scope_type VARCHAR(32) NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, master_type, master_id, scope_type, scope_id)
);
CREATE INDEX IF NOT EXISTS ix_master_scope_lookup ON master_scope_assignment (organization_id, scope_type, scope_id, master_type, active);
