# V90.an — Production + QC + Packing + Sales Integration

V90.an adds a persistent, scope-aware cross-module validation layer for the existing production, process QC, finished-goods, packing, sales-order, stock-allocation, pick, dispatch and invoice modules.

## Integrated flow
Production batch → production QC release → finished-goods release → packing completion → packed-FG QC release → sales order → stock allocation → pick confirmation → dispatch → posted invoice.

## New API
- `GET /v90an/integration/sales-orders/{sales_order_id}/trace`
- `POST /v90an/integration/sales-orders/{sales_order_id}/validate`

## Persistence
- `e2e_integration_validation` audit table
- Migration `113_v90an_production_sales_integration.sql`
- Integration permissions: `integration.view`, `integration.validate`

This release is an integration milestone; it is not the final ERP/UAT release.
