-- V90.ai: Return QC disposition history. Runtime bootstrap is idempotent; this migration persists the release checkpoint.
CREATE TABLE IF NOT EXISTS return_disposition_history (
  disposition_id TEXT PRIMARY KEY,
  sales_return_id TEXT NOT NULL,
  sales_return_line_id TEXT NOT NULL,
  return_hold_id TEXT NOT NULL,
  disposition TEXT NOT NULL,
  quantity NUMERIC NOT NULL,
  reason TEXT NULL,
  approved_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_return_disposition_line ON return_disposition_history(sales_return_line_id,created_at);
