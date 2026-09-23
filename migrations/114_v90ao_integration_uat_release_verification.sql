CREATE TABLE IF NOT EXISTS uat_runs (
    uat_run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT, run_name TEXT NOT NULL, status TEXT NOT NULL, total_checks INTEGER NOT NULL,
    passed_checks INTEGER NOT NULL, failed_checks INTEGER NOT NULL, executed_by TEXT NOT NULL,
    executed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, notes TEXT
);
CREATE TABLE IF NOT EXISTS uat_check_results (
    result_id TEXT PRIMARY KEY, uat_run_id TEXT NOT NULL, check_code TEXT NOT NULL,
    check_name TEXT NOT NULL, category TEXT NOT NULL, passed INTEGER NOT NULL,
    detail TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(uat_run_id, check_code)
);
CREATE TABLE IF NOT EXISTS release_readiness_checks (
    check_id TEXT PRIMARY KEY, uat_run_id TEXT NOT NULL, check_code TEXT NOT NULL,
    check_name TEXT NOT NULL, passed INTEGER NOT NULL, detail TEXT,
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(uat_run_id, check_code)
);
CREATE INDEX IF NOT EXISTS ix_uat_runs_scope ON uat_runs(entity_id, location_id, executed_at);
CREATE INDEX IF NOT EXISTS ix_uat_results_run ON uat_check_results(uat_run_id, category, passed);
CREATE INDEX IF NOT EXISTS ix_release_readiness_run ON release_readiness_checks(uat_run_id, passed);
