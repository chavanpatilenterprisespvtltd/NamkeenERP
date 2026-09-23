# V90.bi — GitHub Repository + CI/CD + Automated Migration/Test Pipeline

Adds a production-oriented GitHub repository structure and repeatable CI gates:
- GitHub Actions CI for cumulative tests, Python compilation, migration validation and artifact checksums.
- PostgreSQL 16 service in CI for migration smoke testing.
- Repository-level `scripts/ci_gate.py` preflight gate.
- `scripts/migration_smoke.py` applies the complete migration chain and asserts schema target 134.
- Migration 134 adds an auditable CI pipeline run registry for operational build history.
- Branch-safe workflow triggers for `main`/`develop`, pull requests, and manual dispatch.
