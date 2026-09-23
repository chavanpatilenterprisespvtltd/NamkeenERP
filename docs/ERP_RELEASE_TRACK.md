# Namkeen ERP — Cumulative Release Track

This file is the running navigation and troubleshooting index for the cumulative ERP build. Releases are cumulative; each release starts from the previous verified package and must preserve prior functionality.

## Project baseline
- Original tracked baseline: V90.dt (schema 195).
- Manufacturing entity X and marketing/sales entity Y remain separate companies with intercompany processing.
- The release history in this package is the source-of-truth implementation trail.

## Current operational/production track
| Release | Milestone | State |
|---|---|---|
| V90.fm | Intercompany X/Y execution + consolidated elimination | Completed |
| V90.fn | Security/RBAC + organization/entity isolation hardening | Completed |
| V90.fo | ERP-wide audit, approval & evidence control | Completed |
| V90.fp | ERP-wide transaction governance integration | Completed |
| V90.fq | Critical-action governance certification | Completed |
| V90.fr | Governance coverage remediation | Completed |
| V90.fs | Governance remediation execution & UAT evidence | Completed |
| V90.ft | ERP UAT & production readiness | Completed |
| V90.fv | Deployment execution, rollback drill & cutover evidence | Completed |
| V90.fw | Backup, restore & DR validation | Completed |
| V90.fx | Observability, health monitoring & alerting | Completed |
| V90.fy | Performance engineering & scalability controls | Completed |
| V90.fz | Performance optimization & capacity remediation | Completed |
| V90.ga | Performance certification / production performance gate | Completed |
| V90.gb | Production-readiness performance integration | Completed |
| V90.gc | Production release certification & cutover integration | Completed |
| V90.gd | Go-live execution & final business sign-off | Completed |
| V90.ge | Post-go-live stabilization & final acceptance | Completed |
| V90.gf | Final go-live closure & operational handover | Completed |
| V90.gg | Operational handover, hypercare & closure certification | Completed |
| V90.gh | Continuous operations governance & SLA management | Completed |
| **V90.gi** | **Incident, Problem & Escalation Management** | **Current** |

## V90.gh change map
- `app/v90gh_operations_sla.py` — SLA policy, breach, review and dashboard API/UI control layer.
- `migrations/259_v90gh_continuous_operations_sla.sql` — schema 259 migration.
- `web/operations_sla.html` — operational SLA UI entry page.
- `tests/test_v90gh_operations_sla.py` — focused lifecycle and control tests.
- `app/v90gi_incident_problem_escalation.py` — problem, link, escalation and governance dashboard API/UI control layer.
- `migrations/260_v90gi_incident_problem_escalation.sql` — schema 260 migration.
- `web/incident_problem_escalation.html` — incident/problem/escalation UI entry page.
- `tests/test_v90gi_incident_problem_escalation.py` — focused problem and escalation tests.
- `config/release_manifest.json` — current release v90.gh / schema 259.
- `config/current_release_manifest.json` — current package pointer.
- `config/migration_manifest.json` — migration 259 with checksum.

## Validation state
- Focused V90.gh + adjacent operational/go-live regression: PASS.
- Full cumulative suite: 520 passed, 1 known pre-existing failure, 28 warnings.
- Known failure: `tests/test_v90db_machine_oee.py::test_machine_oee_calculation`; expected availability 75.0%, actual 0.0%.
- Python compilation: PASS.
- CI repository gate: PASS.
- Checksum verification: PASS.
- PostgreSQL migration smoke: not run without a live `DATABASE_URL`.
- Remote GitHub CI and real production deployment: not claimed unless separately executed.

## Troubleshooting rule
For a defect, first identify the release where the affected workflow was introduced or last changed. Reproduce against that release's tests and migration, then verify the latest cumulative release. Do not silently rewrite historical release behavior to hide a regression.

## Next logical ERP milestone
**V90.gj — Advanced ERP MIS & Management Dashboard**

This should consolidate the ERP transaction, production, procurement, inventory, sales, finance, workforce, maintenance, quality and intercompany domains into management-ready KPIs, drilldowns, exception views and exportable MIS without duplicating existing operational screens.

## Broader business roadmap after ERP completion
ERP completion is not the end of the overall Namkeen business build. After the ERP completion audit, continue to:
1. Company/business website.
2. Consumer brand identity and logo creation.
3. Namkeen/Farsan product packaging system and label artwork.
4. Product/brand marketing assets and launch collateral.
