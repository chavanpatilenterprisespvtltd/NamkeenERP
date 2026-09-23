-- V90.gn — Advanced Sales & Distribution Performance
CREATE TABLE IF NOT EXISTS erp_sales_distribution_snapshot (
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 from_date TEXT NOT NULL, to_date TEXT NOT NULL, net_sales NUMERIC NOT NULL DEFAULT 0,
 invoice_count INTEGER NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0, customer_count INTEGER NOT NULL DEFAULT 0,
 dispatched_qty NUMERIC NOT NULL DEFAULT 0, return_value NUMERIC NOT NULL DEFAULT 0, collection_value NUMERIC NOT NULL DEFAULT 0,
 active_customer_count INTEGER NOT NULL DEFAULT 0, repeat_customer_count INTEGER NOT NULL DEFAULT 0,
 on_time_dispatch_pct NUMERIC NOT NULL DEFAULT 0, return_rate_pct NUMERIC NOT NULL DEFAULT 0,
 collection_realization_pct NUMERIC NOT NULL DEFAULT 0, avg_order_value NUMERIC NOT NULL DEFAULT 0,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,location_id,from_date,to_date)
);
CREATE INDEX IF NOT EXISTS ix_sales_distribution_scope ON erp_sales_distribution_snapshot(organization_id,entity_id,location_id,to_date);
CREATE TABLE IF NOT EXISTS erp_sales_distribution_dimension_snapshot (
 row_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, dimension_type TEXT NOT NULL, dimension_key TEXT NOT NULL,
 dimension_name TEXT NULL, sales_value NUMERIC NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0,
 customer_count INTEGER NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0, collection_value NUMERIC NOT NULL DEFAULT 0,
 return_value NUMERIC NOT NULL DEFAULT 0, productivity_score NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(snapshot_id,dimension_type,dimension_key)
);
CREATE INDEX IF NOT EXISTS ix_sales_distribution_dimension ON erp_sales_distribution_dimension_snapshot(snapshot_id,dimension_type);
CREATE TABLE IF NOT EXISTS erp_sales_distribution_actions (
 action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
 dimension_type TEXT NOT NULL, dimension_key TEXT NOT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM',
 reason TEXT NOT NULL, owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS ix_sales_distribution_actions_scope ON erp_sales_distribution_actions(organization_id,entity_id,status,priority);
