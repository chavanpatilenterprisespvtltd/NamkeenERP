-- Namkeen ERP v72 — release/UAT control-plane migration
CREATE TABLE IF NOT EXISTS release_runs (
    release_run_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    version TEXT NOT NULL,
    environment TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('PLANNED','RUNNING','PASSED','FAILED','ROLLED_BACK')),
    artifact_sha256 TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS migration_checks (
    migration_check_id BIGSERIAL PRIMARY KEY,
    release_run_id TEXT NOT NULL REFERENCES release_runs(release_run_id),
    migration_version TEXT NOT NULL,
    checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING','APPLIED','MATCHED','MISMATCH','SKIPPED')),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_run_id, migration_version)
);

CREATE TABLE IF NOT EXISTS uat_runs (
    uat_run_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    release_run_id TEXT NOT NULL REFERENCES release_runs(release_run_id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('PLANNED','RUNNING','PASSED','FAILED','BLOCKED')),
    tester TEXT,
    signoff_ref TEXT
);

CREATE TABLE IF NOT EXISTS go_live_gates (
    gate_id BIGSERIAL PRIMARY KEY,
    release_run_id TEXT NOT NULL REFERENCES release_runs(release_run_id),
    gate_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN','PASSED','FAILED','WAIVED')),
    owner TEXT,
    evidence_ref TEXT,
    decided_at TIMESTAMPTZ,
    reason TEXT,
    UNIQUE (release_run_id, gate_code)
);

CREATE INDEX IF NOT EXISTS idx_migration_checks_release_status ON migration_checks(release_run_id, status);
CREATE INDEX IF NOT EXISTS idx_uat_runs_org_status ON uat_runs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_go_live_gates_release_status ON go_live_gates(release_run_id, status);
