-- V90.ef — Manufacturing Scheduling Execution from Approved Scenario
CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution(
 execution_id TEXT PRIMARY KEY,
 handoff_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'PROPOSED',
 proposal_line_count INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '',
 created_by TEXT NOT NULL,
 approved_by TEXT,
 approved_at TIMESTAMP,
 executed_by TEXT,
 executed_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution_line(
 line_id TEXT PRIMARY KEY,
 execution_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 schedule_id TEXT NOT NULL,
 original_planned_qty NUMERIC NOT NULL DEFAULT 0,
 original_required_hours NUMERIC NOT NULL DEFAULT 0,
 proposed_planned_qty NUMERIC NOT NULL DEFAULT 0,
 proposed_required_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_hours NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'PROPOSED',
 executed_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(execution_id,schedule_id)
);

CREATE TABLE IF NOT EXISTS manufacturing_scenario_overtime(
 overtime_id TEXT PRIMARY KEY,
 execution_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 overtime_hours NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'PROPOSED',
 executed_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(execution_id,work_center_id)
);

CREATE TABLE IF NOT EXISTS manufacturing_scenario_execution_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end)
);

CREATE INDEX IF NOT EXISTS ix_scenario_execution_scope
 ON manufacturing_scenario_execution(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_scenario_execution_line_scope
 ON manufacturing_scenario_execution_line(execution_id,work_center_id,status);
CREATE INDEX IF NOT EXISTS ix_scenario_overtime_scope
 ON manufacturing_scenario_overtime(execution_id,work_center_id,status);
