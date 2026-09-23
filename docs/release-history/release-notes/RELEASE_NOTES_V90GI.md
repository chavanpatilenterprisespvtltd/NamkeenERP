# V90.gi — Incident, Problem & Escalation Management

Schema 260. Continues V90.gh.

## Scope
- Structured problem-management layer built on V90.fx incident/alert controls and V90.gh SLA controls.
- Problem records with ownership, severity, root cause and controlled resolution/closure.
- Links to incidents, alerts, SLA breaches and other ERP references.
- Multi-level escalation records with owners and due dates.
- Evidence-controlled closure and accepted-exception handling.
- Operational governance dashboard for critical open problems and overdue escalations.
- RBAC: `release.incident.view`, `release.incident.manage`.
- UI: `/ui/incident-problem-escalation`.
- The control layer records governance evidence; it does not claim external support activity occurred.

## Verification
- Focused V90.gi + V90.gh + V90.fx tests: PASS.
- Python compilation: required.
- CI repository gate: required.
- Checksums: required.
- PostgreSQL migration smoke: only executable with a live `DATABASE_URL`.
- GitHub remote CI and actual production operations: not claimed unless executed.
