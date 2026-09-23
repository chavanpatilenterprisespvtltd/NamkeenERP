-- V90.at: Sales MIS + Distributor/Dealer/Territory reporting snapshot persistence.
CREATE TABLE IF NOT EXISTS sales_mis_snapshot (
    snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    location_id TEXT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
    gross_sales NUMERIC NOT NULL DEFAULT 0, net_sales NUMERIC NOT NULL DEFAULT 0,
    gst_value NUMERIC NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0,
    customer_count INTEGER NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0,
    invoice_count INTEGER NOT NULL DEFAULT 0, collections NUMERIC NOT NULL DEFAULT 0,
    outstanding NUMERIC NOT NULL DEFAULT 0, overdue_outstanding NUMERIC NOT NULL DEFAULT 0,
    credit_utilization_pct NUMERIC NOT NULL DEFAULT 0, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    calculated_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sales_mis_scope ON sales_mis_snapshot(entity_id,location_id,from_date,to_date,calculated_at);
