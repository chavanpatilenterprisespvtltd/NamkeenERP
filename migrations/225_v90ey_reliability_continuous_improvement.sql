-- V90.ey: Reliability Governance Learning & Cross-Period Continuous Improvement
CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_snapshot(
 learning_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 prior_period_key TEXT, current_control_score NUMERIC NOT NULL DEFAULT 0, prior_control_score NUMERIC NOT NULL DEFAULT 0,
 control_score_delta NUMERIC NOT NULL DEFAULT 0, current_effectiveness_score NUMERIC NOT NULL DEFAULT 0, prior_effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 effectiveness_delta NUMERIC NOT NULL DEFAULT 0, current_target_met_pct NUMERIC NOT NULL DEFAULT 0, prior_target_met_pct NUMERIC NOT NULL DEFAULT 0,
 target_met_delta NUMERIC NOT NULL DEFAULT 0, current_failed_change_count INTEGER NOT NULL DEFAULT 0, prior_failed_change_count INTEGER NOT NULL DEFAULT 0,
 recurring_failure_count INTEGER NOT NULL DEFAULT 0, recurring_failure_flag INTEGER NOT NULL DEFAULT 0, improvement_assessment TEXT NOT NULL DEFAULT 'NO_BASELINE',
 recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_continuous_improvement_scope ON maintenance_reliability_continuous_improvement_snapshot(organization_id,entity_id,period_key,status,recurring_failure_flag);
CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_feedback(
 feedback_id TEXT PRIMARY KEY, learning_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 prior_period_key TEXT, feedback_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', recommendation TEXT NOT NULL, rationale TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PROPOSED', linked_governance_proposal_id TEXT, owner_user_id TEXT, due_date DATE,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(learning_id,feedback_type));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_continuous_feedback_scope ON maintenance_reliability_continuous_improvement_feedback(organization_id,entity_id,period_key,status,priority);
CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', unresolved_feedback_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL,
 closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
