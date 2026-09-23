# V90.gh — Continuous Operations Governance & SLA Management

Schema 259. Continues V90.gg.

## Scope
- Permanent BAU operational SLA policy layer built on V90.fx observability and incident controls.
- Scoped SLA policies with service area, severity and response targets.
- Evidence-controlled SLA breach lifecycle: OPEN → ACKNOWLEDGED → MITIGATED → CLOSED, with WAIVED support.
- Critical and overdue breach dashboard gate.
- Periodic service reviews with target-vs-actual compliance tracking.
- RBAC: `release.sla.view`, `release.sla.manage`.
- UI: `/ui/operations-sla`.
- Control records do not claim that external SLA monitoring occurred.

## Verification
- Focused V90.gh tests: expected PASS.
- Python compilation: required.
- CI repository gate: required.
- Checksums: required.
- PostgreSQL migration smoke: only executable with a live `DATABASE_URL`.
- GitHub remote CI and actual production operations: not claimed unless executed.
