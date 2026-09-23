CREATE TABLE IF NOT EXISTS repack_rework_jobs (
  job_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
  warehouse_id TEXT NOT NULL, sales_return_id TEXT NOT NULL, sales_return_line_id TEXT NOT NULL,
  source_disposition TEXT NOT NULL, sku_id TEXT NOT NULL, source_lot_id TEXT NOT NULL,
  input_qty NUMERIC NOT NULL, output_qty NUMERIC NOT NULL DEFAULT 0, loss_qty NUMERIC NOT NULL DEFAULT 0,
  input_unit_cost NUMERIC NOT NULL DEFAULT 0, processing_cost NUMERIC NOT NULL DEFAULT 0,
  input_cost NUMERIC NOT NULL DEFAULT 0, total_cost NUMERIC NOT NULL DEFAULT 0, output_unit_cost NUMERIC NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'OPEN', reference_no TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
  completed_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT,
  UNIQUE(organization_id, entity_id, reference_no)
);
CREATE INDEX IF NOT EXISTS ix_repack_rework_scope ON repack_rework_jobs(entity_id,location_id,status,created_at);
CREATE INDEX IF NOT EXISTS ix_repack_rework_return_line ON repack_rework_jobs(sales_return_line_id,status);
CREATE TABLE IF NOT EXISTS return_analytics_snapshot (
  snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
  period_from TEXT NOT NULL, period_to TEXT NOT NULL, total_return_qty NUMERIC NOT NULL, return_value NUMERIC NOT NULL,
  damage_qty NUMERIC NOT NULL, damage_value NUMERIC NOT NULL, expired_qty NUMERIC NOT NULL, expired_value NUMERIC NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(organization_id,entity_id,location_id,period_from,period_to)
);
CREATE INDEX IF NOT EXISTS ix_return_snapshot_scope ON return_analytics_snapshot(entity_id,location_id,period_from,period_to);
