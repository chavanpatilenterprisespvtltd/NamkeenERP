-- V90.ec — Advanced Factory Bottleneck Optimization + Capacity/Labour/OEE Planning
CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_optimization_snapshot(
 snapshot_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 work_center_id TEXT NOT NULL,
 department_id TEXT,
 machine_capacity_hours NUMERIC NOT NULL DEFAULT 0,
 scheduled_hours NUMERIC NOT NULL DEFAULT 0,
 machine_load_pct NUMERIC NOT NULL DEFAULT 0,
 labour_required_hours NUMERIC NOT NULL DEFAULT 0,
 labour_available_hours NUMERIC NOT NULL DEFAULT 0,
 labour_load_pct NUMERIC NOT NULL DEFAULT 0,
 combined_load_pct NUMERIC NOT NULL DEFAULT 0,
 capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 labour_gap_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_required_hours NUMERIC NOT NULL DEFAULT 0,
 oee_pct NUMERIC NOT NULL DEFAULT 0,
 labour_efficiency_pct NUMERIC NOT NULL DEFAULT 0,
 bottleneck_score NUMERIC NOT NULL DEFAULT 0,
 constraint_type TEXT NOT NULL DEFAULT 'NONE',
 status TEXT NOT NULL DEFAULT 'LOW',
 recommendation TEXT,
 source_bottleneck_snapshot_id TEXT,
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end,work_center_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_optimization_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end)
);

CREATE INDEX IF NOT EXISTS ix_factory_bottleneck_opt_scope
 ON hr_factory_bottleneck_optimization_snapshot(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_factory_bottleneck_opt_wc
 ON hr_factory_bottleneck_optimization_snapshot(organization_id,entity_id,work_center_id,status);
