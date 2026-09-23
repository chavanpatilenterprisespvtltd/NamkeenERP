CREATE TABLE IF NOT EXISTS hr_shift_roster(
 roster_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, employee_id TEXT NOT NULL,
 work_date DATE NOT NULL, shift_code TEXT NOT NULL, planned_hours NUMERIC NOT NULL DEFAULT 0,
 department_id TEXT, status TEXT NOT NULL DEFAULT 'PLANNED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,employee_id,work_date));
CREATE TABLE IF NOT EXISTS hr_attendance_exception(
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, employee_id TEXT NOT NULL,
 work_date DATE NOT NULL, exception_type TEXT NOT NULL, expected_value NUMERIC NOT NULL DEFAULT 0, actual_value NUMERIC NOT NULL DEFAULT 0,
 variance_hours NUMERIC NOT NULL DEFAULT 0, reason TEXT, status TEXT NOT NULL DEFAULT 'OPEN', resolved_by TEXT, resolved_at TIMESTAMP,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hr_workforce_plan(
 plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, plan_date DATE NOT NULL,
 department_id TEXT, required_hours NUMERIC NOT NULL DEFAULT 0, planned_hours NUMERIC NOT NULL DEFAULT 0,
 required_headcount INTEGER NOT NULL DEFAULT 0, planned_headcount INTEGER NOT NULL DEFAULT 0,
 labour_cost_budget NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,plan_date,department_id));
CREATE TABLE IF NOT EXISTS hr_labour_cost_forecast(
 forecast_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
 department_id TEXT, planned_hours NUMERIC NOT NULL DEFAULT 0, forecast_hours NUMERIC NOT NULL DEFAULT 0,
 planned_cost NUMERIC NOT NULL DEFAULT 0, forecast_cost NUMERIC NOT NULL DEFAULT 0, variance_cost NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id));
