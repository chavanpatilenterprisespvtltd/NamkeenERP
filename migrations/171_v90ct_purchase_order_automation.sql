-- V90.ct: Purchase requisition -> purchase order automation and procurement controls.
CREATE TABLE IF NOT EXISTS procurement_po_control (
    control_id TEXT PRIMARY KEY, po_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    approval_limit NUMERIC NOT NULL DEFAULT 0, order_value NUMERIC NOT NULL DEFAULT 0,
    price_variance_pct NUMERIC NOT NULL DEFAULT 0, landed_cost NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING', exception_code TEXT NULL, created_by TEXT NOT NULL,
    approved_by TEXT NULL, approved_at TIMESTAMP NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_price_history (
    price_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    supplier_id TEXT NOT NULL, item_master_id TEXT NOT NULL, unit_rate NUMERIC NOT NULL,
    landed_cost NUMERIC NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'INR', source_po_id TEXT NULL,
    effective_date TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_supplier_rebate (
    rebate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    supplier_id TEXT NOT NULL, item_master_id TEXT NULL, threshold_qty NUMERIC NOT NULL DEFAULT 0,
    rebate_pct NUMERIC NOT NULL DEFAULT 0, credit_note_required INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS procurement_commitment_snapshot (
    snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL, supplier_id TEXT NOT NULL, committed_value NUMERIC NOT NULL DEFAULT 0,
    open_qty NUMERIC NOT NULL DEFAULT 0, as_of_date TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_procurement_po_control_scope ON procurement_po_control(organization_id,entity_id,status);
CREATE INDEX IF NOT EXISTS ix_procurement_price_history_item ON procurement_price_history(organization_id,entity_id,supplier_id,item_master_id,effective_date);
