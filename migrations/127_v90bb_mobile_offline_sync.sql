CREATE TABLE IF NOT EXISTS sync_devices (
  device_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
  device_code TEXT NOT NULL, device_name TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'ANDROID',
  last_seen_at TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,device_code));
CREATE TABLE IF NOT EXISTS sync_operations (
  sync_operation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
  device_id TEXT NOT NULL, client_operation_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
  operation_type TEXT NOT NULL, base_version INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING', conflict_code TEXT NULL, server_version INTEGER NULL,
  received_by TEXT NOT NULL, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT NULL, resolved_by TEXT NULL,
  UNIQUE(device_id,client_operation_id));
CREATE TABLE IF NOT EXISTS sync_conflicts (
  conflict_id TEXT PRIMARY KEY, sync_operation_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  location_id TEXT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, base_version INTEGER NOT NULL,
  server_version INTEGER NOT NULL, client_payload_json TEXT NOT NULL, server_payload_json TEXT NOT NULL,
  resolution TEXT NULL, resolved_by TEXT NULL, resolved_at TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sync_aggregate_versions (
  organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by TEXT NOT NULL, PRIMARY KEY(organization_id,entity_id,aggregate_type,aggregate_id));
CREATE TABLE IF NOT EXISTS sync_pull_cursors (device_id TEXT PRIMARY KEY, cursor_at TEXT NULL, cursor_version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_sync_ops_device_status ON sync_operations(device_id,status,received_at);
CREATE INDEX IF NOT EXISTS ix_sync_conflicts_scope ON sync_conflicts(entity_id,location_id,resolution,created_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sync.view','View offline sync queue, conflicts and device state') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sync.write','Submit offline sync operations and resolve conflicts') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'sync.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'sync.write' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson') ON CONFLICT DO NOTHING;