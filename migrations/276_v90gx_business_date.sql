-- FILE PATH: migrations/276_v90gx_business_date.sql
-- V90.gx (Session CS2): business date / shift on production batches and machine runs (app/business_date.py).
-- IF EXISTS keeps this safe on databases where the owning module has not created the table yet.
ALTER TABLE IF EXISTS production_batch ADD COLUMN IF NOT EXISTS business_date DATE NULL;
ALTER TABLE IF EXISTS production_batch ADD COLUMN IF NOT EXISTS shift_code TEXT NULL;
ALTER TABLE IF EXISTS manufacturing_machine_run ADD COLUMN IF NOT EXISTS business_date DATE NULL;
