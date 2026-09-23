CREATE TABLE IF NOT EXISTS erp_manufacturing_workforce_snapshot (
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 from_date TEXT NOT NULL, to_date TEXT NOT NULL, batch_count INTEGER NOT NULL DEFAULT 0, completed_batch_count INTEGER NOT NULL DEFAULT 0,
 planned_qty NUMERIC NOT NULL DEFAULT 0, captured_output_qty NUMERIC NOT NULL DEFAULT 0, labour_hours NUMERIC NOT NULL DEFAULT 0,
 productive_hours NUMERIC NOT NULL DEFAULT 0, downtime_hours NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
 labour_cost NUMERIC NOT NULL DEFAULT 0, output_per_hour NUMERIC NOT NULL DEFAULT 0, labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
 workforce_coverage_pct NUMERIC NOT NULL DEFAULT 0, productivity_index NUMERIC NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,location_id,from_date,to_date)
);
CREATE TABLE IF NOT EXISTS erp_manufacturing_workforce_actions (
 action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 batch_id TEXT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL,
 owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS ix_mfg_workforce_snapshot_scope ON erp_manufacturing_workforce_snapshot(organization_id,entity_id,location_id,to_date);
CREATE INDEX IF NOT EXISTS ix_mfg_workforce_actions_scope ON erp_manufacturing_workforce_actions(organization_id,entity_id,status,priority);
