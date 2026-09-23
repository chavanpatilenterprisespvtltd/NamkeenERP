-- V90.fp: ERP-wide transaction governance integration.
-- Defaults remain AUDIT_ONLY for backward compatibility; REQUIRE_APPROVAL is policy-driven.
CREATE TABLE IF NOT EXISTS erp_governance_integration_policy(
    integration_id TEXT PRIMARY KEY,
    organization_id TEXT NULL,
    module_name TEXT NOT NULL,
    action_code TEXT NOT NULL,
    route_prefix TEXT NOT NULL,
    http_method TEXT NOT NULL DEFAULT 'POST',
    enforcement TEXT NOT NULL DEFAULT 'AUDIT_ONLY',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deactivated_by TEXT NULL,
    deactivated_at TIMESTAMP NULL,
    deactivation_reason TEXT NULL,
    UNIQUE(organization_id,module_name,action_code,route_prefix,http_method)
);
CREATE TABLE IF NOT EXISTS erp_governance_integration_event(
    event_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL,
    organization_id TEXT NULL,
    entity_id TEXT NULL,
    actor_user_id TEXT NOT NULL,
    path TEXT NOT NULL,
    http_method TEXT NOT NULL,
    action_code TEXT NOT NULL,
    outcome TEXT NOT NULL,
    governed_action_id TEXT NULL,
    status_code INTEGER NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_governance_integration_policy_match ON erp_governance_integration_policy(active,http_method,route_prefix,organization_id);
CREATE INDEX IF NOT EXISTS ix_governance_integration_event_scope ON erp_governance_integration_event(organization_id,actor_user_id,created_at);
CREATE INDEX IF NOT EXISTS ix_governance_integration_event_action ON erp_governance_integration_event(action_code,path,created_at);
