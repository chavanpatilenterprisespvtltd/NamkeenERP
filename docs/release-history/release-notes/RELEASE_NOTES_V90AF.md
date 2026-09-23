# V90.af — Dispatch / Pick List Foundation

Cumulative checkpoint after V90.ae.

## Completed
- Approved sales order -> dispatch pick-list creation.
- Exact sales-order allocation lines carried into warehouse pick lines.
- SKU and packed FG lot traceability retained.
- Pick-list OPEN -> PICKED lifecycle.
- Pick confirmation without prematurely reducing FG stock; stock reduction remains a later dispatch transaction.
- Dispatch readiness API requires an approved order and a confirmed pick list.
- Entity/location permission and dispatch/inventory access controls.
- PostgreSQL migration 105 with checksum tracking.

## Verification
- Full cumulative regression suite: 141/141 passed.
- ZIP archive integrity verified after packaging.

## Next
V90.ag — Dispatch execution / shipment posting / invoice linkage.
