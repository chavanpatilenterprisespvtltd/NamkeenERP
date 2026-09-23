# V90.gv — Mobile Transaction Exception / Reconciliation / Approval Control

Baseline: V90.gu / schema 271  
Schema: 272

## Scope
- Reconciliation of mobile integration state against execution records.
- Persistent exception register with severity, retryability and resolution evidence.
- Controlled exception resolution.
- Controlled retry authorization only for explicitly retryable READY integrations.
- Entity/location RBAC and audit trail.
- Existing ERP transaction tables remain systems of record.

## Exception classes
- INTEGRATION_REJECTED
- EXECUTION_STATE_MISMATCH
- POSTING_EXECUTION_GAP
- READY_REQUIRES_EXECUTION
- EXECUTION_STATUS_MISMATCH

## Important control
This release does not silently repair or post a mismatched transaction. It creates an auditable exception and requires controlled resolution/retry.
