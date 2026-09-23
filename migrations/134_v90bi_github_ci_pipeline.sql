CREATE TABLE IF NOT EXISTS ci_pipeline_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_key varchar(120) NOT NULL,
    commit_sha varchar(80) NOT NULL,
    branch varchar(255),
    trigger varchar(40) NOT NULL,
    status varchar(30) NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    test_count integer,
    failure_count integer,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_ci_pipeline_runs_status_started
    ON ci_pipeline_runs(status, started_at DESC);
