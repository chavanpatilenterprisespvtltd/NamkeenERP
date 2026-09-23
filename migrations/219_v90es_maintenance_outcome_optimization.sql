-- V90.es: Maintenance outcome optimization + closed-loop reliability actions
CREATE TABLE IF NOT EXISTS maintenance_outcome_optimization_snapshot(
 optimization_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 work_center_id TEXT,
 pm_orders INTEGER NOT NULL DEFAULT 0,
 corrective_orders INTEGER NOT NULL DEFAULT 0,
 pm_interventions INTEGER NOT NULL DEFAULT 0,
 corrective_interventions INTEGER NOT NULL DEFAULT 0,
 pm_successes INTEGER NOT NULL DEFAULT 0,
 corrective_successes INTEGER NOT NULL DEFAULT 0,
 post_intervention_breakdowns INTEGER NOT NULL DEFAULT 0,
 repeat_failures INTEGER NOT NULL DEFAULT 0,
 pm_success_rate NUMERIC NOT NULL DEFAULT 0,
 corrective_success_rate NUMERIC NOT NULL DEFAULT 0,
 intervention_success_rate NUMERIC NOT NULL DEFAULT 0,
 spare_usage_events INTEGER NOT NULL DEFAULT 0,
 labour_charge_events INTEGER NOT NULL DEFAULT 0,
 recommended_pm_change TEXT NOT NULL DEFAULT 'REVIEW',
 recommended_readiness_action TEXT NOT NULL DEFAULT 'REVIEW',
 reliability_opportunity_score NUMERIC NOT NULL DEFAULT 0,
 recommendation TEXT NOT NULL DEFAULT 'REVIEW',
 confidence TEXT NOT NULL DEFAULT 'LOW',
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_outcome_optimization_key
ON maintenance_outcome_optimization_snapshot(organization_id,entity_id,period_key,work_center_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_outcome_optimization_scope
ON maintenance_outcome_optimization_snapshot(organization_id,entity_id,period_key,reliability_opportunity_score DESC,status);
CREATE TABLE IF NOT EXISTS maintenance_reliability_action(
 action_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 work_center_id TEXT,
 action_type TEXT NOT NULL,
 recommendation TEXT NOT NULL,
 rationale TEXT NOT NULL,
 confidence TEXT NOT NULL DEFAULT 'LOW',
 status TEXT NOT NULL DEFAULT 'PROPOSED',
 approved_by TEXT,
 approved_at TIMESTAMP,
 decision_note TEXT,
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_action_scope
ON maintenance_reliability_action(organization_id,entity_id,period_key,status,action_type);
CREATE TABLE IF NOT EXISTS maintenance_outcome_optimization_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
