# V90.fi — Reliability Executive Governance Effectiveness

Schema target: 235

V90.fi adds evidence-based effectiveness measurement for executive reliability governance. It tracks escalation resolution, overdue escalations, evidence completeness, executive action completion, effectiveness outcomes, governance-effectiveness score, controlled reviews, and period closure.

All metrics are observational control metrics. The release does not claim causal attribution and does not automatically mutate maintenance plans or operational records.

## Routes
- POST `/v90fi/maintenance/reliability-governance-effectiveness/snapshot`
- GET `/v90fi/maintenance/reliability-governance-effectiveness/dashboard`
- POST `/v90fi/maintenance/reliability-governance-effectiveness/reviews`
- POST `/v90fi/maintenance/reliability-governance-effectiveness/reviews/{review_id}/resolve`
- POST `/v90fi/maintenance/reliability-governance-effectiveness/{period_key}/close`
- GET `/ui/maintenance-reliability-governance-effectiveness`
