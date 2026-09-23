-- V90.j: product / SKU / pack-size / UOM workflow checkpoint.
CREATE INDEX IF NOT EXISTS ix_master_record_product_hierarchy
    ON master_record (organization_id, master_type, entity_id, active, updated_at);
CREATE INDEX IF NOT EXISTS ix_master_record_sku_barcode
    ON master_record (organization_id, master_type, entity_id, active);
