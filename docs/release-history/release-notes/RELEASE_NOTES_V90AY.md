# V90.ay — Inventory Valuation + Stock Ageing

## Implemented
- Current available-stock valuation by entity/location/warehouse.
- Latest active product cost-rate valuation basis.
- Weighted raw-lot GRN unit-rate fallback when no active product cost rate exists.
- Configurable slow-moving and dead-stock thresholds at entity or location scope.
- Lot-level stock ageing for raw-material lots and released finished-goods lots.
- Expired-stock visibility.
- Slow-moving and dead-stock valuation metrics.
- Inventory valuation snapshots for audit/reporting history.
- RBAC permissions: `inventory_valuation.view`, `inventory_valuation.edit`.
- Migration 124 with ordered/checksum validation.

## APIs
- `PUT /v90ay/inventory/ageing-policy`
- `GET /v90ay/inventory/valuation`
- `GET /v90ay/inventory/stock-ageing`
- `POST /v90ay/inventory/valuation-snapshots`
- `GET /v90ay/inventory/valuation-snapshots`

## Verification
- Full cumulative suite: 196 passed, 18 pre-existing warnings, 0 failed.
- Python compile check passed.
- Migration continuity/checksum validation passed.
- Release ZIP integrity passed.
