-- V90.ek — Maintenance Reliability Cost + OEE/Production Cost Analytics
CREATE TABLE IF NOT EXISTS maintenance_reliability_cost_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 work_center_id TEXT, preventive_labour_cost NUMERIC NOT NULL DEFAULT 0, breakdown_labour_cost NUMERIC NOT NULL DEFAULT 0,
 maintenance_labour_cost NUMERIC NOT NULL DEFAULT 0, preventive_spare_cost NUMERIC NOT NULL DEFAULT 0, breakdown_spare_cost NUMERIC NOT NULL DEFAULT 0,
 maintenance_spare_cost NUMERIC NOT NULL DEFAULT 0, total_maintenance_cost NUMERIC NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 production_qty NUMERIC NOT NULL DEFAULT 0, production_labour_cost NUMERIC NOT NULL DEFAULT 0, production_total_cost NUMERIC NOT NULL DEFAULT 0,
 oee_pct NUMERIC NOT NULL DEFAULT 0, maintenance_cost_per_unit NUMERIC NOT NULL DEFAULT 0, downtime_cost_per_hour NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_pct_of_production NUMERIC NOT NULL DEFAULT 0, reliability_score NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key,work_center_id)
);
CREATE TABLE IF NOT EXISTS maintenance_reliability_cost_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_mrc_snapshot_scope ON maintenance_reliability_cost_snapshot(organization_id,entity_id,period_key,work_center_id,status);
