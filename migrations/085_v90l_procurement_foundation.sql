-- V90.l: procurement foundation checkpoint.
CREATE TABLE IF NOT EXISTS procurement_requisition (
    requisition_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
    required_date TEXT NULL, purpose TEXT NULL, notes TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_requisition_line (
    line_id TEXT PRIMARY KEY, requisition_id TEXT NOT NULL, line_no INTEGER NOT NULL,
    item_master_id TEXT NOT NULL, description TEXT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
    required_date TEXT NULL, notes TEXT NULL
);
CREATE TABLE IF NOT EXISTS procurement_quote (
    quote_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    requisition_id TEXT NULL, supplier_id TEXT NOT NULL, quote_no TEXT NOT NULL,
    quote_date TEXT NULL, valid_until TEXT NULL, currency TEXT NOT NULL DEFAULT 'INR',
    status TEXT NOT NULL DEFAULT 'RECEIVED', notes TEXT NULL, created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_quote_line (
    line_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, line_no INTEGER NOT NULL,
    item_master_id TEXT NOT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
    unit_rate NUMERIC NOT NULL, tax_rate NUMERIC NULL, freight NUMERIC NULL, discount NUMERIC NULL,
    notes TEXT NULL
);
CREATE TABLE IF NOT EXISTS procurement_po (
    po_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, supplier_id TEXT NOT NULL, requisition_id TEXT NULL,
    quote_id TEXT NULL, po_no TEXT NOT NULL, po_date TEXT NOT NULL, expected_date TEXT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL', currency TEXT NOT NULL DEFAULT 'INR',
    payment_terms_days INTEGER NULL, delivery_terms TEXT NULL, notes TEXT NULL,
    requested_by TEXT NOT NULL, approved_by TEXT NULL, approved_at TIMESTAMP NULL, approval_reason TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_po_line (
    line_id TEXT PRIMARY KEY, po_id TEXT NOT NULL, line_no INTEGER NOT NULL,
    item_master_id TEXT NOT NULL, description TEXT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
    unit_rate NUMERIC NOT NULL, discount NUMERIC NULL, tax_rate NUMERIC NULL, expected_date TEXT NULL,
    notes TEXT NULL
);
CREATE TABLE IF NOT EXISTS procurement_grn_prep (
    grn_prep_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, po_id TEXT NOT NULL,
    reference_no TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', notes TEXT NULL,
    prepared_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_grn_prep_line (
    line_id TEXT PRIMARY KEY, grn_prep_id TEXT NOT NULL, po_line_id TEXT NOT NULL,
    ordered_qty NUMERIC NOT NULL, planned_receive_qty NUMERIC NOT NULL, uom TEXT NOT NULL,
    lot_capture_required INTEGER NOT NULL DEFAULT 1, notes TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_procurement_req_scope ON procurement_requisition (organization_id, entity_id, location_id, status);
CREATE INDEX IF NOT EXISTS ix_procurement_po_scope ON procurement_po (organization_id, entity_id, location_id, status, supplier_id);
CREATE INDEX IF NOT EXISTS ix_procurement_quote_supplier ON procurement_quote (organization_id, entity_id, supplier_id, status);
CREATE INDEX IF NOT EXISTS ix_procurement_grn_prep_po ON procurement_grn_prep (organization_id, entity_id, po_id, status);
