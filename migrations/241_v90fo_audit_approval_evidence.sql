-- V90.fo: ERP-wide audit, governed approval and evidence control foundation.
CREATE TABLE IF NOT EXISTS erp_governed_action_policy(
  policy_id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NULL, action_code VARCHAR(80) NOT NULL,
  module_name VARCHAR(80) NOT NULL, risk_level VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
  approval_required BOOLEAN NOT NULL DEFAULT TRUE, evidence_required BOOLEAN NOT NULL DEFAULT TRUE,
  active BOOLEAN NOT NULL DEFAULT TRUE, created_by VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(organization_id,action_code)
);
CREATE TABLE IF NOT EXISTS erp_governed_action(
  action_id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NOT NULL, entity_id VARCHAR(64) NULL,
  module_name VARCHAR(80) NOT NULL, action_code VARCHAR(80) NOT NULL, subject_type VARCHAR(80) NOT NULL,
  subject_id VARCHAR(120) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'REQUESTED', requested_by VARCHAR(64) NOT NULL,
  requested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, approved_by VARCHAR(64) NULL, approved_at TIMESTAMPTZ NULL,
  decision_note TEXT NULL, evidence_required BOOLEAN NOT NULL DEFAULT TRUE, evidence_complete BOOLEAN NOT NULL DEFAULT FALSE,
  executed_by VARCHAR(64) NULL, executed_at TIMESTAMPTZ NULL, cancelled_by VARCHAR(64) NULL, cancelled_at TIMESTAMPTZ NULL,
  cancellation_note TEXT NULL
);
CREATE TABLE IF NOT EXISTS erp_governed_action_evidence(
  evidence_id VARCHAR(64) PRIMARY KEY, action_id VARCHAR(64) NOT NULL, evidence_type VARCHAR(50) NOT NULL,
  evidence_ref VARCHAR(500) NULL, evidence_note TEXT NOT NULL, added_by VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS erp_audit_event(
  audit_id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NULL, entity_id VARCHAR(64) NULL,
  module_name VARCHAR(80) NOT NULL, action_code VARCHAR(80) NOT NULL, subject_type VARCHAR(80) NULL,
  subject_id VARCHAR(120) NULL, actor_user_id VARCHAR(64) NOT NULL, outcome VARCHAR(30) NOT NULL,
  governed_action_id VARCHAR(64) NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_governed_action_queue ON erp_governed_action(organization_id,status,module_name,action_code,requested_at);
CREATE INDEX IF NOT EXISTS ix_governed_action_subject ON erp_governed_action(subject_type,subject_id,status);
CREATE INDEX IF NOT EXISTS ix_governed_evidence_action ON erp_governed_action_evidence(action_id,created_at);
CREATE INDEX IF NOT EXISTS ix_erp_audit_scope ON erp_audit_event(organization_id,entity_id,created_at);
CREATE INDEX IF NOT EXISTS ix_erp_audit_action ON erp_audit_event(module_name,action_code,created_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES
('governance.audit.view','View ERP audit trail'),
('governance.approval.view','View governed approval queue'),
('governance.approval.manage','Approve or reject governed actions'),
('governance.evidence.manage','Add evidence to governed actions'),
('governance.action.manage','Create governed actions and policies')
ON CONFLICT(permission_id) DO NOTHING;
