-- v79: production-grade bulk master import/export audit layer
CREATE TABLE IF NOT EXISTS bulk_master_import_batch (
    batch_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    requested_by UUID NOT NULL,
    file_name TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    source_format VARCHAR(16) NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'PREVIEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ NULL,
    applied_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_bulk_master_import_org_status ON bulk_master_import_batch(organization_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS bulk_master_import_row (
    batch_id UUID NOT NULL,
    row_number INTEGER NOT NULL,
    action VARCHAR(16) NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    master_id UUID NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_code VARCHAR(64) NULL,
    validation_message TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, row_number),
    FOREIGN KEY (batch_id) REFERENCES bulk_master_import_batch(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bulk_master_export_run (
    export_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    requested_by UUID NOT NULL,
    master_type VARCHAR(64) NOT NULL,
    output_format VARCHAR(16) NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    content_sha256 CHAR(64) NULL,
    output_ref TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_bulk_master_export_org_type ON bulk_master_export_run(organization_id, master_type, created_at DESC);
