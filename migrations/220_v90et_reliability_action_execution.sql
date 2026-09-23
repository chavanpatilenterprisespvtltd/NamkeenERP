-- V90.et: Reliability Action Execution + Benefit Realization
CREATE TABLE IF NOT EXISTS maintenance_reliability_action_execution(
 execution_id TEXT PRIMARY KEY,
 action_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 work_center_id TEXT,
 action_type TEXT NOT NULL,
 recommendation TEXT NOT NULL,
 owner_user_id TEXT,
 due_date DATE,
 status TEXT NOT NULL DEFAULT 'OPEN',
 execution_note TEXT,
 executed_by TEXT,
 executed_at TIMESTAMP,
 baseline_period_key TEXT,
 baseline_breakdown_orders INTEGER NOT NULL DEFAULT 0,
 baseline_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 current_breakdown_orders INTEGER NOT NULL DEFAULT 0,
 current_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 current_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
 effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 benefit_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(action_id)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_action_execution_scope
ON maintenance_reliability_action_execution(organization_id,entity_id,period_key,status,work_center_id);
CREATE TABLE IF NOT EXISTS maintenance_reliability_benefit_snapshot(
 benefit_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 baseline_period_key TEXT NOT NULL,
 work_center_id TEXT,
 breakdown_orders_baseline INTEGER NOT NULL DEFAULT 0,
 breakdown_orders_current INTEGER NOT NULL DEFAULT 0,
 breakdown_hours_baseline NUMERIC NOT NULL DEFAULT 0,
 breakdown_hours_current NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_baseline NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_current NUMERIC NOT NULL DEFAULT 0,
 breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
 effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'NO_IMPROVEMENT_OBSERVED',
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,baseline_period_key,work_center_id)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_benefit_scope
ON maintenance_reliability_benefit_snapshot(organization_id,entity_id,period_key,work_center_id,status);
CREATE TABLE IF NOT EXISTS maintenance_reliability_action_execution_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
