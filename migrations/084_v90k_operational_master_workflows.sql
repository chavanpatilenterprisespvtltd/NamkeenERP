-- V90.k: operational master workflow checkpoint.
CREATE INDEX IF NOT EXISTS ix_master_record_operational_lookup
    ON master_record (organization_id, master_type, entity_id, active, updated_at);
CREATE INDEX IF NOT EXISTS ix_master_record_operational_code
    ON master_record (organization_id, master_type, entity_id, normalized_key, active);
