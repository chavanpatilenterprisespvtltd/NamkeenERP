-- V90.em — Preventive Maintenance ROI + Reliability Cost Optimization
CREATE TABLE IF NOT EXISTS maintenance_roi_snapshot(
 snapshot_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 baseline_period_key TEXT NOT NULL,
 work_center_id TEXT,
 current_preventive_cost NUMERIC NOT NULL DEFAULT 0,
 current_breakdown_cost NUMERIC NOT NULL DEFAULT 0,
 baseline_preventive_cost NUMERIC NOT NULL DEFAULT 0,
 baseline_breakdown_cost NUMERIC NOT NULL DEFAULT 0,
 current_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 avoided_breakdown_cost NUMERIC NOT NULL DEFAULT 0,
 preventive_cost_change NUMERIC NOT NULL DEFAULT 0,
 net_reliability_benefit NUMERIC NOT NULL DEFAULT 0,
 preventive_roi_pct NUMERIC NOT NULL DEFAULT 0,
 breakdown_hours_avoided NUMERIC NOT NULL DEFAULT 0,
 breakdown_hours_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 oee_improvement_pct NUMERIC NOT NULL DEFAULT 0,
 optimization_score NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,work_center_id)
);
CREATE TABLE IF NOT EXISTS maintenance_roi_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_roi_scope ON maintenance_roi_snapshot(organization_id,entity_id,period_key,work_center_id,status);
