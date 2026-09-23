CREATE TABLE IF NOT EXISTS maintenance_reliability_capa_link(
 link_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 benchmark_id TEXT, exception_id TEXT, capa_id TEXT NOT NULL, trigger_type TEXT NOT NULL,
 recurring_failure_count INTEGER NOT NULL DEFAULT 0, root_cause_summary TEXT, action_summary TEXT,
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(capa_id,trigger_type));
CREATE TABLE IF NOT EXISTS maintenance_reliability_capa_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 open_capa_count INTEGER NOT NULL DEFAULT 0, overdue_capa_count INTEGER NOT NULL DEFAULT 0,
 ineffective_capa_count INTEGER NOT NULL DEFAULT 0, effective_capa_pct NUMERIC NOT NULL DEFAULT 0,
 closure_pct NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_reliability_capa_link_period ON maintenance_reliability_capa_link(organization_id,period_key,status);
