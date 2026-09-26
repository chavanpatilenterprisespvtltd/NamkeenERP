-- FILE PATH: migrations/279_v90gx_master_validation_fix_forward.sql
-- V90.gx (Session CS2): fix-forward for migrations 073, 074 and 075, which cannot apply on a fresh PostgreSQL
-- database. 072 creates master_validation_run with the V84 shape; 073's CREATE TABLE IF NOT EXISTS is then
-- skipped and its index on request_id fails ("column request_id does not exist"); 074/075 depend on 073.
-- Confirmed live on PostgreSQL 16 in Session CS2. 073–075 are listed as "superseded" by 279 in
-- config/migration_manifest.json: the runner records them (same checksum, file untouched) without executing,
-- and this migration brings the schema to the exact end state 073+074+075 intended. Idempotent.
-- master_validation_run: add the V85 columns to the V84 table; V84-only NOT NULL columns become optional.
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS request_id UUID NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS master_id UUID NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS stage VARCHAR(32) NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS status VARCHAR(16) NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS errors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS payload_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS validator_version VARCHAR(32) NOT NULL DEFAULT 'v84';
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS validated_by UUID NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS outcome VARCHAR(32) NULL;
ALTER TABLE master_validation_run ADD COLUMN IF NOT EXISTS note TEXT NULL;
ALTER TABLE master_validation_run ALTER COLUMN requested_by DROP NOT NULL;
ALTER TABLE master_validation_run ALTER COLUMN valid DROP NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_master_validation_run_status') THEN
    ALTER TABLE master_validation_run ADD CONSTRAINT ck_master_validation_run_status CHECK (status IS NULL OR status IN ('PASS','WARNING','BLOCKED'));
  END IF;
END $$;
-- from 073
CREATE INDEX IF NOT EXISTS ix_master_validation_org_req ON master_validation_run (organization_id, request_id);
CREATE INDEX IF NOT EXISTS ix_master_validation_org_master ON master_validation_run (organization_id, master_id);
CREATE INDEX IF NOT EXISTS ix_master_validation_status ON master_validation_run (organization_id, status, validated_at DESC);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_status VARCHAR(16);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_id UUID;
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validation_version VARCHAR(32);
ALTER TABLE master_change_request ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_master_change_validation_status ON master_change_request (organization_id, validation_status);
-- from 074
CREATE INDEX IF NOT EXISTS ix_master_change_request_validation_queue ON master_change_request (organization_id, status, validation_status, requested_at DESC);
CREATE INDEX IF NOT EXISTS ix_master_validation_request_stage ON master_validation_run (organization_id, request_id, stage, validated_at DESC);
COMMENT ON COLUMN master_change_request.validation_status IS 'Latest server validation state: PASS, WARNING or BLOCKED.';
COMMENT ON COLUMN master_change_request.validation_id IS 'Latest validation-run identifier applied to this request.';
-- 075 only repeats ix_master_change_request_validation_queue (created above).
