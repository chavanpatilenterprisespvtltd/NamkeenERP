CREATE TABLE IF NOT EXISTS finished_goods_lot (
  fg_lot_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  warehouse_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  product_master_id TEXT NOT NULL,
  sku_id TEXT NULL,
  fg_lot_code TEXT NOT NULL,
  mfg_date TEXT NOT NULL,
  expiry_date TEXT NULL,
  quantity NUMERIC NOT NULL,
  available_qty NUMERIC NOT NULL,
  uom TEXT NOT NULL,
  qc_status TEXT NOT NULL DEFAULT 'RELEASED',
  status TEXT NOT NULL DEFAULT 'AVAILABLE',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fg_lot_batch ON finished_goods_lot(batch_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fg_lot_code ON finished_goods_lot(organization_id, entity_id, fg_lot_code);
CREATE INDEX IF NOT EXISTS ix_fg_lot_scope ON finished_goods_lot(entity_id, location_id, warehouse_id, product_master_id);
