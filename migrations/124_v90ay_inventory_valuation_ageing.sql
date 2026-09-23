CREATE TABLE IF NOT EXISTS inventory_ageing_policy (
    policy_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NULL,
    slow_moving_days INTEGER NOT NULL DEFAULT 90,
    dead_stock_days INTEGER NOT NULL DEFAULT 180,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, entity_id, location_id)
);

CREATE TABLE IF NOT EXISTS inventory_valuation_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NULL,
    valuation_basis TEXT NOT NULL,
    total_qty NUMERIC NOT NULL,
    total_value NUMERIC NOT NULL,
    slow_moving_value NUMERIC NOT NULL DEFAULT 0,
    dead_stock_value NUMERIC NOT NULL DEFAULT 0,
    expired_value NUMERIC NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_inv_val_snapshot_scope ON inventory_valuation_snapshot(entity_id, location_id, created_at);
CREATE INDEX IF NOT EXISTS ix_inv_age_policy_scope ON inventory_ageing_policy(entity_id, location_id);

INSERT INTO erp_permissions(permission_id, permission_name) VALUES ('inventory_valuation.view','View inventory valuation and stock ageing MIS') ON CONFLICT (permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id, permission_name) VALUES ('inventory_valuation.edit','Create inventory valuation snapshots and ageing policies') ON CONFLICT (permission_id) DO NOTHING;
INSERT INTO erp_role_permissions(role_id, permission_id) SELECT role_id,'inventory_valuation.view' FROM erp_roles WHERE role_id IN ('manager','super_admin','accounts','costing','mis','production') ON CONFLICT DO NOTHING;
INSERT INTO erp_role_permissions(role_id, permission_id) SELECT role_id,'inventory_valuation.edit' FROM erp_roles WHERE role_id IN ('manager','super_admin','accounts','costing') ON CONFLICT DO NOTHING;
