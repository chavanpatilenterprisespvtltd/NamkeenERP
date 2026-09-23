-- V90.ca Accounting posting and Tally adapter bridge.
CREATE TABLE IF NOT EXISTS accounting_postings (
 posting_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 source_type TEXT NOT NULL, source_id TEXT NOT NULL, posting_date TEXT,
 voucher_no TEXT NOT NULL, voucher_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'POSTED',
 debit_total NUMERIC NOT NULL DEFAULT 0, credit_total NUMERIC NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id, source_type, source_id)
);
CREATE TABLE IF NOT EXISTS accounting_posting_lines (
 line_id TEXT PRIMARY KEY, posting_id TEXT NOT NULL, ledger_code TEXT NOT NULL,
 ledger_name TEXT, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0,
 tax_component TEXT, narration TEXT
);
CREATE TABLE IF NOT EXISTS tally_export_documents (
 export_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT,
 posting_id TEXT NOT NULL, format TEXT NOT NULL DEFAULT 'TALLY_XML', payload TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(posting_id, format)
);
