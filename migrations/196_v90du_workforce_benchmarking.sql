CREATE TABLE IF NOT EXISTS hr_labour_efficiency_target(
 target_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 department_id TEXT, product_id TEXT, target_name TEXT NOT NULL,
 target_basis TEXT NOT NULL DEFAULT 'OUTPUT_PER_HOUR', target_value NUMERIC NOT NULL,
 uom TEXT, active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,department_id,product_id,target_name));

CREATE TABLE IF NOT EXISTS hr_labour_performance_benchmark(
 benchmark_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, production_batch_id TEXT,
 labour_hours NUMERIC NOT NULL DEFAULT 0, labour_cost NUMERIC NOT NULL DEFAULT 0,
 output_qty NUMERIC NOT NULL DEFAULT 0, productive_hours NUMERIC NOT NULL DEFAULT 0,
 output_per_hour NUMERIC NOT NULL DEFAULT 0, labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 utilization_pct NUMERIC NOT NULL DEFAULT 0, efficiency_pct NUMERIC NOT NULL DEFAULT 0,
 target_output_per_hour NUMERIC NOT NULL DEFAULT 0, target_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 variance_output_per_hour NUMERIC NOT NULL DEFAULT 0, variance_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,production_batch_id));

CREATE TABLE IF NOT EXISTS hr_production_labour_cost_forecast(
 forecast_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 planned_output_qty NUMERIC NOT NULL DEFAULT 0, planned_labour_hours NUMERIC NOT NULL DEFAULT 0,
 forecast_cost NUMERIC NOT NULL DEFAULT 0, cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 target_cost_per_unit NUMERIC NOT NULL DEFAULT 0, forecast_variance_cost NUMERIC NOT NULL DEFAULT 0,
 confidence_pct NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'FORECAST',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id));
