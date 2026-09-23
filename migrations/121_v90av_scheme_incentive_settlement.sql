CREATE TABLE IF NOT EXISTS commercial_schemes (
  scheme_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  scheme_name TEXT NOT NULL, scheme_type TEXT NOT NULL, discount_pct NUMERIC NOT NULL DEFAULT 0,
  fixed_amount NUMERIC, min_invoice_value NUMERIC, max_settlement NUMERIC,
  effective_from TEXT NOT NULL, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1,
  notes TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS discount_settlements (
  discount_settlement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL, sales_invoice_id TEXT NOT NULL, scheme_id TEXT NOT NULL,
  eligible_base NUMERIC NOT NULL, requested_discount NUMERIC NOT NULL, approved_discount NUMERIC NOT NULL,
  status TEXT NOT NULL, settlement_reference TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(sales_invoice_id, scheme_id, settlement_reference)
);
CREATE TABLE IF NOT EXISTS incentive_settlements (
  incentive_settlement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL, salesperson_user_id TEXT NOT NULL, period_from TEXT NOT NULL, period_to TEXT NOT NULL,
  gross_accrual NUMERIC NOT NULL, reversal_total NUMERIC NOT NULL, payable_amount NUMERIC NOT NULL,
  status TEXT NOT NULL, settlement_reference TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(salesperson_user_id,period_from,period_to,settlement_reference)
);
CREATE INDEX IF NOT EXISTS ix_scheme_scope ON commercial_schemes(entity_id,active,effective_from);
CREATE INDEX IF NOT EXISTS ix_discount_settlement_scope ON discount_settlements(entity_id,location_id,created_at);
CREATE INDEX IF NOT EXISTS ix_incentive_settlement_scope ON incentive_settlements(entity_id,salesperson_user_id,period_from,period_to);
