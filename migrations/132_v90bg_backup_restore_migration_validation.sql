CREATE TABLE IF NOT EXISTS erp_backup_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    backup_type VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL,
    release_version VARCHAR(32) NOT NULL,
    migration_target INTEGER NOT NULL,
    file_path TEXT,
    file_size_bytes BIGINT,
    sha256 CHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_erp_backup_runs_status_started
    ON erp_backup_runs(status, started_at DESC);
