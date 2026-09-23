CREATE TABLE IF NOT EXISTS evidence_attachments (
 attachment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, document_type TEXT NOT NULL, filename TEXT NOT NULL,
 mime_type TEXT NOT NULL, storage_ref TEXT NOT NULL, sha256 TEXT NULL, size_bytes INTEGER NULL,
 captured_at TEXT NULL, captured_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 active INTEGER NOT NULL DEFAULT 1, metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS evidence_gps (
 evidence_gps_id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL UNIQUE, latitude REAL NOT NULL, longitude REAL NOT NULL,
 accuracy_m REAL NULL, altitude_m REAL NULL, captured_at TEXT NULL, device_id TEXT NULL, provider TEXT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(attachment_id) REFERENCES evidence_attachments(attachment_id));
CREATE TABLE IF NOT EXISTS evidence_events (
 event_id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, event_type TEXT NOT NULL, event_payload_json TEXT NOT NULL,
 actor_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence_attachments(entity_id,location_id,subject_type,subject_id,active);
CREATE INDEX IF NOT EXISTS ix_evidence_gps ON evidence_gps(latitude,longitude,captured_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('evidence.view','View attachments and GPS evidence') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('evidence.write','Create, activate and audit attachments and GPS evidence') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'evidence.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'evidence.write' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson') ON CONFLICT DO NOTHING;
