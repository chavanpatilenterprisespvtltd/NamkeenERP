CREATE TABLE IF NOT EXISTS hr_labour_budget(
 budget_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 budget_hours NUMERIC NOT NULL DEFAULT 0, budget_cost NUMERIC NOT NULL DEFAULT 0,
 target_cost_per_unit NUMERIC NOT NULL DEFAULT 0, planned_output_qty NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id)
);

CREATE TABLE IF NOT EXISTS hr_labour_budget_actual(
 actual_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 actual_hours NUMERIC NOT NULL DEFAULT 0, actual_cost NUMERIC NOT NULL DEFAULT 0,
 actual_output_qty NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id)
);

CREATE TABLE IF NOT EXISTS hr_labour_benchmark_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 budget_hours NUMERIC NOT NULL DEFAULT 0, actual_hours NUMERIC NOT NULL DEFAULT 0,
 hours_variance NUMERIC NOT NULL DEFAULT 0, budget_cost NUMERIC NOT NULL DEFAULT 0,
 actual_cost NUMERIC NOT NULL DEFAULT 0, cost_variance NUMERIC NOT NULL DEFAULT 0,
 budget_output_qty NUMERIC NOT NULL DEFAULT 0, actual_output_qty NUMERIC NOT NULL DEFAULT 0,
 output_variance NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
 cost_variance_pct NUMERIC NOT NULL DEFAULT 0, efficiency_index_pct NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id)
);
