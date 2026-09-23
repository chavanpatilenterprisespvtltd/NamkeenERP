# V90.fo — ERP-wide Audit, Approval & Evidence Control

## Scope
V90.fo adds a reusable governance control foundation for critical ERP actions. It centralizes governed-action policies, action lifecycle, evidence records, and append-only audit events, with separation-of-duties for approvals.

## Delivered
- Governed-action policy registry by organization/module/action.
- Governed action lifecycle: REQUESTED, APPROVED, REJECTED, EXECUTED.
- Evidence-before-approval enforcement where required.
- Self-approval/self-rejection prevention.
- Reusable `create_governed_action` and `require_executable_action` service helpers for downstream ERP modules.
- ERP audit-event ledger with organization/entity/module/action/actor/outcome traceability.
- Governance APIs for policies, actions, evidence and audit querying.
- Governance Control UI at `/ui/governance-control`.
- Audit instrumentation on existing intercompany execution and approval-workflow operations.
- Existing V90.fn scope isolation remains the security boundary.

## Design guardrails
- No automatic operational mutation is performed by the governance layer itself.
- Approval controls are explicit and evidence-backed.
- The reusable enforcement helper is available for subsequent module hardening without duplicating authorization/governance logic.
- Existing legacy APIs remain backward compatible unless a module explicitly opts into governed execution.

## Verification
- V90.fo focused tests: PASS.
- Cumulative regression status recorded in build verification output.
- PostgreSQL migration smoke requires a live `DATABASE_URL`; no live PostgreSQL instance is available in this build environment.
- GitHub remote CI and production deployment were not performed.
