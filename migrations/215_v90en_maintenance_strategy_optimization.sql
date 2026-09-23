-- V90.en — Maintenance Strategy Optimization + PM Frequency / Reliability Recommendations
CREATE TABLE IF NOT EXISTS maintenance_strategy_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
 pm_orders INTEGER NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0, repeat_breakdown_orders INTEGER NOT NULL DEFAULT 0,
 observed_pm_interval_days NUMERIC NOT NULL DEFAULT 0, recommended_pm_interval_days NUMERIC NOT NULL DEFAULT 0, interval_change_pct NUMERIC NOT NULL DEFAULT 0,
 breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0, cost_change_pct NUMERIC NOT NULL DEFAULT 0, oee_improvement_pct NUMERIC NOT NULL DEFAULT 0, strategy_score NUMERIC NOT NULL DEFAULT 0,
 recommendation TEXT NOT NULL DEFAULT 'REVIEW', confidence TEXT NOT NULL DEFAULT 'LOW', status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,work_center_id)
);
CREATE TABLE IF NOT EXISTS maintenance_strategy_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_strategy_scope ON maintenance_strategy_snapshot(organization_id,entity_id,period_key,work_center_id,status);
