CREATE TABLE IF NOT EXISTS hr_training_course(
 training_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 course_code TEXT NOT NULL, course_name TEXT NOT NULL, skill_id TEXT, provider TEXT,
 duration_hours NUMERIC NOT NULL DEFAULT 0, mandatory BOOLEAN NOT NULL DEFAULT FALSE,
 active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,course_code));
CREATE TABLE IF NOT EXISTS hr_employee_training(
 employee_training_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 employee_id TEXT NOT NULL, training_id TEXT NOT NULL, scheduled_date DATE, completed_date DATE,
 status TEXT NOT NULL DEFAULT 'PLANNED', score NUMERIC, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,employee_id,training_id,scheduled_date));
CREATE TABLE IF NOT EXISTS hr_employee_certification(
 certification_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 employee_id TEXT NOT NULL, certification_code TEXT NOT NULL, certification_name TEXT NOT NULL,
 issued_date DATE, expiry_date DATE, status TEXT NOT NULL DEFAULT 'ACTIVE', skill_id TEXT,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hr_skill_gap_plan(
 gap_plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 plan_date DATE NOT NULL, department_id TEXT, skill_id TEXT NOT NULL, required_level INTEGER NOT NULL DEFAULT 1,
 available_count INTEGER NOT NULL DEFAULT 0, required_count INTEGER NOT NULL DEFAULT 0, gap_count INTEGER NOT NULL DEFAULT 0,
 priority TEXT NOT NULL DEFAULT 'MEDIUM', training_recommended BOOLEAN NOT NULL DEFAULT TRUE,
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,plan_date,department_id,skill_id));
CREATE TABLE IF NOT EXISTS hr_workforce_optimization(
 optimization_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 plan_date DATE NOT NULL, department_id TEXT, current_hours NUMERIC NOT NULL DEFAULT 0,
 optimized_hours NUMERIC NOT NULL DEFAULT 0, current_cost NUMERIC NOT NULL DEFAULT 0,
 optimized_cost NUMERIC NOT NULL DEFAULT 0, saving_hours NUMERIC NOT NULL DEFAULT 0,
 saving_cost NUMERIC NOT NULL DEFAULT 0, utilization_pct NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'DRAFT', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,plan_date,department_id));
