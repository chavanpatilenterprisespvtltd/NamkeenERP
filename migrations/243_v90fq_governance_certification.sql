-- V90.fq: ERP critical-action governance certification and coverage control.
CREATE TABLE IF NOT EXISTS erp_governance_critical_action_certification(
 certification_id TEXT PRIMARY KEY, organization_id TEXT NULL, module_name TEXT NOT NULL, action_code TEXT NOT NULL,
 certification_status TEXT NOT NULL, control_note TEXT NOT NULL, evidence_ref TEXT NULL, certified_by TEXT NOT NULL,
 certified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, active BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE(organization_id,module_name,action_code));
CREATE TABLE IF NOT EXISTS erp_governance_certification_exception(
 exception_id TEXT PRIMARY KEY, organization_id TEXT NULL, module_name TEXT NOT NULL, action_code TEXT NOT NULL,
 reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', opened_by TEXT NOT NULL, opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 resolved_by TEXT NULL, resolved_at TIMESTAMP NULL, resolution_note TEXT NULL, evidence_ref TEXT NULL);
CREATE TABLE IF NOT EXISTS erp_governance_certification_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NULL, closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 force BOOLEAN NOT NULL DEFAULT FALSE, note TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_critical_cert_scope ON erp_governance_critical_action_certification(organization_id,module_name,action_code,active);
CREATE INDEX IF NOT EXISTS ix_cert_exception_scope ON erp_governance_certification_exception(organization_id,status,module_name,action_code);
