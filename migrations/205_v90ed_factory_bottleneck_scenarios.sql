-- V90.ed — Factory Bottleneck Scenario Simulation + Capacity Optimization
CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario(
 scenario_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 scenario_name TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'SIMULATED',
 improved_work_centers INTEGER NOT NULL DEFAULT 0,
 remaining_overloaded_work_centers INTEGER NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_result(
 result_id TEXT PRIMARY KEY,
 scenario_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 baseline_load_pct NUMERIC NOT NULL DEFAULT 0,
 scenario_load_pct NUMERIC NOT NULL DEFAULT 0,
 baseline_oee_pct NUMERIC NOT NULL DEFAULT 0,
 scenario_oee_pct NUMERIC NOT NULL DEFAULT 0,
 baseline_labour_gap_hours NUMERIC NOT NULL DEFAULT 0,
 scenario_labour_gap_hours NUMERIC NOT NULL DEFAULT 0,
 schedule_reduction_hours NUMERIC NOT NULL DEFAULT 0,
 labour_reallocation_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_hours NUMERIC NOT NULL DEFAULT 0,
 oee_gain_pct NUMERIC NOT NULL DEFAULT 0,
 bottleneck_relief_pct NUMERIC NOT NULL DEFAULT 0,
 capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_required_hours NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'LOW',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(scenario_id,work_center_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_close(
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

CREATE INDEX IF NOT EXISTS ix_factory_bottleneck_scenario_scope
 ON hr_factory_bottleneck_scenario(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_factory_bottleneck_scenario_result
 ON hr_factory_bottleneck_scenario_result(scenario_id,scenario_load_pct,status);
