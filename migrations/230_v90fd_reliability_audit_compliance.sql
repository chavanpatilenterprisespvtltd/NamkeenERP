-- V90.fd: Reliability Audit & Compliance
CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 capa_open_count INTEGER NOT NULL DEFAULT 0, capa_overdue_count INTEGER NOT NULL DEFAULT 0,
 capa_evidence_gap_count INTEGER NOT NULL DEFAULT 0, approval_gap_count INTEGER NOT NULL DEFAULT 0,
 unauthorized_change_count INTEGER NOT NULL DEFAULT 0, standard_adoption_gap_count INTEGER NOT NULL DEFAULT 0,
 open_exception_count INTEGER NOT NULL DEFAULT 0, compliance_score NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_exception(
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM', object_type TEXT NOT NULL, object_id TEXT NOT NULL,
 finding TEXT NOT NULL, required_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', evidence_note TEXT,
 resolved_by TEXT, resolved_at TIMESTAMP, resolution_note TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_event(
 audit_event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 event_type TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'INFO',
 detail TEXT NOT NULL, actor_user_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_reliability_audit_exception_queue ON maintenance_reliability_audit_exception(organization_id,entity_id,period_key,status,severity);
CREATE INDEX IF NOT EXISTS ix_reliability_audit_event_scope ON maintenance_reliability_audit_event(organization_id,entity_id,period_key,event_type);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_audit.view','View Reliability Audit and Compliance') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_audit.manage','Manage Reliability Audit Exceptions') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_audit.close','Close Reliability Audit Period') ON CONFLICT(permission_id) DO NOTHING;
