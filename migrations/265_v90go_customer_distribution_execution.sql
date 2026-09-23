-- V90.go — Advanced Customer & Distribution Execution / Route Performance
CREATE TABLE IF NOT EXISTS erp_customer_execution_snapshot (
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 from_date TEXT NOT NULL, to_date TEXT NOT NULL, planned_stops INTEGER NOT NULL DEFAULT 0, completed_stops INTEGER NOT NULL DEFAULT 0,
 completion_pct NUMERIC NOT NULL DEFAULT 0, planned_beats INTEGER NOT NULL DEFAULT 0, customers_visited INTEGER NOT NULL DEFAULT 0,
 active_customers INTEGER NOT NULL DEFAULT 0, at_risk_customers INTEGER NOT NULL DEFAULT 0, churned_customers INTEGER NOT NULL DEFAULT 0,
 open_service_exceptions INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,location_id,from_date,to_date));
CREATE INDEX IF NOT EXISTS ix_customer_execution_snapshot ON erp_customer_execution_snapshot(entity_id,location_id,to_date);
CREATE TABLE IF NOT EXISTS erp_customer_execution_actions (
 action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL, customer_id TEXT NOT NULL,
 action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL, owner_user_id TEXT NULL, due_date TEXT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL);
CREATE INDEX IF NOT EXISTS ix_customer_execution_actions ON erp_customer_execution_actions(entity_id,location_id,status,priority);
