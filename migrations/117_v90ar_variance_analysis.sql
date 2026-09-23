-- V90.ar: Production variance, yield, wastage, BOM/material and packaging variance analysis.
CREATE TABLE IF NOT EXISTS production_variance_report (
    variance_report_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, batch_id TEXT NOT NULL, production_order_id TEXT NOT NULL,
    product_master_id TEXT NOT NULL, planned_qty NUMERIC NOT NULL, actual_good_qty NUMERIC NOT NULL,
    expected_good_qty NUMERIC NOT NULL, actual_wastage_qty NUMERIC NOT NULL, expected_wastage_qty NUMERIC NOT NULL,
    yield_variance_qty NUMERIC NOT NULL, yield_variance_pct NUMERIC NOT NULL,
    wastage_variance_qty NUMERIC NOT NULL, wastage_variance_pct NUMERIC NOT NULL,
    material_variance_cost NUMERIC NOT NULL, packaging_variance_cost NUMERIC NOT NULL,
    total_variance_cost NUMERIC NOT NULL, status TEXT NOT NULL DEFAULT 'CALCULATED',
    calculated_by TEXT NOT NULL, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id)
);
CREATE TABLE IF NOT EXISTS production_variance_component (
    variance_component_id TEXT PRIMARY KEY, variance_report_id TEXT NOT NULL,
    component_type TEXT NOT NULL, item_master_id TEXT NOT NULL, uom TEXT NOT NULL,
    standard_qty NUMERIC NOT NULL, actual_qty NUMERIC NOT NULL, variance_qty NUMERIC NOT NULL,
    unit_rate NUMERIC NOT NULL, variance_cost NUMERIC NOT NULL, variance_pct NUMERIC NOT NULL,
    notes TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(variance_report_id) REFERENCES production_variance_report(variance_report_id)
);
CREATE INDEX IF NOT EXISTS ix_prod_variance_scope ON production_variance_report(entity_id, location_id, calculated_at);
CREATE INDEX IF NOT EXISTS ix_prod_variance_comp_report ON production_variance_component(variance_report_id, component_type);
