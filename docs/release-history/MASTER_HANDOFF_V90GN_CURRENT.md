# Namkeen ERP — Current Master Handoff — V90.gn

## CURRENT RELEASE
- Release: **V90.gn — Advanced Sales & Distribution Performance**
- Schema: **264**
- Baseline: **V90.gl / schema 263**
- Migration: `264_v90gn_advanced_sales_distribution.sql`
- Baseline ZIP: `Namkeen_ERP_V90_GL_WORKING_CAPITAL_RELEASE.zip`

## COMPLETED
- Advanced sales/distribution performance API and snapshot layer.
- Customer / territory / salesperson / channel dimensions using existing governed customer master assignments.
- Repeat-customer, return-rate, collection-realization and average-order KPIs.
- Management action register with priority, owner and due date.
- RBAC + entity/location scope enforcement.
- Web cockpit: `/ui/sales-distribution`.
- Migration and release manifests advanced to schema 264.
- Historical tests that asserted the previous current release were advanced to validate the new current release while preserving historical artifacts.

## VALIDATION
- Focused V90.gn + V90.gl + V90.gk + V90.gj + V90.at + V90.au: **16 passed**.
- Cumulative regression excluding OEE: **532 passed, 28 warnings**.
- Known OEE regression: **1 failed, 1 passed**; `test_machine_oee_calculation` still observes 0.0% availability instead of 75.0%. This is preserved as a known pre-existing defect and was not altered/suppressed.
- Compileall: PASS.
- Checksum verification: PASS, 1114 artifacts.
- CI repository gate: PASS.
- PostgreSQL migration smoke test: **not run because no live DATABASE_URL/PostgreSQL instance is available.**
- GitHub remote CI: not run.
- Production deployment: not run.

## ARCHITECTURE RULES
- Preserve all prior releases and migration genealogy.
- Do not create competing customer ownership/territory models when existing governed portfolio/master assignments can be reused.
- Entity X = manufacturing and Entity Y = marketing/sales remain supported through existing multi-company/entity scope.
- Newer source/release ZIP wins over older handoff claims.
- Never fabricate hashes, migrations, DB smoke tests, CI, deployment, or test results.

## NEXT RELEASE
**V90.go — Advanced Customer & Distribution Execution / Route Performance** (or the next verified roadmap milestone after inspecting the source). Expected focus: route/beat efficiency, distributor/dealer secondary-sales visibility, customer retention/churn signals, service-level exceptions, and tighter execution analytics without duplicating existing field-sales foundations.

## REMAINING ROADMAP
Advanced sales/distribution → manufacturing/workforce integration → quality/traceability completion → mobile/offline/field hardening → technical hardening/UAT → final production readiness → Website → Brand/Logo → Packaging → Marketing.
