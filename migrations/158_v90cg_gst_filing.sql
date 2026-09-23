-- V90.cg GST filing snapshots, adjustments and filing locks.
CREATE TABLE IF NOT EXISTS gst_filing_periods (
 filing_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT, period_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'DRAFT', outward_taxable NUMERIC NOT NULL DEFAULT 0, outward_tax NUMERIC NOT NULL DEFAULT 0,
 inward_taxable NUMERIC NOT NULL DEFAULT 0, inward_tax NUMERIC NOT NULL DEFAULT 0, net_tax NUMERIC NOT NULL DEFAULT 0,
 adjustment_tax NUMERIC NOT NULL DEFAULT 0, snapshot_json TEXT NOT NULL DEFAULT '{}', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, locked_by TEXT, locked_at TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key)
);
CREATE TABLE IF NOT EXISTS gst_filing_adjustments (
 adjustment_id TEXT PRIMARY KEY, filing_id TEXT NOT NULL, adjustment_type TEXT NOT NULL,
 amount NUMERIC NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(filing_id) REFERENCES gst_filing_periods(filing_id)
);
