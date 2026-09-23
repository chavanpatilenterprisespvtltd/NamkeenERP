# V90.bl — Management Dashboard + Approval Inbox + Notifications Center UI

- Management dashboard API with operational KPI summary.
- Approval inbox UI/API for pending workflow requests.
- Notifications center UI/API with per-user read state.
- Management console at `/ui/management`, with `/ui/approvals` and `/ui/notifications` entry routes.
- Role/permission enforcement for management UI.
- Migration 137: UI notification read-state table.
- Cumulative verification: 243 tests passed, 18 pre-existing warnings.
