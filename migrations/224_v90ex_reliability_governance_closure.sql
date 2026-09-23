-- V90.ex: Reliability Governance Closure + Executive Reliability Control
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_control_snapshot(
 control_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0,
 failed_change_count INTEGER NOT NULL DEFAULT 0, repeat_failure_count INTEGER NOT NULL DEFAULT 0,
 open_feedback_count INTEGER NOT NULL DEFAULT 0, critical_exception_count INTEGER NOT NULL DEFAULT 0,
 governance_score NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_executive_control_scope ON maintenance_reliability_executive_control_snapshot(organization_id,entity_id,period_key,status,assessment);
CREATE TABLE IF NOT EXISTS maintenance_reliability_management_exception(
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 source_type TEXT NOT NULL, source_id TEXT, work_center_id TEXT, severity TEXT NOT NULL DEFAULT 'MEDIUM',
 title TEXT NOT NULL, rationale TEXT NOT NULL, recommended_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 owner_user_id TEXT, due_date DATE, resolution_note TEXT, resolved_by TEXT, resolved_at TIMESTAMP,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,source_type,source_id));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_management_exception_scope ON maintenance_reliability_management_exception(organization_id,entity_id,period_key,status,severity);
CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_closure(
 closure_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closure_score NUMERIC NOT NULL DEFAULT 0,
 unresolved_exception_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL, closure_note TEXT,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
