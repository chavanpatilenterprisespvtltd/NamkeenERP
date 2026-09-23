# V90.eh — Factory Execution Benefit Realization + Bottleneck Closure Analytics

## Release
- Version: V90.eh
- Schema target: 209
- Builds cumulatively on V90.eg / migration 208.

## Scope
- measure planned vs realized bottleneck relief after scenario execution
- reconcile planned vs actual overtime and schedule-hour reduction
- produce work-centre benefit lines and a management benefit score
- classify realization as REALIZED / PARTIAL / MISSED
- explicit benefit-closure workflow
- auditable Scenario → Handoff → Execution → Reconciliation → Benefit Realization → Closure chain
- role-based permissions
- Web UI

## Migration
`209_v90eh_factory_benefit_realization.sql`

## PostgreSQL
PostgreSQL smoke testing requires a live DATABASE_URL and is only claimed when actually available.
