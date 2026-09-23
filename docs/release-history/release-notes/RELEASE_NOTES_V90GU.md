# V90.gu — Mobile Remaining Transaction Execution

Schema 271. Built cumulatively from V90.gt / schema 270.

## Scope
- RECEIPT_CONFIRM validates against the existing GRN receiving system of record.
- PRODUCTION_CONFIRM records production output and completes an eligible running batch.
- STOCK_COUNT records counted quantity and variance against existing inventory lots; it does not bypass the controlled stock-adjustment workflow.
- QUALITY_CONFIRM records a quality result and can release only when the supplied result passes and there are no failed results/open NCs.
- Idempotent execution and audit trail reuse V90.gs/V90.gt infrastructure.
- Entity/location RBAC is enforced.

## Design rule
No duplicate inventory, production, or quality ledger is introduced. Existing ERP transaction tables remain authoritative.
