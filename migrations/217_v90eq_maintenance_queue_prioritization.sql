-- V90.eq: Risk-weighted maintenance work-order prioritization
CREATE TABLE IF NOT EXISTS maintenance_priority_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 work_center_id TEXT, risk_score NUMERIC NOT NULL DEFAULT 0, risk_level TEXT NOT NULL DEFAULT 'LOW',
 breakdown_hours NUMERIC NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0,
 maintenance_cost NUMERIC NOT NULL DEFAULT 0, production_cost_impact NUMERIC NOT NULL DEFAULT 0,
 priority_score NUMERIC NOT NULL DEFAULT 0, priority_level TEXT NOT NULL DEFAULT 'LOW',
 recommended_response_hours INTEGER NOT NULL DEFAULT 72, recommended_action TEXT NOT NULL DEFAULT 'MONITOR',
 queue_rank INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_priority_key ON maintenance_priority_snapshot(organization_id,entity_id,period_key,work_center_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_priority_queue ON maintenance_priority_snapshot(organization_id,entity_id,period_key,priority_score DESC,queue_rank);
CREATE TABLE IF NOT EXISTS maintenance_priority_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
