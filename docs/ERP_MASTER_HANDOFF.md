# Namkeen ERP — Master Handoff / Candidate 1.0

## Current position

The cumulative ERP source baseline is **V90.gx / schema 279** (V90.gw-hotfix5 + Session CS2; see `docs/release-history/release-notes/RELEASE_NOTES_V90GX.md`). The next program is no longer arbitrary V90 feature expansion. The project is in the **Production Candidate 1.0 validation track**.

## Business scope already represented in the cumulative source

Manufacturing; procurement; GRN/QC; inventory; BOM/recipe; production planning/execution; process QC; batch output/yield/wastage; finished goods; packing; FEFO; sales orders; pricing/margins; incentives; credit/payment; dispatch/pick/POD; returns/disposition/accounting; collections/receivables/payables; bank reconciliation; costing/profitability; factory/sales MIS; GST/statutory; accounting; Tally boundary; MRP/replenishment/procurement controls; manufacturing scheduling/OEE/maintenance; HR/workforce/payroll; food quality/traceability/recall; barcode/QR; offline/mobile execution; RBAC/security/audit/approvals; backup/restore; observability; performance; deployment/go-live controls; intercompany; completion audit.

## Critical business structure

- Entity X = Manufacturing
- Entity Y = Marketing / Sales
- They may use different legal/trading names.
- Intercompany transactions/reconciliation must remain configuration-driven.
- X→Y price: decided by X and Y and recorded as a transfer-price policy (no default). Y = Chavan Patil Enterprises Pvt. Ltd.; X name to be set.

## Immediate work sequence

### Phase 1 — Consolidation (current)
- canonical source tree
- clean repository structure
- historical release genealogy retained
- migration continuity checked
- stale runtime artifacts removed
- environment templates aligned with V90.gw
- production candidate metadata and documentation

### Phase 2 — Environment validation
- PostgreSQL 16 staging instance
- migration smoke 61–279 (passed locally on PostgreSQL 16 in Session CS2; repeat on staging)
- checksum verification
- backup/restore drill
- security/RBAC boundary tests
- performance/load tests
- Android build and device validation

### Phase 3 — User acceptance testing
- role-by-role testing with demo accounts
- negative/permission testing
- full manufacturing-to-sales-to-accounting flow
- X → Y intercompany flow
- mobile offline/online flow
- traceability/recall
- GST/Tally boundary
- payroll/labour/profitability
- audit/approval/notification flows

### Phase 4 — Production readiness
- critical defects closed or explicitly dispositioned
- completion audit controls evidenced
- staging deployment/cutover/rollback drill
- business sign-off
- production deployment

### Phase 5 — Post-ERP program
After genuine ERP completion: Website → Brand/Logo → Packaging → Marketing.

## Known baseline issues that must remain visible

1. Historical OEE test defect: `tests/test_v90db_machine_oee.py::test_machine_oee_calculation` has previously observed an expected 75.0% availability versus 0.0% in the available test environment. Do not silently suppress or rewrite this history.
2. Historical V90.gp date/environment test issue: `test_v90gp_manufacturing_workforce_integration.py::test_dashboard_and_snapshot` previously expected a batch on a fixed date and observed none. Treat as historical until reproduced against staging data.
3. PostgreSQL (Session CS2): migrations 061–279, app start, bootstrap and login verified on PostgreSQL 16; pytest on PostgreSQL 381 passed / 196 failed (mostly older SQLite-only test fixtures) — next work item.
4. First admin in staging/production comes from `bootstrap/bootstrap.py`; demo logins are disabled outside development/test.

## Mandatory code-file documentation rule

For every future new or modified ERP code file, use the repository standard in `docs/development/CODE_CHANGE_DOCUMENTATION_STANDARD.md`. The first line is the full FILE PATH; the next line is the component version/session header; the current session changelog must state exact confirmation method/evidence, root cause, exact function/mechanism changed, and explicitly unaffected scope; older in-file changelogs are preserved; changed code gets a short `[Session N]` inline pointer; and every code fix is delivered as the complete file, ready to paste/overwrite in GitHub.

This convention exists specifically for fast troubleshooting. Do not retrofit every historical file just for formatting; apply it whenever a historical file is actually modified.

## Operating rule

When a meaningful validation milestone is completed, move to the next one automatically. Do not create arbitrary feature releases merely to continue version numbering.
