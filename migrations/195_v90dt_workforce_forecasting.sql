CREATE TABLE IF NOT EXISTS hr_workforce_optimization_rule(
 rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 rule_code TEXT NOT NULL, rule_name TEXT NOT NULL, min_utilization_pct NUMERIC NOT NULL DEFAULT 0,
 max_overtime_hours NUMERIC NOT NULL DEFAULT 0, max_capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,rule_code));

CREATE TABLE IF NOT EXISTS hr_workforce_forecast(
 forecast_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 forecast_date DATE NOT NULL, department_id TEXT, shift_code TEXT,
 required_hours NUMERIC NOT NULL DEFAULT 0, available_hours NUMERIC NOT NULL DEFAULT 0,
 forecast_hours NUMERIC NOT NULL DEFAULT 0, required_headcount INTEGER NOT NULL DEFAULT 0,
 available_headcount INTEGER NOT NULL DEFAULT 0, headcount_gap INTEGER NOT NULL DEFAULT 0,
 capacity_gap_hours NUMERIC NOT NULL DEFAULT 0, forecast_cost NUMERIC NOT NULL DEFAULT 0,
 confidence_pct NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'FORECAST',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,forecast_date,department_id,shift_code));

CREATE TABLE IF NOT EXISTS hr_workforce_optimization_result(
 result_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 plan_date DATE NOT NULL, department_id TEXT, current_hours NUMERIC NOT NULL DEFAULT 0,
 optimized_hours NUMERIC NOT NULL DEFAULT 0, current_cost NUMERIC NOT NULL DEFAULT 0,
 optimized_cost NUMERIC NOT NULL DEFAULT 0, saving_hours NUMERIC NOT NULL DEFAULT 0,
 saving_cost NUMERIC NOT NULL DEFAULT 0, utilization_pct NUMERIC NOT NULL DEFAULT 0,
 rule_id TEXT, status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,plan_date,department_id));
