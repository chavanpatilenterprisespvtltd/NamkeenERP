# V90.gj — Advanced ERP MIS & Management Dashboard

## Scope
Consolidates existing ERP management data into a controlled executive MIS snapshot and KPI layer. No operational transaction is automatically mutated by dashboard generation.

## Functional coverage
- Executive dashboard snapshot by organization/entity/period
- KPI cards for sales, collections, receivables, inventory, dead stock, production cost/yield/variance, procurement spend/savings/supplier score, labour cost, maintenance health, and operational risks
- Authenticated dashboard read and period comparison APIs
- Evidence reference capture for management snapshots
- Organization/entity security-scope enforcement
- Web entry point at `/ui/mis-dashboard`

## Migration
- Schema target: 261
- Migration: `261_v90gj_advanced_mis_dashboard.sql`

## Validation notes
- Focused V90.gj + V90.gi + V90.gh regression: 9 passed
- Full cumulative results recorded in build verification after execution
- Existing unrelated OEE test remains a known issue where applicable
- PostgreSQL migration smoke requires a live `DATABASE_URL`
