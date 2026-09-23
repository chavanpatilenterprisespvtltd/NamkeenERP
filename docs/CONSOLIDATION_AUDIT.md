# Consolidation Audit — Production Candidate 1.0

## Source baseline

Input: `Namkeen_ERP_V90_GW_ERP_COMPLETION_AUDIT_RELEASE.zip`
Code baseline: V90.gw
Schema target: 273

## Completed in this consolidation

- [x] Latest V90.gw cumulative source extracted.
- [x] `app/`, `migrations/`, `web/`, `android/`, `tests/`, `scripts/`, `config/`, `deploy/`, `docker/`, `.github/` retained.
- [x] Historical release notes moved to `docs/release-history/release-notes/`.
- [x] Historical build verification records moved to `docs/release-history/build-verification/`.
- [x] Historical component checksum snapshots moved to `docs/release-history/component-checksums/`.
- [x] Historical V90 handoffs retained under `docs/release-history/`.
- [x] Legacy README checkpoints retained under `docs/legacy/`.
- [x] Runtime database files and caches removed from the candidate.
- [x] Environment templates aligned from stale V90.bh/V73 labels to V90.gw.
- [x] Docker Compose default APP_VERSION aligned to V90.gw.
- [x] Candidate metadata created.
- [x] Production/UAT/deployment documentation created.

## Migration continuity

The cumulative current tree contains migrations **061 through 273**, matching the current CI gate's required contiguous range and schema target.

## Source hygiene

The candidate must contain no real production secrets, `.env` files, local databases, Python bytecode or pytest cache. Example configuration files are templates only.

## Not yet certified

- Live PostgreSQL migration smoke test
- Real backup/restore drill
- Penetration/security testing
- Load/scalability execution
- Real Android device/offline network testing
- Full business UAT
- Production deployment
- Final business sign-off

## Consolidation principle

The latest cumulative source is authoritative. Historical releases are retained for genealogy/troubleshooting, not as competing source trees.

## Code-file troubleshooting standard added after consolidation

The Production Candidate now carries a mandatory self-documenting code-file standard under `docs/development/` and a reusable template under `templates/`. The standard requires path/version/evidence/root-cause/fix/unaffected-scope headers, preserved in-file history, inline session pointers, and complete-file delivery. Historical files are not mass-rewritten solely for formatting; the convention applies when a file is next modified.
