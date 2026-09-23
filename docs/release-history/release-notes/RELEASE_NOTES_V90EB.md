# V90.eb — Workforce + Machine Bottleneck Analytics

## Scope
- PostgreSQL migration 203.
- Builds on V90.ea workforce + OEE integration and existing machine/OEE runtime data.
- Work-centre ranking and bottleneck classification.
- Labour efficiency, OEE, combined score, labour/OEE gap, downtime, output and labour-cost analytics.
- Configurable labour/OEE weights and bottleneck thresholds.
- Period close and role-based API/UI access.

## Cumulative maintenance
- No historical migration rewritten; migration 203 is added after 202.

## Verification
- Focused V90.eb and V90.ea/machine regression tests run where possible.
- Python compilation and repository CI gate run.
- Checksum generation/verification run.
- PostgreSQL migration smoke test requires a live DATABASE_URL and is only reported when available.
