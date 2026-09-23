-- V90.ei — Maintenance Labour Costing + Reliability Labour Integration
CREATE TABLE IF NOT EXISTS maintenance_labour_rate(
 rate_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 work_center_id TEXT,
 employee_id TEXT,
 labour_category TEXT,
 regular_rate NUMERIC NOT NULL DEFAULT 0,
 overtime_rate NUMERIC NOT NULL DEFAULT 0,
 burden_pct NUMERIC NOT NULL DEFAULT 0,
 active BOOLEAN NOT NULL DEFAULT TRUE,
 effective_from DATE,
 effective_to DATE,
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS maintenance_labour_charge(
 charge_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 maintenance_order_id TEXT NOT NULL,
 work_center_id TEXT NOT NULL,
 employee_id TEXT,
 labour_category TEXT,
 charge_date DATE NOT NULL,
 regular_hours NUMERIC NOT NULL DEFAULT 0,
 overtime_hours NUMERIC NOT NULL DEFAULT 0,
 regular_rate NUMERIC NOT NULL DEFAULT 0,
 overtime_rate NUMERIC NOT NULL DEFAULT 0,
 burden_pct NUMERIC NOT NULL DEFAULT 0,
 regular_cost NUMERIC NOT NULL DEFAULT 0,
 overtime_cost NUMERIC NOT NULL DEFAULT 0,
 burden_cost NUMERIC NOT NULL DEFAULT 0,
 total_cost NUMERIC NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS maintenance_labour_close(
 close_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 period_start DATE NOT NULL,
 period_end DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED',
 closed_by TEXT NOT NULL,
 closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_start,period_end)
);
CREATE INDEX IF NOT EXISTS ix_maintenance_labour_charge_scope ON maintenance_labour_charge(organization_id,entity_id,maintenance_order_id,charge_date,status);
CREATE INDEX IF NOT EXISTS ix_maintenance_labour_rate_scope ON maintenance_labour_rate(organization_id,entity_id,work_center_id,employee_id,active,effective_from);
