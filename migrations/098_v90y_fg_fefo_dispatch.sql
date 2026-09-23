CREATE TABLE IF NOT EXISTS fg_fefo_allocation (
    allocation_id TEXT PRIMARY KEY,
    allocation_group_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    packed_fg_lot_id TEXT NOT NULL,
    lot_code TEXT NULL,
    reference_type TEXT NULL,
    reference_id TEXT NULL,
    quantity NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    allocated_by TEXT NOT NULL,
    allocated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMP NULL,
    release_reason TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_fg_fefo_alloc_group ON fg_fefo_allocation(allocation_group_id,status);
CREATE INDEX IF NOT EXISTS ix_fg_fefo_alloc_scope ON fg_fefo_allocation(entity_id,location_id,warehouse_id,sku_id,status);
CREATE INDEX IF NOT EXISTS ix_fg_fefo_alloc_lot ON fg_fefo_allocation(packed_fg_lot_id,status);
