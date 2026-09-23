# V90.gt — Mobile Inventory / Dispatch / Delivery Transaction Execution

V90.gt extends the V90.gs mobile transaction boundary into controlled execution against existing ERP transaction tables. It does not create duplicate inventory, dispatch, invoice, or return ledgers.

## Implemented
- `PICK_CONFIRM` executes the existing dispatch pick-list confirmation.
- `DISPATCH_CONFIRM` validates the existing posted dispatch as the mobile execution checkpoint.
- `DELIVERY_CONFIRM` records POD against the existing dispatch.
- `RETURN_CONFIRM` receives an existing sales return into the established QC-hold workflow.
- Execution is idempotent through `mobile_execution_records`.
- V90.gs integration status moves to `POSTED` only after successful execution.
- Execution audit is retained with result JSON, actor, scope and timestamp.
- Entity/location RBAC is enforced.
- Web cockpit: `/ui/mobile-inventory-dispatch-delivery`.

## Deliberate boundary
`RECEIPT_CONFIRM`, `PRODUCTION_CONFIRM`, `STOCK_COUNT`, and `QUALITY_CONFIRM` remain on their existing ERP workflows until their transaction-specific posting rules can be safely adapted without bypassing QC, stock, accounting, or production controls.
