BEGIN;
CREATE TABLE IF NOT EXISTS deployment_release (
    id BIGSERIAL PRIMARY KEY,
    release_code TEXT NOT NULL UNIQUE,
    schema_target TEXT NOT NULL,
    artifact_sha256 TEXT,
    deployed_at TIMESTAMPTZ,
    deployed_by TEXT,
    status TEXT NOT NULL CHECK (status IN ('PREPARED','DEPLOYED','ROLLED_BACK','FAILED')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS deployment_evidence (
    id BIGSERIAL PRIMARY KEY,
    release_id BIGINT NOT NULL REFERENCES deployment_release(id),
    evidence_type TEXT NOT NULL,
    reference TEXT NOT NULL,
    sha256 TEXT,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO deployment_release(release_code, schema_target, status)
VALUES ('v73','062','PREPARED')
ON CONFLICT (release_code) DO NOTHING;
COMMIT;
