CREATE TABLE IF NOT EXISTS year_end_closes (
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, financial_year TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', net_profit_loss NUMERIC NOT NULL DEFAULT 0,
 retained_earnings_ledger TEXT, prepared_by TEXT, prepared_at TIMESTAMP, closed_by TEXT, closed_at TIMESTAMP,
 reopened_by TEXT, reopened_at TIMESTAMP, reopen_reason TEXT, UNIQUE(organization_id,entity_id,financial_year)
);
CREATE TABLE IF NOT EXISTS year_end_carryforwards (
 carryforward_id TEXT PRIMARY KEY, close_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 next_period_key TEXT NOT NULL, ledger_code TEXT NOT NULL, debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(close_id,ledger_code)
);
