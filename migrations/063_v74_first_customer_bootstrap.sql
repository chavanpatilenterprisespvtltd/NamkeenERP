-- v74: first-customer bootstrap ledger and release metadata.
CREATE TABLE IF NOT EXISTS customer_bootstrap_runs (
    bootstrap_run_id UUID PRIMARY KEY,
    organization_id UUID NULL,
    release_version VARCHAR(32) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    seed_sha256 CHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    initiated_by UUID NULL,
    notes TEXT NULL
);

CREATE INDEX IF NOT EXISTS ix_customer_bootstrap_runs_org_started
    ON customer_bootstrap_runs (organization_id, started_at DESC);
