-- V90.gt: mobile inventory / dispatch / delivery transaction execution boundary.
-- Source ERP transaction tables remain the system of record; this migration adds only execution audit state.
CREATE TABLE IF NOT EXISTS mobile_execution_records (
  execution_id TEXT PRIMARY KEY,
  integration_id TEXT NOT NULL UNIQUE,
  organization_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  location_id TEXT NULL,
  transaction_type TEXT NOT NULL,
  reference_type TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'EXECUTED',
  result_json TEXT NOT NULL,
  executed_by TEXT NOT NULL,
  executed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mobile_exec_scope ON mobile_execution_records(entity_id, location_id, status, executed_at);
CREATE INDEX IF NOT EXISTS ix_mobile_exec_ref ON mobile_execution_records(reference_type, reference_id, transaction_type);
