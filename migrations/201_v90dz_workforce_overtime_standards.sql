-- V90.dz — Advanced Workforce Productivity + Overtime Efficiency + Labour Standards
CREATE TABLE IF NOT EXISTS hr_labour_standard(
 standard_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 department_id TEXT, product_id TEXT, standard_basis_qty NUMERIC NOT NULL DEFAULT 1,
 standard_uom TEXT NOT NULL DEFAULT 'UNIT', standard_hours NUMERIC NOT NULL,
 standard_cost NUMERIC NOT NULL DEFAULT 0, effective_from DATE, effective_to DATE,
 active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,department_id,product_id,effective_from));

CREATE TABLE IF NOT EXISTS hr_labour_standard_performance(
 performance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, run_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 standard_id TEXT, standard_hours NUMERIC NOT NULL DEFAULT 0, actual_hours NUMERIC NOT NULL DEFAULT 0,
 regular_hours NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
 output_qty NUMERIC NOT NULL DEFAULT 0, standard_cost NUMERIC NOT NULL DEFAULT 0,
 actual_cost NUMERIC NOT NULL DEFAULT 0, hours_variance NUMERIC NOT NULL DEFAULT 0,
 cost_variance NUMERIC NOT NULL DEFAULT 0, efficiency_pct NUMERIC NOT NULL DEFAULT 0,
 overtime_hours_pct NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,run_id));

CREATE TABLE IF NOT EXISTS hr_overtime_efficiency_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 regular_hours NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
 total_hours NUMERIC NOT NULL DEFAULT 0, output_qty NUMERIC NOT NULL DEFAULT 0,
 regular_output_qty NUMERIC NOT NULL DEFAULT 0, overtime_output_qty NUMERIC NOT NULL DEFAULT 0,
 regular_output_per_hour NUMERIC NOT NULL DEFAULT 0, overtime_output_per_hour NUMERIC NOT NULL DEFAULT 0,
 overtime_efficiency_pct NUMERIC NOT NULL DEFAULT 0, overtime_cost NUMERIC NOT NULL DEFAULT 0,
 total_labour_cost NUMERIC NOT NULL DEFAULT 0, overtime_cost_pct NUMERIC NOT NULL DEFAULT 0,
 excess_overtime_hours NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id));

CREATE TABLE IF NOT EXISTS hr_workforce_dz_period_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_id));

CREATE INDEX IF NOT EXISTS ix_hr_labour_standard_scope ON hr_labour_standard(organization_id,entity_id,department_id,product_id,active);
CREATE INDEX IF NOT EXISTS ix_hr_labour_standard_performance_period ON hr_labour_standard_performance(organization_id,entity_id,period_id);
CREATE INDEX IF NOT EXISTS ix_hr_overtime_efficiency_period ON hr_overtime_efficiency_snapshot(organization_id,entity_id,period_id);
