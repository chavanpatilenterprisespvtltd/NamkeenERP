-- V90.cf GST reconciliation, exception and statutory export foundations.
CREATE TABLE IF NOT EXISTS gst_reconciliation_runs (
 run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'GENERATED', outward_tax NUMERIC NOT NULL DEFAULT 0, inward_tax NUMERIC NOT NULL DEFAULT 0,
 ledger_tax NUMERIC NOT NULL DEFAULT 0, variance NUMERIC NOT NULL DEFAULT 0, generated_by TEXT NOT NULL,
 generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key)
);
CREATE TABLE IF NOT EXISTS gst_reconciliation_exceptions (
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, period_key TEXT NOT NULL,
 exception_type TEXT NOT NULL, expected_value NUMERIC NOT NULL DEFAULT 0, actual_value NUMERIC NOT NULL DEFAULT 0,
 variance NUMERIC NOT NULL DEFAULT 0, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP, resolved_by TEXT,
 UNIQUE(organization_id,entity_id,period_key,exception_type)
);
