-- V90.ae Sales Order -> FG/FEFO allocation bridge
CREATE TABLE IF NOT EXISTS sales_order_allocations (
    sales_order_allocation_id TEXT PRIMARY KEY,
    sales_order_id TEXT NOT NULL,
    sales_order_line_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    lot_code TEXT NULL,
    quantity NUMERIC NOT NULL,
    fg_allocation_group_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ALLOCATED',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMP NULL,
    release_reason TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_so_alloc_order ON sales_order_allocations(sales_order_id,status);
CREATE INDEX IF NOT EXISTS ix_so_alloc_line ON sales_order_allocations(sales_order_line_id,status);
