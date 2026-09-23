-- V90.ah Returns / reverse logistics foundation
CREATE TABLE IF NOT EXISTS sales_returns (
    sales_return_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sales_order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    return_no TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    reason TEXT,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_at TEXT,
    created_by TEXT NOT NULL,
    received_by TEXT
);
CREATE TABLE IF NOT EXISTS sales_return_lines (
    sales_return_line_id TEXT PRIMARY KEY,
    sales_return_id TEXT NOT NULL,
    dispatch_line_id TEXT NOT NULL,
    sales_order_line_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    lot_code TEXT,
    requested_qty NUMERIC NOT NULL,
    received_qty NUMERIC NOT NULL DEFAULT 0,
    disposition_status TEXT NOT NULL DEFAULT 'QC_HOLD',
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS return_hold_lots (
    return_hold_id TEXT PRIMARY KEY,
    sales_return_id TEXT NOT NULL,
    sales_return_line_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    lot_code TEXT,
    quantity NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'QC_HOLD',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_return_no ON sales_returns(organization_id,entity_id,return_no);
CREATE INDEX IF NOT EXISTS ix_sales_return_order ON sales_returns(sales_order_id,status);
CREATE INDEX IF NOT EXISTS ix_sales_return_hold_lot ON return_hold_lots(packed_fg_lot_id,status);
