# V90.y — Finished Goods Batch/Expiry + FEFO Dispatch Control

Cumulative from V90.x.

## Added
- Packed-FG lot FEFO preview by SKU, warehouse and expiry date.
- Expired lots excluded from dispatch allocation.
- Open allocation reservations reduce allocatable quantity.
- Allocation group creation and release workflow.
- Dispatch-readiness endpoint with explicit blocking reasons.
- Entity/location/warehouse access enforcement.
- Migration 098 and release metadata target 98.

## Verification
- Full cumulative test suite: 118 passed, 0 failed.
- ZIP archive integrity verified.

## Next
V90.z continues the cumulative ERP build. V90.y is not final.
