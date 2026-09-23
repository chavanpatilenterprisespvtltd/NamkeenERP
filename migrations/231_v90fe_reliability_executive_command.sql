-- V90.fe: Reliability Executive Command Center
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 reliability_score NUMERIC NOT NULL DEFAULT 0, maintenance_cost NUMERIC NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 oee_pct NUMERIC NOT NULL DEFAULT 0, effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0,
 standard_adoption_pct NUMERIC NOT NULL DEFAULT 0, capa_open_count INTEGER NOT NULL DEFAULT 0, capa_overdue_count INTEGER NOT NULL DEFAULT 0,
 capa_ineffective_count INTEGER NOT NULL DEFAULT 0, benchmark_exception_count INTEGER NOT NULL DEFAULT 0, audit_open_exception_count INTEGER NOT NULL DEFAULT 0,
 audit_compliance_score NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0, executive_health_score NUMERIC NOT NULL DEFAULT 0,
 assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', status TEXT NOT NULL DEFAULT 'OPEN', recommendation TEXT, created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_exception(
 exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM', source_type TEXT NOT NULL, source_id TEXT,
 title TEXT NOT NULL, detail TEXT NOT NULL, required_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 resolution_note TEXT, evidence_note TEXT, resolved_by TEXT, resolved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', health_score NUMERIC NOT NULL DEFAULT 0, unresolved_exception_count INTEGER NOT NULL DEFAULT 0,
 closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key));
CREATE INDEX IF NOT EXISTS ix_reliability_command_scope ON maintenance_reliability_executive_command_snapshot(organization_id,entity_id,period_key,status);
CREATE INDEX IF NOT EXISTS ix_reliability_command_exception ON maintenance_reliability_executive_command_exception(organization_id,entity_id,period_key,status,severity);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_command.view','View Reliability Executive Command Center') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_command.manage','Manage Reliability Executive Exceptions') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('maintenance_reliability_command.close','Close Reliability Executive Period') ON CONFLICT(permission_id) DO NOTHING;
