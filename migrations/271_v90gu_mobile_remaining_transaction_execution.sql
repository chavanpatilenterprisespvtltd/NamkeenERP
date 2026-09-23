-- V90.gu: mobile adapters for receipt, production confirmation, stock count and quality confirmation.
-- Existing ERP transaction tables remain the systems of record. Stock counts are recorded as evidence;
-- inventory ledger adjustment requires the existing controlled stock-adjustment workflow.
CREATE TABLE IF NOT EXISTS mobile_stock_count_execution (
    count_execution_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL UNIQUE,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    item_master_id TEXT NOT NULL,
    lot_id TEXT NULL,
    system_qty NUMERIC NOT NULL,
    counted_qty NUMERIC NOT NULL,
    variance_qty NUMERIC NOT NULL,
    uom TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RECORDED',
    notes TEXT NULL,
    counted_by TEXT NOT NULL,
    counted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mobile_count_scope ON mobile_stock_count_execution(entity_id,location_id,warehouse_id,counted_at);
