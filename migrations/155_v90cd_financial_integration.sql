CREATE TABLE IF NOT EXISTS financial_integration_postings(
 integration_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 source_type TEXT NOT NULL, source_id TEXT NOT NULL, posting_id TEXT NOT NULL,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,source_type,source_id));
