# V90.w — Packing / SKU Conversion

## Added
- Packing run master and lifecycle: DRAFT → RUNNING → COMPLETED.
- Bulk finished-goods source lot validation and consumption.
- SKU validation using persistent product master.
- Packaging-material consumption capture, including optional lot-specific consumption.
- Packaging stock availability checks before completion.
- Packaging inventory decrement ledger/balance updates.
- Packed finished-goods lot creation linked to packing run and source FG lot.
- Packed SKU inventory receipt and balance update.
- Lot/run traceability endpoints.
- Entity/location/warehouse scope enforcement.
- Migration 096 and release target 96.

## Verification
- Full cumulative regression suite: 112 passed, 0 failed.
- Archive integrity verified after packaging.
- V90.w is not project-final.
