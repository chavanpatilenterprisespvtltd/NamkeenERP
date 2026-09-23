-- V90.eh — Factory Execution Benefit Realization + Bottleneck Closure Analytics
CREATE TABLE IF NOT EXISTS hr_factory_execution_benefit_realization(
 realization_id TEXT PRIMARY KEY,
 reconciliation_id TEXT NOT NULL,
 execution_id TEXT NOT NULL,
 scenario_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN',
 planned_bottleneck_relief_pct NUMERIC NOT NULL DEFAULT 0,
 realized_bottleneck_relief_pct NUMERIC NOT NULL DEFAULT 0,
 planned_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 actual_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 planned_hours_reduction NUMERIC NOT NULL DEFAULT 0,
 actual_hours_reduction NUMERIC NOT NULL DEFAULT 0,
 planned_capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 realized_capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 benefit_score_pct NUMERIC NOT NULL DEFAULT 0,
 closure_status TEXT NOT NULL DEFAULT 'OPEN',
 notes TEXT NOT NULL DEFAULT '',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 closed_by TEXT,
 closed_at TIMESTAMP,
 UNIQUE(reconciliation_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_execution_benefit_realization_line(
 realization_line_id TEXT PRIMARY KEY,
 realization_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 planned_load_pct NUMERIC NOT NULL DEFAULT 0,
 realized_load_pct NUMERIC NOT NULL DEFAULT 0,
 planned_relief_pct NUMERIC NOT NULL DEFAULT 0,
 realized_relief_pct NUMERIC NOT NULL DEFAULT 0,
 planned_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 realized_overtime_hours NUMERIC NOT NULL DEFAULT 0,
 planned_hours_reduction NUMERIC NOT NULL DEFAULT 0,
 actual_hours_reduction NUMERIC NOT NULL DEFAULT 0,
 planned_capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 realized_capacity_gap_hours NUMERIC NOT NULL DEFAULT 0,
 benefit_score_pct NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(realization_id,work_center_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_execution_benefit_close(
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

CREATE INDEX IF NOT EXISTS ix_factory_benefit_scope
 ON hr_factory_execution_benefit_realization(organization_id,entity_id,period_start,period_end,status,closure_status);
CREATE INDEX IF NOT EXISTS ix_factory_benefit_line
 ON hr_factory_execution_benefit_realization_line(realization_id,work_center_id,status);
