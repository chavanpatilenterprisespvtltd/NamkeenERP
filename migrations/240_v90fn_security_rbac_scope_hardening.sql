-- V90.fn: unified RBAC + organization/entity/location/warehouse security hardening.
CREATE TABLE IF NOT EXISTS erp_organization_user_access (
  user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id),
  organization_id VARCHAR(64) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  granted_by VARCHAR(64) NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_by VARCHAR(64) NULL,
  revoked_at TIMESTAMPTZ NULL,
  PRIMARY KEY(user_id, organization_id)
);
CREATE INDEX IF NOT EXISTS ix_erp_org_user_access ON erp_organization_user_access(organization_id, user_id, active);

CREATE TABLE IF NOT EXISTS erp_security_entity_organization (
  entity_id VARCHAR(64) PRIMARY KEY,
  organization_id VARCHAR(64) NOT NULL,
  mapped_by VARCHAR(64) NULL,
  mapped_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(organization_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_security_entity_org ON erp_security_entity_organization(organization_id, entity_id);

CREATE TABLE IF NOT EXISTS erp_security_scope_audit (
  audit_id VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  actor_user_id VARCHAR(64) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  reason TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_security_scope_audit ON erp_security_scope_audit(user_id, scope_type, created_at);

INSERT INTO erp_permissions(permission_id,permission_name) VALUES
('security.rbac.view','View RBAC and security scope'),
('security.rbac.manage','Manage RBAC and security scope'),
('security.scope.view','View organization/entity/location/warehouse access'),
('security.scope.manage','Grant or revoke organization/entity/location/warehouse access')
ON CONFLICT(permission_id) DO NOTHING;

INSERT INTO erp_role_permissions(role_id,permission_id)
SELECT role_id,'security.rbac.view' FROM erp_roles WHERE role_id IN ('super_admin','manager') ON CONFLICT(role_id,permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id)
SELECT role_id,'security.rbac.manage' FROM erp_roles WHERE role_id IN ('super_admin') ON CONFLICT(role_id,permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id)
SELECT role_id,'security.scope.view' FROM erp_roles WHERE role_id IN ('super_admin','manager') ON CONFLICT(role_id,permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id)
SELECT role_id,'security.scope.manage' FROM erp_roles WHERE role_id IN ('super_admin') ON CONFLICT(role_id,permission_id) DO NOTHING;
