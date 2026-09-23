# V90.fr — ERP Governance Coverage Remediation

## Schema
244

## Scope
V90.fr systematically scans the critical transactional governance surface established by V90.fq and identifies actionable coverage gaps instead of adding another independent governance framework.

## Included
- Critical-action coverage scan across procurement, receiving/QC, inventory, production, process QC, batch/packing, FG dispatch, sales, returns, return disposition, accounting and intercompany.
- Detection of missing governance policy, missing approval enforcement and uncertified critical actions.
- Persistent coverage-gap records with organization scope and lifecycle.
- Evidence-backed gap resolution.
- Coverage dashboard, gap list and scan history.
- Period-independent remediation records suitable for later UAT/certification.
- RBAC and V90.fn security-scope enforcement.
- UI: `/ui/governance-coverage-remediation`.

## Safety
The scan is diagnostic/remediation control only. It does not automatically alter transaction policies or operational data. Normal remediation requires an explicit administrator action with resolution evidence.

## Verification
- Focused governance/security tests: 17 passed.
- Full cumulative suite: 472 passed, 1 pre-existing unrelated V90.db machine-OEE failure, 27 warnings.
- Python compilation: PASS.
- CI repository gate: PASS.
- Artifact checksum verification: PASS (1009 files).
- PostgreSQL migration smoke: not successfully executed because no live `DATABASE_URL`/PostgreSQL instance was available.
- GitHub remote CI and production deployment: not performed.

Known unrelated regression: V90.db machine-OEE test expects 75.0% availability but receives 0.0%.
