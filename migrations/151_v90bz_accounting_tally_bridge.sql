-- V90.bz configurable accounting/Tally bridge foundation.
CREATE TABLE IF NOT EXISTS accounting_ledger_map (
 mapping_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
 source_key TEXT NOT NULL, ledger_code TEXT NOT NULL, ledger_name TEXT,
 active INTEGER NOT NULL DEFAULT 1, UNIQUE(organization_id, entity_id, source_key)
);
CREATE TABLE IF NOT EXISTS accounting_export_batches (
 batch_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
 export_format TEXT NOT NULL DEFAULT 'TALLY_XML', status TEXT NOT NULL DEFAULT 'DRAFT',
 period_key TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 exported_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS accounting_export_lines (
 export_line_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, source_type TEXT NOT NULL,
 source_id TEXT NOT NULL, voucher_type TEXT NOT NULL, voucher_no TEXT NOT NULL,
 debit_ledger TEXT NOT NULL, credit_ledger TEXT NOT NULL, amount NUMERIC NOT NULL DEFAULT 0,
 tax_ledger TEXT, narration TEXT, UNIQUE(batch_id, source_type, source_id)
);
