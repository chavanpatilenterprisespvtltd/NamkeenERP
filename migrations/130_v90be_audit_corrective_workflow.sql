CREATE TABLE IF NOT EXISTS erp_audit_log (
 audit_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL, location_id TEXT NULL,
 actor_user_id TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
 before_json TEXT NULL, after_json TEXT NULL, reason TEXT NULL, correlation_id TEXT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS corrective_transaction_requests (
 correction_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 source_type TEXT NOT NULL, source_id TEXT NOT NULL, correction_type TEXT NOT NULL, reason TEXT NOT NULL,
 before_json TEXT NULL, proposed_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', requested_by TEXT NOT NULL,
 requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_by TEXT NULL, decided_at TEXT NULL,
 decision_reason TEXT NULL, applied_at TEXT NULL, applied_by TEXT NULL);
CREATE INDEX IF NOT EXISTS ix_audit_scope_time ON erp_audit_log(organization_id,entity_id,location_id,created_at);
CREATE INDEX IF NOT EXISTS ix_audit_object ON erp_audit_log(object_type,object_id,created_at);
CREATE INDEX IF NOT EXISTS ix_correction_queue ON corrective_transaction_requests(organization_id,entity_id,status,requested_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_correction_active_source ON corrective_transaction_requests(source_type,source_id) WHERE status IN ('PENDING','APPROVED');
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('audit.view','View audit log and transaction history') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('correction.view','View corrective transaction requests') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('correction.submit','Submit corrective transaction requests') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('correction.approve','Approve or reject corrective transaction requests') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'audit.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'correction.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'correction.submit' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'correction.approve' FROM erp_roles WHERE role_id IN ('manager','super_admin') ON CONFLICT DO NOTHING;
