# V90.ei — Maintenance Labour Costing + Reliability Labour Integration

## Release
- Version: V90.ei
- Schema target: 210
- Builds cumulatively on V90.eh / migration 209.

## Scope
- configurable maintenance labour rates by work centre / employee / labour category
- regular and overtime maintenance labour hours/cost
- burdened maintenance labour cost
- maintenance order and work-centre labour cost dashboard
- explicit maintenance labour period close
- role-based permissions
- Web UI

## Migration
`210_v90ei_maintenance_labour_costing.sql`

## PostgreSQL
PostgreSQL smoke testing requires a live DATABASE_URL and is only claimed when actually available.
