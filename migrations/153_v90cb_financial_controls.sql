-- V90.cb Financial controls, accounting periods and statutory reporting foundation.
CREATE TABLE IF NOT EXISTS accounting_periods (
 period_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
 closed_by TEXT, closed_at TIMESTAMP, UNIQUE(organization_id,period_key)
);
CREATE TABLE IF NOT EXISTS accounting_period_closures (
 closure_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
 closing_type TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,period_key,closing_type)
);
