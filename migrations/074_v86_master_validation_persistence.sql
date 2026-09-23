-- v86: persist validation state directly on master-change requests and make the
-- final approval stamp part of the same DB transaction as the master mutation.
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_status VARCHAR(16);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_id UUID;
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_version VARCHAR(32);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_master_change_request_validation_queue
    ON master_change_request (organization_id, status, validation_status, requested_at DESC);

CREATE INDEX IF NOT EXISTS ix_master_validation_request_stage
    ON master_validation_run (organization_id, request_id, stage, validated_at DESC);

COMMENT ON COLUMN master_change_request.validation_status IS
    'Latest server validation state: PASS, WARNING or BLOCKED.';
COMMENT ON COLUMN master_change_request.validation_id IS
    'Latest validation-run identifier applied to this request.';
