-- V90.ce statutory reporting controls; runtime schema is created idempotently by the module.
CREATE TABLE IF NOT EXISTS statutory_report_runs (
 run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
 period_key TEXT NOT NULL, report_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'GENERATED',
 generated_by TEXT NOT NULL, generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,report_type)
);
CREATE TABLE IF NOT EXISTS statutory_exceptions (
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
 period_key TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
 exception_type TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP, resolved_by TEXT,
 UNIQUE(organization_id,period_key,source_type,source_id,exception_type)
);
