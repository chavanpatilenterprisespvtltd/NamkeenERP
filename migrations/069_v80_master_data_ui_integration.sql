-- v80 Master Data UI integration metadata/read indexes
CREATE INDEX IF NOT EXISTS ix_master_record_org_type_active_updated
  ON master_record (organization_id, master_type, active, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_master_change_request_org_status_requested
  ON master_change_request (organization_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS ix_master_audit_snapshot_org_master_version
  ON master_audit_snapshot (organization_id, master_id, version_no DESC);
