CREATE TABLE IF NOT EXISTS hr_workforce_kpi_target(
 kpi_target_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 department_id TEXT, product_id TEXT, kpi_code TEXT NOT NULL, kpi_name TEXT NOT NULL,
 target_value NUMERIC NOT NULL, target_uom TEXT, direction TEXT NOT NULL DEFAULT 'HIGHER_IS_BETTER',
 effective_from DATE, effective_to DATE, active BOOLEAN NOT NULL DEFAULT TRUE,
 created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,department_id,product_id,kpi_code,effective_from));

CREATE TABLE IF NOT EXISTS hr_workforce_kpi_scorecard(
 scorecard_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT, employee_id TEXT,
 kpi_code TEXT NOT NULL, actual_value NUMERIC NOT NULL DEFAULT 0, target_value NUMERIC NOT NULL DEFAULT 0,
 variance_value NUMERIC NOT NULL DEFAULT 0, achievement_pct NUMERIC NOT NULL DEFAULT 0,
 efficiency_score NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id,employee_id,kpi_code));

CREATE TABLE IF NOT EXISTS hr_workforce_productivity_benchmark(
 benchmark_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL, department_id TEXT, product_id TEXT, kpi_code TEXT NOT NULL,
 participant_count INTEGER NOT NULL DEFAULT 0, average_value NUMERIC NOT NULL DEFAULT 0,
 best_value NUMERIC NOT NULL DEFAULT 0, worst_value NUMERIC NOT NULL DEFAULT 0,
 actual_value NUMERIC NOT NULL DEFAULT 0, peer_rank INTEGER, percentile NUMERIC NOT NULL DEFAULT 0,
 gap_to_best NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY', created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_id,department_id,product_id,kpi_code));

CREATE INDEX IF NOT EXISTS ix_hr_workforce_kpi_scorecard_period ON hr_workforce_kpi_scorecard(organization_id,entity_id,period_id);
CREATE INDEX IF NOT EXISTS ix_hr_workforce_kpi_benchmark_period ON hr_workforce_productivity_benchmark(organization_id,entity_id,period_id);
