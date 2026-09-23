-- V90.bv field-sales/beat planning foundation.
CREATE TABLE IF NOT EXISTS field_sales_beat_plans (
    beat_plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    territory_id TEXT, salesperson_user_id TEXT, beat_date TEXT NOT NULL, beat_name TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED', notes TEXT, created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS field_sales_beat_stops (
    stop_id TEXT PRIMARY KEY, beat_plan_id TEXT NOT NULL, customer_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL DEFAULT 1, planned_at TEXT, completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED', notes TEXT
);
