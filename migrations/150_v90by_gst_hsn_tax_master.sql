-- V90.by GST/HSN/Tax master and statutory reporting foundation.
CREATE TABLE IF NOT EXISTS hsn_tax_master (
    hsn_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, hsn_code TEXT NOT NULL,
    description TEXT, goods_or_service TEXT NOT NULL DEFAULT 'GOODS',
    effective_from TEXT, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(organization_id, hsn_code)
);
CREATE TABLE IF NOT EXISTS tax_rate_master (
    tax_rate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, hsn_id TEXT,
    tax_name TEXT NOT NULL DEFAULT 'GST', gst_rate NUMERIC NOT NULL DEFAULT 0,
    igst_rate NUMERIC NOT NULL DEFAULT 0, cgst_rate NUMERIC NOT NULL DEFAULT 0,
    sgst_rate NUMERIC NOT NULL DEFAULT 0, cess_rate NUMERIC NOT NULL DEFAULT 0,
    intra_state INTEGER NOT NULL DEFAULT 1, effective_from TEXT, effective_to TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tax_transaction_lines (
    tax_line_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    source_type TEXT NOT NULL, source_id TEXT NOT NULL, source_line_id TEXT,
    hsn_code TEXT, taxable_value NUMERIC NOT NULL DEFAULT 0, gst_rate NUMERIC NOT NULL DEFAULT 0,
    igst_value NUMERIC NOT NULL DEFAULT 0, cgst_value NUMERIC NOT NULL DEFAULT 0,
    sgst_value NUMERIC NOT NULL DEFAULT 0, cess_value NUMERIC NOT NULL DEFAULT 0,
    total_tax NUMERIC NOT NULL DEFAULT 0, place_of_supply TEXT, supply_type TEXT NOT NULL DEFAULT 'OUTWARD',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tax_reporting_periods (
    period_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
    start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
    UNIQUE(organization_id, period_key)
);
