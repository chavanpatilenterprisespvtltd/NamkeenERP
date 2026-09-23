CREATE TABLE IF NOT EXISTS production_batch_output (
  output_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  good_qty NUMERIC NOT NULL DEFAULT 0,
  rework_qty NUMERIC NOT NULL DEFAULT 0,
  wastage_qty NUMERIC NOT NULL DEFAULT 0,
  uom TEXT NOT NULL,
  yield_pct NUMERIC NOT NULL DEFAULT 0,
  wastage_pct NUMERIC NOT NULL DEFAULT 0,
  notes TEXT,
  recorded_by TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_batch_output_batch ON production_batch_output(batch_id);
CREATE INDEX IF NOT EXISTS ix_batch_output_scope ON production_batch_output(entity_id, location_id, recorded_at);
