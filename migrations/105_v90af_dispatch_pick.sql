-- V90.af: dispatch pick-list foundation
CREATE TABLE IF NOT EXISTS dispatch_pick_lists (
    pick_list_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sales_order_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    picked_at TEXT,
    confirmed_by TEXT
);
CREATE TABLE IF NOT EXISTS dispatch_pick_lines (
    pick_line_id TEXT PRIMARY KEY,
    pick_list_id TEXT NOT NULL,
    sales_order_line_id TEXT NOT NULL,
    sales_order_allocation_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    lot_code TEXT,
    allocated_qty NUMERIC NOT NULL,
    picked_qty NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pick_order ON dispatch_pick_lists(sales_order_id,status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pick_line_alloc ON dispatch_pick_lines(sales_order_allocation_id);
CREATE INDEX IF NOT EXISTS ix_pick_scope ON dispatch_pick_lists(entity_id,location_id,warehouse_id,status);

INSERT INTO erp_permissions(permission_id,permission_name) VALUES('dispatch.view','View dispatch') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('dispatch.edit','Edit dispatch') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT 'manager','dispatch.view' WHERE EXISTS(SELECT 1 FROM erp_roles WHERE role_id='manager') AND EXISTS(SELECT 1 FROM erp_permissions WHERE permission_id='dispatch.view') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT 'manager','dispatch.edit' WHERE EXISTS(SELECT 1 FROM erp_roles WHERE role_id='manager') AND EXISTS(SELECT 1 FROM erp_permissions WHERE permission_id='dispatch.edit') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT 'super_admin','dispatch.view' WHERE EXISTS(SELECT 1 FROM erp_roles WHERE role_id='super_admin') AND EXISTS(SELECT 1 FROM erp_permissions WHERE permission_id='dispatch.view') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id,permission_id) SELECT 'super_admin','dispatch.edit' WHERE EXISTS(SELECT 1 FROM erp_roles WHERE role_id='super_admin') AND EXISTS(SELECT 1 FROM erp_permissions WHERE permission_id='dispatch.edit') ON CONFLICT DO NOTHING;
