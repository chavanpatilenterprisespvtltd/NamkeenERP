-- V90.eg — Scenario Execution Reconciliation + Production Schedule Variance
CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution_reconciliation(
 reconciliation_id TEXT PRIMARY KEY,
 execution_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'ON_TRACK',
 original_qty NUMERIC NOT NULL DEFAULT 0,
 planned_qty NUMERIC NOT NULL DEFAULT 0,
 actual_qty NUMERIC NOT NULL DEFAULT 0,
 original_hours NUMERIC NOT NULL DEFAULT 0,
 planned_hours NUMERIC NOT NULL DEFAULT 0,
 actual_hours NUMERIC NOT NULL DEFAULT 0,
 planned_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 actual_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 qty_variance NUMERIC NOT NULL DEFAULT 0,
 hours_variance NUMERIC NOT NULL DEFAULT 0,
 overtime_variance NUMERIC NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '',
 reconciled_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 closed_by TEXT,
 closed_at TIMESTAMP,
 UNIQUE(execution_id)
);

CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution_reconciliation_line(
 reconciliation_line_id TEXT PRIMARY KEY,
 reconciliation_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 schedule_id TEXT NOT NULL,
 planned_qty NUMERIC NOT NULL DEFAULT 0,
 actual_qty NUMERIC NOT NULL DEFAULT 0,
 qty_variance NUMERIC NOT NULL DEFAULT 0,
 planned_hours NUMERIC NOT NULL DEFAULT 0,
 actual_hours NUMERIC NOT NULL DEFAULT 0,
 hours_variance NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'ON_TRACK',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(reconciliation_id,schedule_id)
);

CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution_reconciliation_exception(
 exception_id TEXT PRIMARY KEY,
 reconciliation_id TEXT NOT NULL,
 exception_type TEXT NOT NULL,
 severity TEXT NOT NULL DEFAULT 'WARNING',
 message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN',
 resolved_by TEXT,
 resolved_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_scenario_execution_recon_scope
 ON manufacturing_scenario_execution_reconciliation(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_scenario_execution_recon_line
 ON manufacturing_scenario_execution_reconciliation_line(reconciliation_id,work_center_id,status);
