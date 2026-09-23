# v82 — Dependent Master Lookup APIs

## Purpose
Provide searchable, organization-scoped lookup endpoints for structured master-data screens so users do not manually type UUIDs.

## Relationships
- Product → Variant
- Product → SKU
- Variant → SKU
- Pack Size → SKU
- Warehouse → Bin
- Tax Profile → HSN
- SKU → Price List

## Contract
`GET /v82/lookups/{kind}` accepts `organization_id`, `q`, optional `parent_id`, `entity_id`, and `limit`.

`GET /v82/relationships` can return multiple dependent collections in one request.

All lookups return `id`, `key`, `label`, `master_type`, `entity_id`, and a `data` payload for display/selection.

## Control
Only active records in the requested organization are returned. No cross-organization lookup is allowed. The API is read-only; selecting a lookup value does not mutate a master or transaction.

For production, mount these routes behind the same authentication/RBAC/entity authorization used by the v77–v81 master APIs.
