CREATE TABLE IF NOT EXISTS barcode_registry (
    barcode_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
    code TEXT NOT NULL, symbology TEXT NOT NULL DEFAULT 'CODE128', object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    item_id TEXT NULL, lot_id TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,code)
);
CREATE TABLE IF NOT EXISTS barcode_scan_events (
    scan_event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
    warehouse_id TEXT NULL, code TEXT NOT NULL, symbology TEXT NOT NULL, object_type TEXT NULL, object_id TEXT NULL,
    purpose TEXT NOT NULL DEFAULT 'LOOKUP', result_status TEXT NOT NULL, result_json TEXT NULL,
    scanned_by TEXT NOT NULL, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS barcode_scan_batches (
    scan_batch_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
    purpose TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', opened_by TEXT NOT NULL,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT NULL
);
CREATE TABLE IF NOT EXISTS barcode_scan_batch_lines (
    scan_batch_line_id TEXT PRIMARY KEY, scan_batch_id TEXT NOT NULL, code TEXT NOT NULL,
    object_type TEXT NULL, object_id TEXT NULL, quantity NUMERIC NULL, uom TEXT NULL,
    status TEXT NOT NULL DEFAULT 'SCANNED', scanned_by TEXT NOT NULL, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_barcode_registry_scope ON barcode_registry(entity_id,location_id,active,code);
CREATE INDEX IF NOT EXISTS ix_barcode_scan_events_scope ON barcode_scan_events(entity_id,location_id,scanned_at);
CREATE INDEX IF NOT EXISTS ix_barcode_batch_lines_batch ON barcode_scan_batch_lines(scan_batch_id,scanned_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('barcode.view','Resolve barcode/QR identifiers and view scan history') ON CONFLICT DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('barcode.scan','Register identifiers and record operational scans') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'barcode.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'barcode.scan' FROM erp_roles WHERE role_id IN ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson') ON CONFLICT DO NOTHING;
