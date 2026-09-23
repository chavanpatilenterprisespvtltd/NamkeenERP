# NAMKEEN ERP — Production Candidate 1.0

This is the **canonical consolidated ERP source tree** for the Namkeen/Farsan Manufacturing ERP + MIS program.

## Identity

- Product: **Namkeen ERP**
- Production Candidate: **1.0**
- Cumulative code baseline: **V90.gw**
- Database schema target: **273**
- Architecture: Python/FastAPI + PostgreSQL + Web UI + Android foundation
- Business model: multi-company/entity, including Manufacturing Entity X and Marketing/Sales Entity Y with intercompany support

## What this package is

This package consolidates the cumulative source that was present in the latest verified V90.gw release into one clean repository structure. Historical release notes, verification records, handoffs, and component checksum snapshots are retained under `docs/release-history/` rather than duplicated as competing source trees.

**Do not restart the ERP from an older release.** This repository is the working source of truth for Candidate 1.0 unless a newer signed/verified candidate is explicitly created.

## Current status

The functional ERP feature build has reached the V90.gw completion-audit gate. This package is now moving into **consolidation → environment validation → role-based UAT → end-to-end UAT → production readiness → deployment**.

It is **not yet certified as production-complete**. The latest release verification recorded focused tests, compilation, checksum verification and CI-gate success, while PostgreSQL migration smoke testing and production deployment were not run in that release environment.

## Repository layout

- `app/` — cumulative Python backend/API and ERP modules
- `migrations/` — ordered PostgreSQL migrations (61–273 in the current cumulative tree)
- `web/` — cumulative web UI
- `android/` — Android/mobile foundation and build configuration
- `tests/` — cumulative automated test suite
- `scripts/` — CI, migration smoke, backup/restore, deployment and validation utilities
- `config/` — release, migration and environment configuration
- `deploy/` — production Docker Compose/deployment configuration
- `docker/` — container definitions
- `.github/` — CI/CD workflows and repository governance
- `docs/` — architecture, testing, UAT, deployment and complete release genealogy

## Production path

1. Consolidated source validation
2. Git repository establishment
3. PostgreSQL staging migration smoke test
4. Security/RBAC and permission-boundary testing
5. Backup/restore and DR drill
6. Performance/load/scalability validation
7. Role-by-role functional UAT
8. Full business E2E UAT
9. Defect disposition and release-blocker closure
10. Staging/cutover/rollback drill
11. Final business sign-off
12. Production deployment
13. Domain/custom-domain configuration

GitHub is intended to be the source-control system. Vercel is being evaluated for the web/API deployment layer; the final topology must be validated against the actual FastAPI/PostgreSQL runtime before production use.

## Important rules

- Preserve migration numbers; never reuse a migration number.
- Preserve release genealogy; do not silently overwrite history.
- Do not commit production secrets.
- Use environment/secrets management for passwords, tokens, GST/Tally credentials and database credentials.
- Do not declare production readiness from static inspection alone.
- Do not turn every UAT preference into a feature release. Critical defects are fixed; UX/enhancement findings are tracked separately.

## Code-file troubleshooting standard

All future new or modified ERP code files follow the self-documenting file convention in `docs/development/CODE_CHANGE_DOCUMENTATION_STANDARD.md`: FILE PATH first line, component version header, evidence-based session changelog, root cause, exact fix and unaffected scope, preserved in-file history, inline session pointers, and complete-file delivery for GitHub paste/overwrite. This is intentionally embedded in the ERP repository so troubleshooting remains fast even when a developer opens only one file. Historical files are not rewritten solely to retrofit the convention; it applies when a file is actually modified.

## Primary documents

- `docs/ERP_MASTER_HANDOFF.md`
- `docs/CONSOLIDATION_AUDIT.md`
- `docs/RELEASE_GENEALOGY.md`
- `docs/testing/AUTOMATED_TESTING.md`
- `docs/uat/UAT_MASTER_PLAN.md`
- `docs/deployment/PRODUCTION_DEPLOYMENT.md`
- `docs/deployment/GITHUB_VERCEL_PLAN.md`
- `config/production_candidate.json`
- `docs/development/CODE_CHANGE_DOCUMENTATION_STANDARD.md`
- `docs/development/GITHUB_TROUBLESHOOTING_STANDARD.md`
- `templates/CODE_FILE_CHANGE_TEMPLATE.md`
