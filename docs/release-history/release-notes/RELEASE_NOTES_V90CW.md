# V90.cw — Advanced Manufacturing Costing & Yield Optimization

## Scope
- Batch-wise actual costing
- Standard vs actual cost variance
- Material, packaging, labour and overhead costing
- Rework cost tracking
- Wastage and by-product quantities
- Yield percentage and cost-per-output metrics
- Controlled cost adjustments with approval
- Manufacturing Costing Web UI
- RBAC: `mfg_cost.view`, `mfg_cost.manage`, `mfg_cost.approve`
- Migration 174

## Verification
- Focused V90.cw tests: 2/2
- Python compilation: passed
- CI repository gate: passed
- Migration continuity: 61–174
- Artifact checksum verification: passed (635 files)
- PostgreSQL migration smoke not claimed because `DATABASE_URL` is unavailable.
