-- V90.gv: controlled exception, reconciliation and approval records for mobile transaction execution.
CREATE TABLE IF NOT EXISTS mobile_transaction_exceptions (
    exception_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NULL,
    transaction_type TEXT NOT NULL,
    reference_type TEXT NULL,
    reference_id TEXT NULL,
    exception_code TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'MEDIUM',
    status TEXT NOT NULL DEFAULT 'OPEN',
    retryable INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    resolution_note TEXT NULL,
    raised_at TEXT NOT NULL,
    resolved_at TEXT NULL,
    raised_by TEXT NOT NULL,
    resolved_by TEXT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mobile_exception_key ON mobile_transaction_exceptions(integration_id, exception_code);
CREATE INDEX IF NOT EXISTS ix_mobile_exception_scope ON mobile_transaction_exceptions(entity_id,location_id,status,severity,raised_at);
CREATE INDEX IF NOT EXISTS ix_mobile_exception_ref ON mobile_transaction_exceptions(reference_type,reference_id,status);
