CREATE TABLE IF NOT EXISTS ui_inventory_preferences (
    preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    screen_key TEXT NOT NULL,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, screen_key)
);
CREATE INDEX IF NOT EXISTS ix_inventory_grn_ui_scope ON inventory_grn(organization_id, entity_id, location_id, received_at);
CREATE INDEX IF NOT EXISTS ix_inventory_lot_ui_scope ON inventory_lot(organization_id, entity_id, location_id, warehouse_id, expiry_date);
CREATE INDEX IF NOT EXISTS ix_inventory_ledger_ui_scope ON inventory_stock_ledger(organization_id, entity_id, location_id, warehouse_id, created_at);
CREATE INDEX IF NOT EXISTS ix_inventory_transfer_ui_scope ON inventory_transfer(organization_id, entity_id, from_location_id, to_location_id, created_at);
