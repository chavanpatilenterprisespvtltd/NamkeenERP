-- V90.al: Receivables, aging, credit utilization and collection follow-up visibility.
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS due_date DATE;
CREATE INDEX IF NOT EXISTS ix_sales_invoices_due_date ON sales_invoices(entity_id,due_date,status);
CREATE TABLE IF NOT EXISTS receivable_followups (
  followup_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  location_id TEXT,
  customer_id TEXT NOT NULL,
  follow_up_date DATE NOT NULL,
  mode TEXT NOT NULL,
  note TEXT NOT NULL,
  assigned_to_user_id TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_receivable_followups_customer ON receivable_followups(entity_id,customer_id,follow_up_date);
