-- V90.bx operational intercompany linkage/reconciliation.
CREATE TABLE IF NOT EXISTS intercompany_operational_links (
    link_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, operation_type TEXT NOT NULL,
    operation_id TEXT NOT NULL, entity_id TEXT NOT NULL, direction TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0, value NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'POSTED', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS intercompany_reconciliation (
    reconciliation_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL UNIQUE,
    expected_value NUMERIC NOT NULL DEFAULT 0, operational_value NUMERIC NOT NULL DEFAULT 0,
    receivable_value NUMERIC NOT NULL DEFAULT 0, payable_value NUMERIC NOT NULL DEFAULT 0,
    variance_value NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'MATCHED',
    reconciled_by TEXT, reconciled_at TIMESTAMP
);
