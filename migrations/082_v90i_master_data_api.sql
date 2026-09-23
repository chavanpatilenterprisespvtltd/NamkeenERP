-- V90.i: master-data CRUD/API integration checkpoint.
CREATE INDEX IF NOT EXISTS ix_master_record_api_scope
    ON master_record (organization_id, master_type, entity_id, active, updated_at);
CREATE INDEX IF NOT EXISTS ix_master_change_request_api_scope
    ON master_change_request (organization_id, entity_id, status, requested_at);
