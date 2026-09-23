# Namkeen ERP — V90.gt Current Handoff

## CURRENT RELEASE
V90.gt — Mobile Inventory / Dispatch / Delivery Transaction Execution
Schema target: 270

## BASELINE
Built directly from the verified V90.gs package. Preserve all prior release history and migration genealogy.

## COMPLETED IN THIS RELEASE
- Mobile PICK_CONFIRM -> existing pick-list confirmation.
- Mobile DELIVERY_CONFIRM -> existing dispatch POD.
- Mobile DISPATCH_CONFIRM -> posted-dispatch execution checkpoint.
- Mobile RETURN_CONFIRM -> existing return receipt/QC-hold workflow.
- Idempotent execution audit table.
- V90.gs status is posted only after successful V90.gt execution.
- Entity/location scope and mobile transaction permission checks.

## IMPORTANT BOUNDARY
No duplicate inventory/dispatch/invoice/return ledgers were introduced. Existing ERP tables remain systems of record. STOCK_COUNT, RECEIPT_CONFIRM, PRODUCTION_CONFIRM and QUALITY_CONFIRM are intentionally not auto-posted by V90.gt because their existing workflows include domain-specific controls.

## VALIDATION
Focused V90.gt + V90.gs tests: 3 passed. Cumulative regression excluding known OEE test: 543 passed, 28 warnings, exit code 0. Python compileall: PASS. Checksum generation/verification: PASS. CI gate: PASS. ZIP integrity: PASS. PostgreSQL migration smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available. Production deployment was not run.

## KNOWN PRE-EXISTING DEFECT
The historical OEE test `tests/test_v90db_machine_oee.py::test_machine_oee_calculation` is known to expect 75.0% availability while observing 0.0%. Do not silently alter or suppress it.

## NEXT
V90.gu — Mobile Inventory Count / Receipt / Production Execution Adapters, only after inspecting the actual V90.gt source and existing transaction workflows. The goal is to extend mobile execution without bypassing QC, stock, accounting, or production controls.
