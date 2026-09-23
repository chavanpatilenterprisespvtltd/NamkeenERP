-- V90.eb — Workforce + Machine bottleneck analytics
CREATE TABLE IF NOT EXISTS hr_workforce_bottleneck_snapshot(
 snapshot_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_start DATE NOT NULL, period_end DATE NOT NULL,
 work_center_id TEXT NOT NULL, department_id TEXT, product_id TEXT,
 labour_efficiency_pct NUMERIC NOT NULL DEFAULT 0,
 oee_pct NUMERIC NOT NULL DEFAULT 0,
 combined_efficiency_score NUMERIC NOT NULL DEFAULT 0,
 labour_oee_gap NUMERIC NOT NULL DEFAULT 0,
 labour_hours NUMERIC NOT NULL DEFAULT 0,
 output_qty NUMERIC NOT NULL DEFAULT 0,
 labour_cost NUMERIC NOT NULL DEFAULT 0,
 output_per_labour_hour NUMERIC NOT NULL DEFAULT 0,
 labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 downtime_minutes NUMERIC NOT NULL DEFAULT 0,
 downtime_pct NUMERIC NOT NULL DEFAULT 0,
 rank_no INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'WATCH' CHECK(status IN ('SEVERE_BOTTLENECK','BOTTLENECK','WATCH','HEALTHY')),
 labour_weight NUMERIC NOT NULL DEFAULT 0.5,
 oee_weight NUMERIC NOT NULL DEFAULT 0.5,
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end,work_center_id)
);
CREATE TABLE IF NOT EXISTS hr_workforce_bottleneck_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_start DATE NOT NULL, period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end)
);
CREATE INDEX IF NOT EXISTS ix_hr_workforce_bottleneck_scope
 ON hr_workforce_bottleneck_snapshot(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_hr_workforce_bottleneck_wc
 ON hr_workforce_bottleneck_snapshot(organization_id,entity_id,work_center_id);
