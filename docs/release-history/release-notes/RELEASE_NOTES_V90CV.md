# V90.cv — Advanced Procurement Analytics & Supplier Optimization

## Scope
- Supplier spend analytics
- Supplier-wise PPV and price benchmarking
- Contracted vs actual rate analysis
- Landed-cost visibility
- OTIF and quality-rejection metrics
- Supplier savings analysis
- Supplier dependency/concentration metric
- Historical supplier score and optimization recommendation foundation
- Approval-controlled supplier recommendations
- Procurement Analytics Web UI
- RBAC: `proc_analytics.view`, `proc_analytics.manage`, `proc_analytics.recommend`
- Migration 173

## Verification
- Focused V90.cv tests: 2/2
- Python compilation: passed
- CI repository gate: passed
- Migration continuity: 61–173
- Artifact checksum verification: passed
- PostgreSQL migration smoke not claimed because `DATABASE_URL` is unavailable.
