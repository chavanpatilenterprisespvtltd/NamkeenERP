-- V90.cy: Advanced Production Variance & Factory Performance
CREATE TABLE IF NOT EXISTS manufacturing_variance_detail (
 variance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, batch_id TEXT NOT NULL,
 product_id TEXT NOT NULL, period_key TEXT NOT NULL, variance_type TEXT NOT NULL,
 standard_value NUMERIC NOT NULL DEFAULT 0, actual_value NUMERIC NOT NULL DEFAULT 0,
 variance_value NUMERIC NOT NULL DEFAULT 0, variance_pct NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN', reason TEXT, created_by TEXT NOT NULL, approved_by TEXT, approved_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS manufacturing_variance_corrective_action (
 action_id TEXT PRIMARY KEY, variance_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 action_text TEXT NOT NULL, owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, completed_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS manufacturing_shift_performance (
 performance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 shift_code TEXT NOT NULL, operator_ref TEXT, machine_ref TEXT, batch_count INTEGER NOT NULL DEFAULT 0,
 good_qty NUMERIC NOT NULL DEFAULT 0, wastage_qty NUMERIC NOT NULL DEFAULT 0, avg_yield_pct NUMERIC NOT NULL DEFAULT 0,
 total_variance_value NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,shift_code,operator_ref,machine_ref)
);
CREATE INDEX IF NOT EXISTS ix_mfg_var_scope ON manufacturing_variance_detail(organization_id,entity_id,period_key,product_id,variance_type);
