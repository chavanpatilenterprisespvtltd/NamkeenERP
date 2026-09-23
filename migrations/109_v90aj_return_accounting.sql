-- V90.aj: Return accounting, customer credit adjustment and incentive reversal.
CREATE TABLE IF NOT EXISTS return_credit_notes (
  credit_note_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  sales_return_id TEXT NOT NULL UNIQUE,
  customer_id TEXT NOT NULL,
  credit_note_no TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'POSTED',
  subtotal NUMERIC NOT NULL DEFAULT 0,
  discount_total NUMERIC NOT NULL DEFAULT 0,
  taxable_value NUMERIC NOT NULL DEFAULT 0,
  gst_total NUMERIC NOT NULL DEFAULT 0,
  grand_total NUMERIC NOT NULL DEFAULT 0,
  reason TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS return_credit_note_lines (
  credit_note_line_id TEXT PRIMARY KEY,
  credit_note_id TEXT NOT NULL,
  sales_return_line_id TEXT NOT NULL,
  invoice_line_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  quantity NUMERIC NOT NULL,
  taxable_amount NUMERIC NOT NULL DEFAULT 0,
  gst_rate NUMERIC NOT NULL DEFAULT 0,
  gst_amount NUMERIC NOT NULL DEFAULT 0,
  line_total NUMERIC NOT NULL DEFAULT 0,
  UNIQUE(credit_note_id, sales_return_line_id)
);
CREATE TABLE IF NOT EXISTS customer_credit_adjustments (
  adjustment_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  sales_return_id TEXT NOT NULL,
  credit_note_id TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  adjustment_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'POSTED',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS incentive_reversals (
  incentive_reversal_id TEXT PRIMARY KEY,
  incentive_accrual_id TEXT NOT NULL,
  sales_return_id TEXT NOT NULL,
  sales_return_line_id TEXT NOT NULL,
  salesperson_user_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  returned_quantity NUMERIC NOT NULL,
  original_quantity NUMERIC NOT NULL,
  reversal_amount NUMERIC NOT NULL,
  status TEXT NOT NULL DEFAULT 'REVERSED',
  reason TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(incentive_accrual_id, sales_return_line_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_return_credit_note_no ON return_credit_notes(organization_id,entity_id,credit_note_no);
CREATE INDEX IF NOT EXISTS ix_return_credit_note_return ON return_credit_notes(sales_return_id,status);
CREATE INDEX IF NOT EXISTS ix_incentive_reversal_return ON incentive_reversals(sales_return_id,created_at);
