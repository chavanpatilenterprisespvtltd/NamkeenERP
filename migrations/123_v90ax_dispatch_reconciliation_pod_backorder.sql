-- V90.ax Dispatch reconciliation / transporter / POD / partial dispatch-backorder workflow
CREATE TABLE IF NOT EXISTS transporters (
    transporter_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    transporter_code TEXT NOT NULL,
    transporter_name TEXT NOT NULL,
    phone TEXT NULL,
    gstin TEXT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, entity_id, transporter_code)
);
CREATE TABLE IF NOT EXISTS dispatch_delivery_assignments (
    assignment_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL,
    transporter_id TEXT NULL,
    transporter_name TEXT NULL,
    vehicle_no TEXT NULL,
    driver_name TEXT NULL,
    driver_phone TEXT NULL,
    eway_bill_no TEXT NULL,
    assigned_by TEXT NOT NULL,
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'ASSIGNED',
    UNIQUE(dispatch_id)
);
CREATE TABLE IF NOT EXISTS dispatch_reconciliation (
    reconciliation_id TEXT PRIMARY KEY,
    sales_order_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    ordered_qty NUMERIC NOT NULL DEFAULT 0,
    dispatched_qty NUMERIC NOT NULL DEFAULT 0,
    backorder_qty NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    reconciled_by TEXT NOT NULL,
    reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sales_order_id)
);
CREATE TABLE IF NOT EXISTS dispatch_pod (
    pod_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    received_by TEXT NULL,
    received_at TEXT NULL,
    pod_reference TEXT NULL,
    attachment_ref TEXT NULL,
    notes TEXT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    captured_by TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sales_order_backorders (
    backorder_id TEXT PRIMARY KEY,
    sales_order_id TEXT NOT NULL,
    sales_order_line_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    ordered_qty NUMERIC NOT NULL,
    dispatched_qty NUMERIC NOT NULL,
    backorder_qty NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    reason TEXT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT NULL,
    UNIQUE(sales_order_id, sales_order_line_id)
);
CREATE INDEX IF NOT EXISTS ix_transporters_scope ON transporters(entity_id, active);
CREATE INDEX IF NOT EXISTS ix_delivery_assignment_transport ON dispatch_delivery_assignments(transporter_id,status);
CREATE INDEX IF NOT EXISTS ix_dispatch_recon_scope ON dispatch_reconciliation(entity_id,location_id,status);
CREATE INDEX IF NOT EXISTS ix_dispatch_pod_scope ON dispatch_pod(entity_id,location_id,status);
CREATE INDEX IF NOT EXISTS ix_backorder_scope ON sales_order_backorders(entity_id,location_id,status);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('dispatch_mis.view','View dispatch reconciliation and delivery MIS') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('dispatch_mis.edit','Edit transporter, delivery assignment and backorder records') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('pod.edit','Capture delivery proof/POD') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'dispatch_mis.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','salesperson','accounts','mis') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'dispatch_mis.edit' FROM erp_roles WHERE role_id IN ('manager','super_admin','salesperson') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT role_id,'pod.edit' FROM erp_roles WHERE role_id IN ('manager','super_admin','salesperson','dispatch') ON CONFLICT DO NOTHING;
