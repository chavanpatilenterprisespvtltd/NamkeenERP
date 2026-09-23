CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 action_count INTEGER NOT NULL DEFAULT 0, approved_action_count INTEGER NOT NULL DEFAULT 0, completed_action_count INTEGER NOT NULL DEFAULT 0,
 overdue_action_count INTEGER NOT NULL DEFAULT 0, assessed_action_count INTEGER NOT NULL DEFAULT 0, effective_action_count INTEGER NOT NULL DEFAULT 0,
 ineffective_action_count INTEGER NOT NULL DEFAULT 0, total_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0, maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
 action_completion_pct NUMERIC NOT NULL DEFAULT 0, benefit_assessment_pct NUMERIC NOT NULL DEFAULT 0, effectiveness_pct NUMERIC NOT NULL DEFAULT 0,
 executive_action_score NUMERIC NOT NULL DEFAULT 0, assessment TEXT NOT NULL DEFAULT 'NO_BASELINE', status TEXT NOT NULL DEFAULT 'OPEN', recommendation TEXT,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_review(
 review_id TEXT PRIMARY KEY, action_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 assessment TEXT NOT NULL, review_note TEXT NOT NULL, evidence_note TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(action_id));
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 action_count INTEGER NOT NULL DEFAULT 0, unassessed_action_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL,
 closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_reliability_exec_effectiveness_scope ON maintenance_reliability_executive_effectiveness_snapshot(organization_id,entity_id,period_key,status);
CREATE INDEX IF NOT EXISTS ix_reliability_exec_effectiveness_review ON maintenance_reliability_executive_effectiveness_review(organization_id,entity_id,period_key,assessment);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES
('maintenance_reliability_effectiveness.view','View Reliability Executive Action Effectiveness'),
('maintenance_reliability_effectiveness.manage','Review Reliability Executive Action Benefits'),
('maintenance_reliability_effectiveness.close','Close Reliability Executive Effectiveness Period') ON CONFLICT(permission_id) DO NOTHING;
