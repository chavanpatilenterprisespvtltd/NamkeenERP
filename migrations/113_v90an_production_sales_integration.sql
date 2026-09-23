-- V90.an: cross-module production -> QC -> packing -> sales integration validation.
CREATE TABLE IF NOT EXISTS e2e_integration_validation (
    validation_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    sales_order_id TEXT,
    production_batch_id TEXT,
    fg_lot_id TEXT,
    packing_run_id TEXT,
    packed_fg_lot_id TEXT,
    validation_status TEXT NOT NULL,
    production_status TEXT,
    production_qc_status TEXT,
    fg_status TEXT,
    packing_status TEXT,
    packing_qc_status TEXT,
    sales_status TEXT,
    allocation_status TEXT,
    pick_status TEXT,
    dispatch_status TEXT,
    invoice_status TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    validated_by TEXT NOT NULL,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_e2e_validation_scope ON e2e_integration_validation(entity_id,location_id,validation_status,validated_at);
CREATE INDEX IF NOT EXISTS ix_e2e_validation_order ON e2e_integration_validation(sales_order_id,validated_at);
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('integration.view','View end-to-end integration status') ON CONFLICT(permission_id) DO NOTHING;
INSERT INTO erp_permissions(permission_id,permission_name) VALUES('integration.validate','Validate end-to-end production/sales flow') ON CONFLICT(permission_id) DO NOTHING;
