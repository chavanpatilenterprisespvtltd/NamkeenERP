# Namkeen ERP — Master Handoff V90.gv

Current release: V90.gv
Schema: 272
Baseline: V90.gu / schema 271

## Completed
Mobile transaction exception, reconciliation and approval controls.

## Key endpoints
- POST /v90gv/mobile/reconcile/{integration_id}
- GET /v90gv/mobile/exceptions
- POST /v90gv/mobile/exceptions/{exception_id}/resolve
- POST /v90gv/mobile/exceptions/{exception_id}/retry

## Controls
- Does not bypass or duplicate ERP transaction ledgers.
- Reconciles mobile integration status with execution records.
- Persists exception evidence.
- Resolution is auditable and RBAC-controlled.
- Retry is allowed only for explicitly retryable READY integrations.
- Entity/location scope is enforced.

## Next milestone
Final ERP technical hardening / security / audit / backup-restore readiness and UAT closure, beginning with a source-based hardening audit.
