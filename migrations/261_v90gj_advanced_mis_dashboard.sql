CREATE TABLE IF NOT EXISTS erp_mis_dashboard_snapshot (
    snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
    gross_sales NUMERIC NOT NULL DEFAULT 0, net_sales NUMERIC NOT NULL DEFAULT 0, collections NUMERIC NOT NULL DEFAULT 0,
    outstanding NUMERIC NOT NULL DEFAULT 0, inventory_value NUMERIC NOT NULL DEFAULT 0, slow_moving_value NUMERIC NOT NULL DEFAULT 0,
    dead_stock_value NUMERIC NOT NULL DEFAULT 0, production_cost NUMERIC NOT NULL DEFAULT 0, production_yield_pct NUMERIC NOT NULL DEFAULT 0,
    cost_variance NUMERIC NOT NULL DEFAULT 0, procurement_spend NUMERIC NOT NULL DEFAULT 0, procurement_savings NUMERIC NOT NULL DEFAULT 0,
    supplier_score NUMERIC NOT NULL DEFAULT 0, labour_cost NUMERIC NOT NULL DEFAULT 0, labour_cost_per_hour NUMERIC NOT NULL DEFAULT 0,
    maintenance_health_score NUMERIC NOT NULL DEFAULT 0, open_alerts INTEGER NOT NULL DEFAULT 0, open_incidents INTEGER NOT NULL DEFAULT 0,
    open_problems INTEGER NOT NULL DEFAULT 0, open_escalations INTEGER NOT NULL DEFAULT 0, critical_risks INTEGER NOT NULL DEFAULT 0,
    executive_health_score NUMERIC NOT NULL DEFAULT 0, assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', status TEXT NOT NULL DEFAULT 'OPEN',
    evidence_ref TEXT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id,entity_id,period_key)
);
CREATE TABLE IF NOT EXISTS erp_mis_dashboard_kpi (
    kpi_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
    kpi_code TEXT NOT NULL, kpi_name TEXT NOT NULL, value NUMERIC NOT NULL DEFAULT 0, target NUMERIC NULL,
    unit TEXT NOT NULL DEFAULT 'NUMBER', direction TEXT NOT NULL DEFAULT 'HIGHER', status TEXT NOT NULL DEFAULT 'INFO',
    source_module TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id,entity_id,period_key,kpi_code)
);
CREATE INDEX IF NOT EXISTS ix_mis_dashboard_scope ON erp_mis_dashboard_snapshot(organization_id,entity_id,period_key,status);
CREATE INDEX IF NOT EXISTS ix_mis_dashboard_kpi_scope ON erp_mis_dashboard_kpi(organization_id,entity_id,period_key,kpi_code);
