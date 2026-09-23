# V90.fe — Reliability Executive Command Center

Schema target: **231**

## Scope
- Consolidates reliability governance/control, maintenance reliability cost, OEE/downtime, change effectiveness, standard adoption, CAPA and audit compliance into an executive health view.
- Supports organization-wide cross-entity ranking while retaining entity-level drill-down.
- Generates controlled executive exceptions for open audit and benchmark exposure.
- Requires explicit evidence-backed exception resolution and controlled period closure.
- Executive health scoring is transparent and bounded to 0–100; it is advisory and not causal attribution.
- No automatic maintenance-plan, production, CAPA, standard, or other operational mutation is performed.

## API/UI
- `POST /v90fe/maintenance/reliability-command/snapshot`
- `GET /v90fe/maintenance/reliability-command/dashboard`
- `GET /v90fe/maintenance/reliability-command/exceptions`
- `POST /v90fe/maintenance/reliability-command/exceptions/{exception_id}/resolve`
- `POST /v90fe/maintenance/reliability-command/{period_key}/close`
- UI: `/ui/maintenance-reliability-command`

## Verification
- V90.e-series cumulative regression: 57 passed, 9 warnings.
- Python compilation: PASS.
- CI repository gate: PASS.
- Migration continuity through schema 231: PASS via CI gate.
- Checksum generation/verification: run for final package.
- PostgreSQL migration smoke: NOT RUN because no live `DATABASE_URL`/PostgreSQL instance is available in this environment.
- GitHub remote CI/push: NOT performed.
- Vercel production deployment: NOT performed.
