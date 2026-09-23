CREATE TABLE IF NOT EXISTS production_process_log (
    process_log_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    production_order_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    operator_user_id TEXT NULL,
    machine_id TEXT NULL,
    started_at TEXT NULL,
    ended_at TEXT NULL,
    temperature_c NUMERIC NULL,
    frying_time_sec NUMERIC NULL,
    process_value NUMERIC NULL,
    process_uom TEXT NULL,
    status TEXT NOT NULL DEFAULT 'RECORDED',
    deviation_flag INTEGER NOT NULL DEFAULT 0,
    deviation_reason TEXT NULL,
    notes TEXT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_process_log_batch ON production_process_log(batch_id, stage, created_at);
CREATE TABLE IF NOT EXISTS production_process_measurement (
    measurement_id TEXT PRIMARY KEY,
    process_log_id TEXT NOT NULL,
    parameter_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    value_num NUMERIC NULL,
    value_text TEXT NULL,
    uom TEXT NULL,
    target_min NUMERIC NULL,
    target_max NUMERIC NULL,
    pass_flag INTEGER NULL,
    measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_process_measurement_log ON production_process_measurement(process_log_id, parameter_code);
