-- V90.er: Maintenance execution feedback + risk-to-outcome learning
CREATE TABLE IF NOT EXISTS maintenance_execution_feedback_snapshot(
 feedback_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 work_center_id TEXT,
 queue_rank INTEGER NOT NULL DEFAULT 0,
 priority_level TEXT NOT NULL DEFAULT 'LOW',
 priority_score NUMERIC NOT NULL DEFAULT 0,
 risk_level TEXT NOT NULL DEFAULT 'LOW',
 risk_score NUMERIC NOT NULL DEFAULT 0,
 maintenance_orders INTEGER NOT NULL DEFAULT 0,
 intervention_orders INTEGER NOT NULL DEFAULT 0,
 intervention_events INTEGER NOT NULL DEFAULT 0,
 responded_orders INTEGER NOT NULL DEFAULT 0,
 response_hours NUMERIC NOT NULL DEFAULT 0,
 sla_hours NUMERIC NOT NULL DEFAULT 72,
 sla_compliant_orders INTEGER NOT NULL DEFAULT 0,
 sla_compliance_pct NUMERIC NOT NULL DEFAULT 0,
 breakdowns_after_intervention INTEGER NOT NULL DEFAULT 0,
 risk_hits INTEGER NOT NULL DEFAULT 0,
 false_positives INTEGER NOT NULL DEFAULT 0,
 missed_risks INTEGER NOT NULL DEFAULT 0,
 repeat_failures INTEGER NOT NULL DEFAULT 0,
 outcome_window_days INTEGER NOT NULL DEFAULT 30,
 risk_calibration_error NUMERIC NOT NULL DEFAULT 0,
 outcome_status TEXT NOT NULL DEFAULT 'OBSERVED',
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_execution_feedback_key
ON maintenance_execution_feedback_snapshot(organization_id,entity_id,period_key,work_center_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_execution_feedback_scope
ON maintenance_execution_feedback_snapshot(organization_id,entity_id,period_key,priority_level,risk_level);
CREATE TABLE IF NOT EXISTS maintenance_execution_feedback_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
