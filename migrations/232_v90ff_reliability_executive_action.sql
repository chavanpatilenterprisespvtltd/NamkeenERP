-- V90.ff: Reliability Executive Action & Decision Control
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_action(
 action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 exception_id TEXT, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', title TEXT NOT NULL,
 decision_request TEXT NOT NULL, owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'PROPOSED',
 decision_note TEXT, evidence_note TEXT, decided_by TEXT, decided_at TIMESTAMP, completed_note TEXT,
 completed_by TEXT, completed_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(exception_id,action_type));
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_action_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 action_count INTEGER NOT NULL DEFAULT 0, open_action_count INTEGER NOT NULL DEFAULT 0, completed_action_count INTEGER NOT NULL DEFAULT 0,
 closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_reliability_exec_action_scope ON maintenance_reliability_executive_action(organization_id,entity_id,period_key,status,priority);
CREATE INDEX IF NOT EXISTS ix_reliability_exec_action_due ON maintenance_reliability_executive_action(organization_id,entity_id,status,due_date);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_action.view','View Reliability Executive Actions') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_action.manage','Manage Reliability Executive Actions') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_action.close','Close Reliability Executive Action Period') ON CONFLICT(permission_id) DO NOTHING;
