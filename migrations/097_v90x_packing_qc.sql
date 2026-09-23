CREATE TABLE IF NOT EXISTS packing_qc_inspection (
    inspection_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    packing_run_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    net_weight_target NUMERIC NULL,
    net_weight_actual NUMERIC NULL,
    weight_tolerance_pct NUMERIC NULL,
    seal_status TEXT NULL,
    label_status TEXT NULL,
    nitrogen_status TEXT NULL,
    visual_status TEXT NULL,
    overall_status TEXT NOT NULL DEFAULT 'PENDING',
    hold_reason TEXT NULL,
    released_by TEXT NULL,
    released_at TEXT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(packing_run_id, packed_fg_lot_id)
);
CREATE TABLE IF NOT EXISTS packing_qc_checks (
    check_id TEXT PRIMARY KEY,
    inspection_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    observed_value TEXT NULL,
    status TEXT NOT NULL,
    remarks TEXT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(inspection_id) REFERENCES packing_qc_inspection(inspection_id)
);
CREATE INDEX IF NOT EXISTS ix_packing_qc_scope ON packing_qc_inspection(entity_id,location_id,warehouse_id,overall_status);
CREATE INDEX IF NOT EXISTS ix_packing_qc_lot ON packing_qc_inspection(packed_fg_lot_id);
