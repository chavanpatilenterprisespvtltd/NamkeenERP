CREATE TABLE IF NOT EXISTS packing_run (
  packing_run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, source_fg_lot_id TEXT NOT NULL,
  sku_id TEXT NOT NULL, run_no TEXT NOT NULL, source_qty NUMERIC NOT NULL,
  packed_qty NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT',
  started_at timestamptz NULL, completed_at timestamptz NULL, created_by TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), notes TEXT NULL
);
CREATE TABLE IF NOT EXISTS packing_material_consumption (
  consumption_id TEXT PRIMARY KEY, packing_run_id TEXT NOT NULL, material_master_id TEXT NOT NULL,
  lot_id TEXT NULL, quantity NUMERIC NOT NULL, uom TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), FOREIGN KEY(packing_run_id) REFERENCES packing_run(packing_run_id)
);
CREATE TABLE IF NOT EXISTS packed_fg_lot (
  packed_fg_lot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, packing_run_id TEXT NOT NULL,
  source_fg_lot_id TEXT NOT NULL, sku_id TEXT NOT NULL, lot_code TEXT NOT NULL,
  pack_count NUMERIC NOT NULL, net_qty NUMERIC NOT NULL, available_qty NUMERIC NOT NULL,
  uom TEXT NOT NULL, mfg_date timestamptz NOT NULL, expiry_date timestamptz NULL,
  status TEXT NOT NULL DEFAULT 'AVAILABLE', qc_status TEXT NOT NULL DEFAULT 'RELEASED',
  created_by TEXT NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_packing_run_no ON packing_run(organization_id,entity_id,run_no);
CREATE UNIQUE INDEX IF NOT EXISTS ux_packed_fg_lot_code ON packed_fg_lot(organization_id,entity_id,lot_code);
CREATE UNIQUE INDEX IF NOT EXISTS ux_packed_fg_run ON packed_fg_lot(packing_run_id);
CREATE INDEX IF NOT EXISTS ix_packing_run_scope ON packing_run(entity_id,location_id,warehouse_id,status);
