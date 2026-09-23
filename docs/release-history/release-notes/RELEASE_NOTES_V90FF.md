# V90.ff — Reliability Executive Action & Decision Control

Schema target: 232

Adds a controlled executive action queue derived from V90.fe reliability command exceptions. Management can generate actions, approve/reject/defer decisions, assign owners and due dates, record completion evidence, and close action periods. No maintenance plan, production, inventory, or other operational record is mutated automatically.

Routes:
- POST `/v90ff/maintenance/reliability-actions/generate`
- GET `/v90ff/maintenance/reliability-actions`
- POST `/v90ff/maintenance/reliability-actions/{action_id}/decide`
- POST `/v90ff/maintenance/reliability-actions/{action_id}/complete`
- POST `/v90ff/maintenance/reliability-actions/{period_key}/close`
- GET `/ui/maintenance-reliability-actions`
