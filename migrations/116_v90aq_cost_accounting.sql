-- V90.aq: Product cost rates and production batch cost rollup.
CREATE TABLE IF NOT EXISTS product_cost_rate (
    cost_rate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    item_master_id TEXT NOT NULL, uom TEXT NOT NULL, unit_cost NUMERIC NOT NULL,
    source_type TEXT NOT NULL, source_reference_id TEXT NULL, effective_from TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id,entity_id,item_master_id,uom,effective_from)
);
CREATE TABLE IF NOT EXISTS production_batch_cost (
    batch_cost_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, batch_id TEXT NOT NULL, production_order_id TEXT NOT NULL,
    product_master_id TEXT NOT NULL, planned_qty NUMERIC NOT NULL, actual_good_qty NUMERIC NOT NULL,
    material_cost NUMERIC NOT NULL, packaging_cost NUMERIC NOT NULL, conversion_cost NUMERIC NOT NULL DEFAULT 0,
    wastage_cost NUMERIC NOT NULL DEFAULT 0, total_cost NUMERIC NOT NULL, unit_cost NUMERIC NOT NULL,
    cost_status TEXT NOT NULL DEFAULT 'CALCULATED', calculated_by TEXT NOT NULL, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id)
);
CREATE TABLE IF NOT EXISTS production_cost_component (
    component_id TEXT PRIMARY KEY, batch_cost_id TEXT NOT NULL, component_type TEXT NOT NULL,
    item_master_id TEXT NULL, reference_id TEXT NULL, quantity NUMERIC NOT NULL, uom TEXT NOT NULL,
    unit_rate NUMERIC NOT NULL, amount NUMERIC NOT NULL, variance_pct NUMERIC NULL,
    notes TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_prod_batch_cost_entity ON production_batch_cost(entity_id,location_id,calculated_at);
CREATE INDEX IF NOT EXISTS ix_prod_cost_comp_batch ON production_cost_component(batch_cost_id,component_type);
