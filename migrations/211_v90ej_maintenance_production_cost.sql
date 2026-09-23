-- V90.ej — Maintenance Labour Cost -> Production Cost & Reliability Impact Integration
CREATE TABLE IF NOT EXISTS maintenance_production_cost_allocation (
 allocation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 work_center_id TEXT NOT NULL, maintenance_labour_cost NUMERIC NOT NULL DEFAULT 0, maintenance_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 production_qty NUMERIC NOT NULL DEFAULT 0, allocation_basis TEXT NOT NULL, allocated_cost NUMERIC NOT NULL DEFAULT 0,
 cost_per_unit NUMERIC NOT NULL DEFAULT 0, source_charge_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key,work_center_id)
);
CREATE TABLE IF NOT EXISTS maintenance_production_cost_line (
 line_id TEXT PRIMARY KEY, allocation_id TEXT NOT NULL, batch_id TEXT, product_id TEXT, work_center_id TEXT NOT NULL,
 period_key TEXT NOT NULL, base_cost NUMERIC NOT NULL DEFAULT 0, allocated_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
 revised_overhead_cost NUMERIC NOT NULL DEFAULT 0, revised_total_cost NUMERIC NOT NULL DEFAULT 0,
 production_qty NUMERIC NOT NULL DEFAULT 0, cost_per_unit NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(allocation_id,batch_id)
);
CREATE TABLE IF NOT EXISTS maintenance_production_cost_close (
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE INDEX IF NOT EXISTS ix_mpc_alloc_scope ON maintenance_production_cost_allocation(organization_id,entity_id,period_key,work_center_id,status);
CREATE INDEX IF NOT EXISTS ix_mpc_line_scope ON maintenance_production_cost_line(allocation_id,work_center_id,period_key);
