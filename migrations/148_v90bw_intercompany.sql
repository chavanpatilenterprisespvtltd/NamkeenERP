-- V90.bw configurable multi-company intercompany foundation.
CREATE TABLE IF NOT EXISTS intercompany_transactions (
    transaction_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, transaction_no TEXT NOT NULL,
    transaction_type TEXT NOT NULL, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL,
    source_location_id TEXT, target_location_id TEXT, status TEXT NOT NULL DEFAULT 'DRAFT',
    taxable_value NUMERIC NOT NULL DEFAULT 0, tax_value NUMERIC NOT NULL DEFAULT 0,
    total_value NUMERIC NOT NULL DEFAULT 0, reference_type TEXT, reference_id TEXT,
    created_by TEXT NOT NULL, approved_by TEXT, posted_by TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP, posted_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS intercompany_transaction_lines (
    line_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
    lot_id TEXT, quantity NUMERIC NOT NULL DEFAULT 0, uom TEXT NOT NULL DEFAULT 'EA',
    unit_price NUMERIC NOT NULL DEFAULT 0, taxable_value NUMERIC NOT NULL DEFAULT 0,
    tax_rate NUMERIC NOT NULL DEFAULT 0, tax_value NUMERIC NOT NULL DEFAULT 0, line_total NUMERIC NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS intercompany_accounting_entries (
    entry_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    side TEXT NOT NULL, account_code TEXT NOT NULL, amount NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
