-- V90.m: GRN receiving, incoming QC, released lots and receipt ledger.
CREATE TABLE IF NOT EXISTS inventory_grn (
    grn_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, po_id TEXT NULL,
    grn_no TEXT NOT NULL, supplier_id TEXT NOT NULL, received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT', notes TEXT NULL, created_by TEXT NOT NULL,
    approved_by TEXT NULL, approved_at TEXT NULL, approval_reason TEXT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inventory_grn_line (
    grn_line_id TEXT PRIMARY KEY, grn_id TEXT NOT NULL, po_line_id TEXT NULL, line_no INTEGER NOT NULL,
    item_master_id TEXT NOT NULL, ordered_qty NUMERIC NOT NULL, received_qty NUMERIC NOT NULL,
    accepted_qty NUMERIC NOT NULL DEFAULT 0, rejected_qty NUMERIC NOT NULL DEFAULT 0,
    uom TEXT NOT NULL, unit_rate NUMERIC NULL, supplier_lot_no TEXT NULL,
    mfg_date TEXT NULL, expiry_date TEXT NULL, qc_required INTEGER NOT NULL DEFAULT 1,
    qc_status TEXT NOT NULL DEFAULT 'PENDING', rejection_reason TEXT NULL
);
CREATE TABLE IF NOT EXISTS inventory_lot (
    lot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
    source_grn_id TEXT NOT NULL, source_grn_line_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
    supplier_lot_no TEXT NULL, lot_code TEXT NOT NULL, mfg_date TEXT NULL, expiry_date TEXT NULL,
    received_qty NUMERIC NOT NULL, accepted_qty NUMERIC NOT NULL, available_qty NUMERIC NOT NULL,
    rejected_qty NUMERIC NOT NULL DEFAULT 0, uom TEXT NOT NULL, qc_status TEXT NOT NULL DEFAULT 'HOLD',
    status TEXT NOT NULL DEFAULT 'QUARANTINE', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inventory_stock_ledger (
    movement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
    lot_id TEXT NULL, movement_type TEXT NOT NULL, quantity NUMERIC NOT NULL,
    uom TEXT NOT NULL, reference_type TEXT NOT NULL, reference_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'POSTED', created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inventory_qc_result (
    qc_id TEXT PRIMARY KEY, grn_id TEXT NOT NULL, grn_line_id TEXT NOT NULL,
    inspection_no TEXT NOT NULL, inspector_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
    tested_qty NUMERIC NOT NULL, accepted_qty NUMERIC NOT NULL DEFAULT 0,
    rejected_qty NUMERIC NOT NULL DEFAULT 0, reason TEXT NULL, remarks TEXT NULL,
    inspected_at TEXT NOT NULL, approved_by TEXT NULL, approved_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS inventory_stock_balance (
    organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL, uom TEXT NOT NULL,
    available_qty NUMERIC NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, entity_id, location_id, warehouse_id, item_master_id, uom)
);
