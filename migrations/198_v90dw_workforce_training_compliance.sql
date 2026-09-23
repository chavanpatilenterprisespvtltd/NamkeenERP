CREATE TABLE IF NOT EXISTS hr_training_effectiveness(
 effectiveness_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 training_id TEXT NOT NULL, employee_id TEXT, period_id TEXT, department_id TEXT,
 baseline_output_per_hour NUMERIC NOT NULL DEFAULT 0, post_output_per_hour NUMERIC NOT NULL DEFAULT 0,
 output_improvement_pct NUMERIC NOT NULL DEFAULT 0, baseline_labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 post_labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0, cost_improvement_pct NUMERIC NOT NULL DEFAULT 0,
 baseline_efficiency_pct NUMERIC NOT NULL DEFAULT 0, post_efficiency_pct NUMERIC NOT NULL DEFAULT 0,
 effectiveness_score NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
 completed_date DATE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,training_id,employee_id,period_id));

CREATE TABLE IF NOT EXISTS hr_certification_compliance_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 certification_id TEXT NOT NULL, employee_id TEXT NOT NULL, certification_code TEXT NOT NULL,
 expiry_date DATE, days_to_expiry INTEGER, compliance_status TEXT NOT NULL,
 checked_on DATE NOT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,certification_id,checked_on));
