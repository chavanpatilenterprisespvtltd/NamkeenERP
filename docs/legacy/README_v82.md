# Namkeen ERP v82 — Dependent Master Lookup APIs

v82 adds searchable, organization-scoped lookup APIs and a dependent-lookup UI contract for the structured master screens.

## Relationships
- Product → Variant
- Product → SKU
- Variant → SKU
- Pack Size → SKU
- Warehouse → Bin
- Tax Profile → HSN
- SKU → Price List

## APIs
- `GET /v82/lookup-types`
- `GET /v82/lookups/{kind}` with search, parent, entity and limit filters
- `GET /v82/relationships` for bundled dependent collections

## Controls
Only active records in the selected organization are returned. Lookup endpoints are read-only and do not bypass master approval/audit controls. Production deployment must apply normal authentication/RBAC/entity authorization middleware.

## Validation
- 3/3 focused v82 tests passed
- Python compilation passed
