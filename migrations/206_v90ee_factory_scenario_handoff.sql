-- V90.ee — Factory Scenario Comparison + Approved Scenario Handoff
CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_comparison(
 comparison_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 scenario_count INTEGER NOT NULL DEFAULT 0,
 relief_weight NUMERIC NOT NULL DEFAULT 0.50,
 load_weight NUMERIC NOT NULL DEFAULT 0.30,
 overtime_weight NUMERIC NOT NULL DEFAULT 0.20,
 recommended_scenario_id TEXT,
 approved_scenario_id TEXT,
 status TEXT NOT NULL DEFAULT 'DRAFT',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_comparison_line(
 line_id TEXT PRIMARY KEY,
 comparison_id TEXT NOT NULL,
 scenario_id TEXT NOT NULL,
 rank_no INTEGER NOT NULL,
 rank_score NUMERIC NOT NULL DEFAULT 0,
 avg_scenario_load_pct NUMERIC NOT NULL DEFAULT 0,
 avg_relief_pct NUMERIC NOT NULL DEFAULT 0,
 overtime_required_hours NUMERIC NOT NULL DEFAULT 0,
 improved_work_centers INTEGER NOT NULL DEFAULT 0,
 remaining_overloaded_work_centers INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(comparison_id,scenario_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_approval(
 approval_id TEXT PRIMARY KEY,
 comparison_id TEXT NOT NULL,
 scenario_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 decision TEXT NOT NULL,
 remarks TEXT NOT NULL DEFAULT '',
 approved_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(comparison_id,scenario_id)
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_handoff(
 handoff_id TEXT PRIMARY KEY,
 scenario_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 target_module TEXT NOT NULL DEFAULT 'MANUFACTURING_SCHEDULING',
 status TEXT NOT NULL DEFAULT 'READY',
 notes TEXT NOT NULL DEFAULT '',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_scenario_handoff_action(
 action_id TEXT PRIMARY KEY,
 handoff_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 schedule_reduction_hours NUMERIC NOT NULL DEFAULT 0,
 labour_reallocation_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_hours NUMERIC NOT NULL DEFAULT 0,
 oee_gain_pct NUMERIC NOT NULL DEFAULT 0,
 scenario_load_pct NUMERIC NOT NULL DEFAULT 0,
 overtime_required_hours NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'READY',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(handoff_id,work_center_id)
);

CREATE INDEX IF NOT EXISTS ix_factory_scenario_comparison_scope
 ON hr_factory_bottleneck_scenario_comparison(organization_id,entity_id,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS ix_factory_scenario_approval_scope
 ON hr_factory_bottleneck_scenario_approval(organization_id,entity_id,period_start,period_end,decision);
CREATE INDEX IF NOT EXISTS ix_factory_scenario_handoff_scope
 ON hr_factory_bottleneck_scenario_handoff(organization_id,entity_id,period_start,period_end,status);
