-- V90.h: master-data entity/location scoping checkpoint.
-- Runtime code adds nullable entity_id/location_id to existing master records table when present.
CREATE TABLE IF NOT EXISTS erp_master_scope_policy (
  policy_id VARCHAR(64) PRIMARY KEY,
  master_scope VARCHAR(32) NOT NULL,
  enforce_on_read BOOLEAN NOT NULL DEFAULT TRUE,
  enforce_on_write BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO erp_master_scope_policy(policy_id, master_scope)
VALUES ('default','entity_location')
ON CONFLICT(policy_id) DO NOTHING;
