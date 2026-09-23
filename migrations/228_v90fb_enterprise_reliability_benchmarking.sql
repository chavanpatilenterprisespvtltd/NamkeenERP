CREATE TABLE IF NOT EXISTS maintenance_reliability_benchmark_snapshot(
 benchmark_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, scope_name TEXT, control_score NUMERIC NOT NULL DEFAULT 0,
 effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0, adoption_pct NUMERIC NOT NULL DEFAULT 0,
 failed_change_count INTEGER NOT NULL DEFAULT 0, repeat_failure_count INTEGER NOT NULL DEFAULT 0, benchmark_score NUMERIC NOT NULL DEFAULT 0,
 benchmark_rank INTEGER NOT NULL DEFAULT 0, peer_count INTEGER NOT NULL DEFAULT 0, benchmark_gap NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key,scope_type,scope_id));
CREATE INDEX IF NOT EXISTS ix_reliability_benchmark_scope ON maintenance_reliability_benchmark_snapshot(organization_id,period_key,scope_type,benchmark_rank,assessment);
CREATE TABLE IF NOT EXISTS maintenance_reliability_benchmark_exception(
 exception_id TEXT PRIMARY KEY, benchmark_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL, recommended_action TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN', resolved_by TEXT, resolved_at TIMESTAMP, resolution_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_reliability_benchmark_exception_scope ON maintenance_reliability_benchmark_exception(organization_id,period_key,status,severity,scope_type);
