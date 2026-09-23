-- V90.cx: Advanced manufacturing loss, yield and by-product accounting.
CREATE TABLE IF NOT EXISTS manufacturing_loss_standard (
 standard_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 product_id TEXT NOT NULL, ingredient_id TEXT, loss_type TEXT NOT NULL,
 standard_pct NUMERIC NOT NULL DEFAULT 0, standard_qty NUMERIC NOT NULL DEFAULT 0,
 effective_from DATE NOT NULL, effective_to DATE, status TEXT NOT NULL DEFAULT 'ACTIVE',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,product_id,ingredient_id,loss_type,effective_from)
);
CREATE TABLE IF NOT EXISTS manufacturing_consumption_variance (
 variance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 batch_id TEXT NOT NULL, product_id TEXT NOT NULL, ingredient_id TEXT NOT NULL,
 standard_qty NUMERIC NOT NULL DEFAULT 0, actual_qty NUMERIC NOT NULL DEFAULT 0,
 unit_cost NUMERIC NOT NULL DEFAULT 0, variance_qty NUMERIC NOT NULL DEFAULT 0,
 variance_value NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS manufacturing_byproduct_accounting (
 byproduct_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 batch_id TEXT NOT NULL, product_id TEXT NOT NULL, byproduct_item_id TEXT NOT NULL,
 quantity NUMERIC NOT NULL DEFAULT 0, valuation_rate NUMERIC NOT NULL DEFAULT 0,
 valuation_value NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'RECORDED',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS manufacturing_yield_benchmark (
 benchmark_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 product_id TEXT NOT NULL, period_key TEXT NOT NULL, batch_count INTEGER NOT NULL DEFAULT 0,
 avg_yield_pct NUMERIC NOT NULL DEFAULT 0, best_yield_pct NUMERIC NOT NULL DEFAULT 0,
 avg_wastage_qty NUMERIC NOT NULL DEFAULT 0, avg_cost_per_kg NUMERIC NOT NULL DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,product_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_mfg_consumption_variance_scope ON manufacturing_consumption_variance(organization_id,entity_id,batch_id);
CREATE INDEX IF NOT EXISTS ix_mfg_byproduct_scope ON manufacturing_byproduct_accounting(organization_id,entity_id,batch_id);
