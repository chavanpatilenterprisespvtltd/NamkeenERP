-- V90.ep: Predictive maintenance / failure-risk analytics
CREATE TABLE IF NOT EXISTS maintenance_risk_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
 breakdown_orders INTEGER NOT NULL DEFAULT 0, repeat_breakdown_orders INTEGER NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 pm_orders INTEGER NOT NULL DEFAULT 0, prior_breakdown_orders INTEGER NOT NULL DEFAULT 0, prior_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 failure_rate_per_100_orders NUMERIC NOT NULL DEFAULT 0, breakdown_growth_pct NUMERIC NOT NULL DEFAULT 0, repeat_failure_ratio_pct NUMERIC NOT NULL DEFAULT 0,
 risk_score NUMERIC NOT NULL DEFAULT 0, risk_level TEXT NOT NULL DEFAULT 'LOW', warning_signal TEXT NOT NULL DEFAULT 'NONE', recommended_action TEXT NOT NULL DEFAULT 'MONITOR',
 confidence TEXT NOT NULL DEFAULT 'LOW', status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_risk_key ON maintenance_risk_snapshot(organization_id,entity_id,period_key,work_center_id);
CREATE TABLE IF NOT EXISTS maintenance_risk_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_maintenance_risk_scope ON maintenance_risk_snapshot(organization_id,entity_id,period_key,work_center_id,risk_level,status);
