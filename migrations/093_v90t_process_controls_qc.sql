CREATE TABLE IF NOT EXISTS production_process_control (
    control_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    parameter_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    uom TEXT NULL,
    target_min NUMERIC NULL,
    target_max NUMERIC NULL,
    severity TEXT NOT NULL DEFAULT 'WARNING',
    action_on_breach TEXT NOT NULL DEFAULT 'FLAG',
    active INTEGER NOT NULL DEFAULT 1,
    effective_from TEXT NULL,
    effective_to TEXT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_process_control_scope ON production_process_control(entity_id, location_id, stage, parameter_code, effective_from);
CREATE INDEX IF NOT EXISTS ix_process_control_lookup ON production_process_control(entity_id, location_id, stage, parameter_code, active);
CREATE TABLE IF NOT EXISTS production_process_qc_decision (
    decision_id TEXT PRIMARY KEY,
    process_log_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NULL,
    source TEXT NOT NULL DEFAULT 'PROCESS_QC',
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_process_qc_decision_batch ON production_process_qc_decision(batch_id, decided_at);
