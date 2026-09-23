# V90.ep — Predictive Maintenance / Failure-Risk Analytics

Schema target: 216. Builds cumulatively on V90.en maintenance strategy optimization.

## Delivered
- Monthly work-centre failure-risk snapshots from observed maintenance history.
- Breakdown growth, breakdown-hour growth, repeat-failure ratio and breakdown rate indicators.
- Risk score and risk level: LOW / MEDIUM / HIGH / CRITICAL.
- Risk-ranked management dashboard and ranking API.
- Historical risk trend API.
- Recommended operational actions and confidence indicator.
- Period close and RBAC permissions.
- Web UI at `/ui/maintenance-risk`.

## Guardrail
This release provides explainable operational risk indicators. It is not a machine-learning failure probability and does not automatically alter maintenance plans.
