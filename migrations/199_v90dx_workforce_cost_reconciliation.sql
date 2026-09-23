CREATE TABLE IF NOT EXISTS hr_workforce_cost_reconciliation(
 reconciliation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, run_id TEXT NOT NULL,
 payroll_employer_cost NUMERIC NOT NULL DEFAULT 0, allocated_labour_cost NUMERIC NOT NULL DEFAULT 0,
 production_labour_cost NUMERIC NOT NULL DEFAULT 0, labour_budget_cost NUMERIC NOT NULL DEFAULT 0,
 payroll_to_allocation_variance NUMERIC NOT NULL DEFAULT 0,
 allocation_to_production_variance NUMERIC NOT NULL DEFAULT 0,
 budget_to_production_variance NUMERIC NOT NULL DEFAULT 0,
 payroll_allocation_variance_pct NUMERIC NOT NULL DEFAULT 0,
 production_budget_variance_pct NUMERIC NOT NULL DEFAULT 0,
 labour_hours NUMERIC NOT NULL DEFAULT 0, output_qty NUMERIC NOT NULL DEFAULT 0,
 labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,run_id));

CREATE TABLE IF NOT EXISTS hr_workforce_cost_reconciliation_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, reconciliation_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id));
