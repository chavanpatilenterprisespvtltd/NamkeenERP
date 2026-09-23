-- V90.el — Reliability Improvement Analytics + Preventive Maintenance Effectiveness
CREATE TABLE IF NOT EXISTS maintenance_effectiveness_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 baseline_period_key TEXT NOT NULL, work_center_id TEXT,
 current_maintenance_cost NUMERIC NOT NULL DEFAULT 0, baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 current_breakdown_hours NUMERIC NOT NULL DEFAULT 0, baseline_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 breakdown_hours_reduction NUMERIC NOT NULL DEFAULT 0, breakdown_hours_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 maintenance_cost_reduction NUMERIC NOT NULL DEFAULT 0, maintenance_cost_reduction_pct NUMERIC NOT NULL DEFAULT 0,
 preventive_orders INTEGER NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0,
 preventive_mix_pct NUMERIC NOT NULL DEFAULT 0, effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,work_center_id)
);
CREATE TABLE IF NOT EXISTS maintenance_effectiveness_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_effectiveness_scope ON maintenance_effectiveness_snapshot(organization_id,entity_id,period_key,work_center_id,status);
