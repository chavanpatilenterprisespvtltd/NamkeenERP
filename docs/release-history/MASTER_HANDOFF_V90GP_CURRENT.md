# Namkeen ERP — Current Master Handoff — V90.gp

## CURRENT RELEASE
- Release: **V90.gp — Manufacturing & Workforce Integration**
- Schema: **266**
- Baseline: **V90.go / schema 265**
- Migration: `266_v90gp_manufacturing_workforce_integration.sql`

## COMPLETED
- Manufacturing batch and workforce labour capture reconciliation.
- Batch coverage, output, labour hours/cost, productive time, downtime and overtime KPIs.
- Productivity and labour cost/unit visibility.
- Persistent snapshots and management actions.
- RBAC + entity/location security.
- Web cockpit `/ui/manufacturing-workforce`.

## NEXT
Continue the remaining manufacturing/workforce integration gaps after source inspection, then food quality/traceability, mobile/offline, final hardening/UAT and production readiness. Preserve all historical releases and migration genealogy. Newer source/release ZIP wins over older claims. Never fabricate validation, hashes, DB smoke tests, CI or deployment status.
