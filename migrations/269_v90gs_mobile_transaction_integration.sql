-- V90.gs: mobile/offline events cross the ERP transaction posting boundary.
CREATE TABLE IF NOT EXISTS mobile_transaction_integrations (integration_id TEXT PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,transaction_type TEXT NOT NULL,reference_type TEXT NULL,reference_id TEXT NULL,status TEXT NOT NULL DEFAULT 'PENDING',validation_code TEXT NULL,validation_message TEXT NULL,processed_at TEXT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_transaction_audit (audit_id TEXT PRIMARY KEY,integration_id TEXT NOT NULL,action TEXT NOT NULL,from_status TEXT NULL,to_status TEXT NULL,message TEXT NULL,actor_user_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_mobile_txn_scope ON mobile_transaction_integrations(entity_id,location_id,status);
CREATE INDEX IF NOT EXISTS ix_mobile_txn_ref ON mobile_transaction_integrations(reference_type,reference_id,status);
