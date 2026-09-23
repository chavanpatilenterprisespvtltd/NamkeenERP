-- V90.as: Production KPI and Factory MIS snapshot persistence.
CREATE TABLE IF NOT EXISTS factory_kpi_snapshot (
    snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
    planned_qty NUMERIC NOT NULL DEFAULT 0, produced_good_qty NUMERIC NOT NULL DEFAULT 0,
    wastage_qty NUMERIC NOT NULL DEFAULT 0, yield_pct NUMERIC NOT NULL DEFAULT 0,
    batch_count INTEGER NOT NULL DEFAULT 0, qc_release_count INTEGER NOT NULL DEFAULT 0,
    packing_run_count INTEGER NOT NULL DEFAULT 0, packed_qty NUMERIC NOT NULL DEFAULT 0,
    dispatched_qty NUMERIC NOT NULL DEFAULT 0, invoice_value NUMERIC NOT NULL DEFAULT 0,
    production_cost NUMERIC NOT NULL DEFAULT 0, variance_cost NUMERIC NOT NULL DEFAULT 0,
    calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, calculated_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_factory_kpi_scope ON factory_kpi_snapshot(entity_id,location_id,from_date,to_date,calculated_at);
