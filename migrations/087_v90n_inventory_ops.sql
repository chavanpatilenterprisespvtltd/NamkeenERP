CREATE TABLE IF NOT EXISTS inventory_reservation (
 reservation_id text PRIMARY KEY, organization_id text NOT NULL, entity_id text NOT NULL, location_id text NOT NULL, warehouse_id text NOT NULL, item_master_id text NOT NULL, quantity numeric NOT NULL, reserved_qty numeric NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'OPEN', reference_type text, reference_id text, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), released_at timestamptz, release_reason text
);
CREATE TABLE IF NOT EXISTS inventory_transfer (
 transfer_id text PRIMARY KEY, organization_id text NOT NULL, entity_id text NOT NULL, from_location_id text NOT NULL, from_warehouse_id text NOT NULL, to_location_id text NOT NULL, to_warehouse_id text NOT NULL, status text NOT NULL DEFAULT 'DRAFT', notes text, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), posted_at timestamptz
);
CREATE TABLE IF NOT EXISTS inventory_transfer_line (
 transfer_line_id text PRIMARY KEY, transfer_id text NOT NULL, item_master_id text NOT NULL, lot_id text NOT NULL, quantity numeric NOT NULL, uom text NOT NULL
);
