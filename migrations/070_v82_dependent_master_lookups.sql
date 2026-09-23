-- v82: dependent lookup/read-model indexes
CREATE INDEX IF NOT EXISTS ix_master_record_org_type_active_code
ON master_record (organization_id, master_type, active);
CREATE INDEX IF NOT EXISTS ix_master_record_org_type_updated
ON master_record (organization_id, master_type, updated_at DESC);
