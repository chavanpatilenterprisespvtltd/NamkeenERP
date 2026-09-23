# Namkeen ERP — Current Master Handoff — V90.go

## CURRENT RELEASE
- Release: **V90.go — Advanced Customer & Distribution Execution / Route Performance**
- Schema: **265**
- Baseline: **V90.gn / schema 264**
- Migration: `265_v90go_customer_distribution_execution.sql`

## COMPLETED
- Route/beat execution metrics on existing field-sales foundation.
- Customer visit execution metrics.
- Customer health/retention signals from order history.
- Service-exception cockpit metric.
- Snapshot persistence and customer action register.
- RBAC + entity/location scope.
- Web cockpit: `/ui/customer-distribution-execution`.

## ARCHITECTURE
- Preserve all historical releases and migration genealogy.
- Entity X = manufacturing; Entity Y = marketing/sales.
- Reuse existing customer, territory, field-sales, order and dispatch foundations.
- Do not create competing customer ownership or route masters.
- Newer source/release ZIP wins over older handoff claims.
- Never fabricate hashes, DB smoke tests, CI or deployment status.

## NEXT RELEASE
**V90.gp or next verified roadmap milestone after source inspection:** continue advanced sales/distribution execution only where a real missing business capability remains; then move into manufacturing/workforce integration, quality/traceability, mobile/offline hardening, final technical hardening/UAT and production readiness.
