-- V90.ew: Reliability Change Effectiveness + Automated Continuous-Improvement Feedback
CREATE TABLE IF NOT EXISTS maintenance_reliability_change_effectiveness_snapshot(
 effectiveness_id TEXT PRIMARY KEY, implementation_id TEXT NOT NULL, proposal_id TEXT,
 organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, work_center_id TEXT,
 target_effectiveness_score NUMERIC NOT NULL DEFAULT 60, actual_effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 target_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0, actual_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 target_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0, actual_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,
 target_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0, actual_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
 effectiveness_variance NUMERIC NOT NULL DEFAULT 0, target_met INTEGER NOT NULL DEFAULT 0,
 repeat_failure_count INTEGER NOT NULL DEFAULT 0, rollback_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED', pm_revision_status TEXT,
 failure_flag INTEGER NOT NULL DEFAULT 0, recommendation TEXT, status TEXT NOT NULL DEFAULT 'ASSESSED',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(implementation_id));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_change_effectiveness_scope ON maintenance_reliability_change_effectiveness_snapshot(organization_id,entity_id,period_key,work_center_id,status,failure_flag);
CREATE TABLE IF NOT EXISTS maintenance_reliability_improvement_feedback(
 feedback_id TEXT PRIMARY KEY, effectiveness_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL, work_center_id TEXT, feedback_type TEXT NOT NULL, recommendation TEXT NOT NULL,
 rationale TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', status TEXT NOT NULL DEFAULT 'PROPOSED',
 linked_governance_proposal_id TEXT, approved_by TEXT, approved_at TIMESTAMP,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(effectiveness_id,feedback_type));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_improvement_feedback_scope ON maintenance_reliability_improvement_feedback(organization_id,entity_id,period_key,status,priority);
CREATE TABLE IF NOT EXISTS maintenance_reliability_change_effectiveness_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
