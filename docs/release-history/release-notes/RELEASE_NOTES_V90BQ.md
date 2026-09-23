# V90.bq — Salesperson Home + Customer Onboarding + Customer Visit + Order Builder UI

## Scope
- Salesperson home dashboard with orders, value, visits, open orders, active customers.
- Customer search/list scoped by organization/entity/location.
- Customer onboarding request reuses existing CUSTOMER master approval governance.
- Customer visit capture with outcome, next action and optional GPS coordinates.
- Visit history scoped by organization/entity/location/customer.
- Saved order-builder drafts per salesperson/customer/context.
- Responsive Web screen at `/web/salesperson.html`.
- RBAC permissions: `salesperson_ui.view`, `salesperson_ui.manage`.
- Migration 142 and release metadata.

## Validation
- Full cumulative pytest: 257 passed, 18 pre-existing warnings.
- Migration range 61–142 contiguous and checksummed.
- Python compilation passed.
- CI repository gate passed.
- Release archive excludes local databases, bytecode, caches and build artifacts.
