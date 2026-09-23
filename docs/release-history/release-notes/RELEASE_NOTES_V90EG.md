# V90.eg — Scenario Execution Reconciliation + Production Schedule Variance

## Release
- Version: V90.eg
- Schema target: 208
- Builds cumulatively on V90.ef / migration 207.

## Scope
- reconcile executed scenario schedules against approved execution proposals
- planned vs actual quantity and required-hour variance
- planned vs actual overtime reconciliation
- per-work-centre / schedule reconciliation lines
- configurable reconciliation tolerances
- ON_TRACK vs VARIANCE classification
- explicit reconciliation close workflow
- auditable scenario → handoff → execution → actual schedule → reconciliation chain
- role-based permissions
- Web UI

## Migration
`208_v90eg_execution_reconciliation.sql`

## PostgreSQL
PostgreSQL smoke testing requires a live DATABASE_URL and is only claimed when actually available.
