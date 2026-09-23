CREATE TABLE IF NOT EXISTS accounting_reconciliation_runs (
 run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 reconciliation_type TEXT NOT NULL, source_total NUMERIC NOT NULL DEFAULT 0, ledger_total NUMERIC NOT NULL DEFAULT 0,
 difference NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL, exception_reason TEXT, created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, signed_by TEXT, signed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS accounting_reconciliation_exceptions (
 exception_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 resolution TEXT, resolved_by TEXT, resolved_at TIMESTAMP
);
