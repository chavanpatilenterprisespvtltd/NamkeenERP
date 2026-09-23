CREATE TABLE IF NOT EXISTS deployment_release_registry (
    id bigserial PRIMARY KEY,
    release_version varchar(32) NOT NULL,
    schema_target integer NOT NULL,
    environment varchar(32) NOT NULL,
    status varchar(24) NOT NULL,
    git_commit varchar(128),
    image_digest varchar(256),
    deployed_at timestamptz NOT NULL DEFAULT now(),
    notes text,
    UNIQUE (release_version, environment)
);

CREATE INDEX IF NOT EXISTS ix_deployment_release_registry_environment
    ON deployment_release_registry(environment, deployed_at DESC);
