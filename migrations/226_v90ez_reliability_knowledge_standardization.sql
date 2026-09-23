-- V90.ez: Reliability Knowledge Base + Standardization
CREATE TABLE IF NOT EXISTS maintenance_reliability_knowledge_record(
 knowledge_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 source_type TEXT NOT NULL, source_id TEXT, work_center_id TEXT, knowledge_type TEXT NOT NULL,
 title TEXT NOT NULL, finding TEXT NOT NULL, evidence_note TEXT, effectiveness_score NUMERIC NOT NULL DEFAULT 0,
 recurrence_count INTEGER NOT NULL DEFAULT 0, recommendation TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PROPOSED',
 approved_by TEXT, approved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,source_type,source_id,knowledge_type));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_knowledge_scope ON maintenance_reliability_knowledge_record(organization_id,entity_id,status,knowledge_type,work_center_id);
CREATE TABLE IF NOT EXISTS maintenance_reliability_standard_recommendation(
 standard_id TEXT PRIMARY KEY, knowledge_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 work_center_id TEXT, standard_type TEXT NOT NULL, standard_text TEXT NOT NULL, rationale TEXT NOT NULL,
 version_no INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'PROPOSED', approved_by TEXT, approved_at TIMESTAMP,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(knowledge_id));
CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_standard_scope ON maintenance_reliability_standard_recommendation(organization_id,entity_id,status,standard_type,work_center_id);
