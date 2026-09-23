CREATE TABLE IF NOT EXISTS hr_skill_master(
 skill_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 skill_code TEXT NOT NULL, skill_name TEXT NOT NULL, department_id TEXT, required_level INTEGER NOT NULL DEFAULT 1,
 active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,skill_code));
CREATE TABLE IF NOT EXISTS hr_employee_skill(
 employee_skill_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, employee_id TEXT NOT NULL,
 skill_id TEXT NOT NULL, skill_level INTEGER NOT NULL DEFAULT 1, valid_from DATE, valid_to DATE, status TEXT NOT NULL DEFAULT 'ACTIVE',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,employee_id,skill_id));
CREATE TABLE IF NOT EXISTS hr_workforce_capacity_plan(
 capacity_plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, plan_date DATE NOT NULL,
 department_id TEXT, shift_code TEXT, required_headcount INTEGER NOT NULL DEFAULT 0, available_headcount INTEGER NOT NULL DEFAULT 0,
 required_hours NUMERIC NOT NULL DEFAULT 0, available_hours NUMERIC NOT NULL DEFAULT 0, capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 skill_gap_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,plan_date,department_id,shift_code));
CREATE TABLE IF NOT EXISTS hr_labour_availability_forecast(
 availability_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, forecast_date DATE NOT NULL,
 department_id TEXT, available_headcount INTEGER NOT NULL DEFAULT 0, available_hours NUMERIC NOT NULL DEFAULT 0,
 expected_absence_hours NUMERIC NOT NULL DEFAULT 0, expected_overtime_hours NUMERIC NOT NULL DEFAULT 0, net_available_hours NUMERIC NOT NULL DEFAULT 0,
 confidence NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'FORECAST', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,forecast_date,department_id));
