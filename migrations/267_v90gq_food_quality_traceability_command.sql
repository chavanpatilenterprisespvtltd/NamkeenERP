CREATE TABLE IF NOT EXISTS erp_food_quality_traceability_snapshot (
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 from_date TEXT NOT NULL, to_date TEXT NOT NULL, batches_reviewed INTEGER NOT NULL DEFAULT 0,
 inspections_reviewed INTEGER NOT NULL DEFAULT 0, released_batches INTEGER NOT NULL DEFAULT 0,
 held_batches INTEGER NOT NULL DEFAULT 0, failed_inspections INTEGER NOT NULL DEFAULT 0,
 open_nc INTEGER NOT NULL DEFAULT 0, open_capa INTEGER NOT NULL DEFAULT 0,
 traceable_batches INTEGER NOT NULL DEFAULT 0, traceability_pct NUMERIC NOT NULL DEFAULT 0,
 release_readiness_pct NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,location_id,from_date,to_date)
);
CREATE TABLE IF NOT EXISTS erp_food_quality_traceability_actions (
 action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 batch_id TEXT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL,
 owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS ix_fqt_snapshot_scope ON erp_food_quality_traceability_snapshot(organization_id,entity_id,location_id,to_date);
CREATE INDEX IF NOT EXISTS ix_fqt_actions_scope ON erp_food_quality_traceability_actions(organization_id,entity_id,status,priority);
