# V90.gf — Final Go-Live Closure & Operational Handover

Schema target: 257  
Previous release: v90.ge (256)  
Migration: `257_v90gf_final_go_live_closure.sql`

## Scope

V90.gf is the final controlled ERP go-live closure layer. It consolidates the post-go-live acceptance chain into a formal closure and operational handover record.

## Controls

- V90.ge post-go-live stabilization must be CLOSED.
- No unresolved critical operational incidents or alerts.
- Unresolved defects must be closed or recorded as accepted exceptions with evidence.
- Rollback window must be formally closed.
- Operations/support ownership handover must be recorded.
- Final business acceptance must be recorded.

## Workflow

OPEN → ACCEPTED → CLOSED

Defect dispositions: CLOSED, ACCEPTED_EXCEPTION, DEFERRED.

## API/UI

- `/v90gf/go-live-closures`
- `/v90gf/go-live-closures/{closure_id}/defects`
- `/v90gf/go-live-closures/{closure_id}/controls/{control_code}`
- `/v90gf/go-live-closures/{closure_id}/readiness`
- `/v90gf/go-live-closures/{closure_id}/accept`
- `/v90gf/go-live-closures/{closure_id}/close`
- `/ui/go-live-closure`

The application records evidence and governs the decision chain. It does not claim that external production deployment or external monitoring was executed.

## Verification

Focused V90.gf + prior go-live chain tests: 15 passed.
Python compilation: passed. CI repository gate: passed. Checksum verification: passed. PostgreSQL migration smoke is blocked when no live `DATABASE_URL` is available.

The cumulative suite retains the known pre-existing machine OEE failure (`test_v90db_machine_oee.py::test_machine_oee_calculation`); a later full run was not claimed as clean.
