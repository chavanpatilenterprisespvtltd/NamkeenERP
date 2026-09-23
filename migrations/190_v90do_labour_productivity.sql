CREATE TABLE IF NOT EXISTS hr_labour_productivity_target(
 target_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 department_id TEXT, target_name TEXT NOT NULL, target_basis TEXT NOT NULL DEFAULT 'OUTPUT_PER_HOUR',
 target_value NUMERIC NOT NULL, uom TEXT, active BOOLEAN NOT NULL DEFAULT TRUE,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,target_name,department_id));
CREATE TABLE IF NOT EXISTS hr_production_labour_capture(
 capture_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 run_id TEXT NOT NULL, production_batch_id TEXT NOT NULL, employee_id TEXT, department_id TEXT,
 work_date DATE NOT NULL, labour_hours NUMERIC NOT NULL, labour_cost NUMERIC NOT NULL,
 output_qty NUMERIC NOT NULL DEFAULT 0, output_uom TEXT, downtime_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_hours NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'POSTED',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hr_labour_productivity_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, run_id TEXT NOT NULL, labour_hours NUMERIC NOT NULL,
 labour_cost NUMERIC NOT NULL, output_qty NUMERIC NOT NULL, productive_hours NUMERIC NOT NULL,
 downtime_hours NUMERIC NOT NULL, overtime_hours NUMERIC NOT NULL, cost_per_hour NUMERIC NOT NULL,
 output_per_hour NUMERIC NOT NULL, labour_cost_per_unit NUMERIC NOT NULL,
 productivity_index NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
 generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,run_id));
CREATE TABLE IF NOT EXISTS hr_labour_productivity_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id));
