CREATE TABLE IF NOT EXISTS hr_payroll_cost_rule(
 rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 rule_name TEXT NOT NULL, allocation_basis TEXT NOT NULL DEFAULT 'HOURS', department_id TEXT,
 production_only BOOLEAN NOT NULL DEFAULT FALSE, active BOOLEAN NOT NULL DEFAULT TRUE,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,rule_name));
CREATE TABLE IF NOT EXISTS hr_payroll_cost_allocation(
 allocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 employee_id TEXT, department_id TEXT, production_batch_id TEXT, source_amount NUMERIC NOT NULL,
 allocated_amount NUMERIC NOT NULL, basis TEXT NOT NULL, basis_value NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'ALLOCATED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(run_id,employee_id,department_id,production_batch_id));
CREATE TABLE IF NOT EXISTS hr_payroll_labour_batch_summary(
 summary_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 production_batch_id TEXT NOT NULL, labour_amount NUMERIC NOT NULL, labour_hours NUMERIC NOT NULL DEFAULT 0,
 employees_count INTEGER NOT NULL DEFAULT 0, cost_per_hour NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN', posted_journal_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(run_id,production_batch_id));
CREATE TABLE IF NOT EXISTS hr_payroll_mis_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
 run_id TEXT NOT NULL, gross_payroll NUMERIC NOT NULL, net_payroll NUMERIC NOT NULL, employer_cost NUMERIC NOT NULL,
 allocated_cost NUMERIC NOT NULL, production_labour NUMERIC NOT NULL, unallocated_cost NUMERIC NOT NULL,
 production_batches INTEGER NOT NULL DEFAULT 0, labour_hours NUMERIC NOT NULL DEFAULT 0,
 avg_labour_cost_per_hour NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
 generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_id,run_id));
