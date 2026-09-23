CREATE TABLE IF NOT EXISTS ui_build_registry (
    build_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target varchar(20) NOT NULL,
    build_version varchar(64) NOT NULL,
    release_version varchar(32) NOT NULL,
    artifact varchar(255),
    commit_sha varchar(80),
    status varchar(24) NOT NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ui_build_registry_target_created
    ON ui_build_registry(target, created_at DESC);
