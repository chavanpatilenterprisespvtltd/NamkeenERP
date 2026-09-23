# V90.fx — Observability, Health Monitoring, Alerting & Operational SLA Controls

## Scope
Adds an evidence-backed operational monitoring and incident-control layer after V90.fw backup/DR validation.

## Capabilities
- Operational health/readiness checks with PASS/FAIL/BLOCKED/WAIVED outcomes.
- Metric and threshold capture for SLA evidence.
- Alert creation with LOW/MEDIUM/HIGH/CRITICAL severity.
- Incident lifecycle: OPEN → ACKNOWLEDGED → RESOLVED → CLOSED.
- Resolution evidence required before RESOLVED/CLOSED.
- Operational dashboard with health state, open alerts, critical alerts and open incidents.
- Period close gate requiring all catalogued operational checks to be PASS/WAIVED and no critical open alerts or unresolved incidents.
- Organization-scoped security enforcement through V90.fn.
- Web UI at `/ui/observability`.

## Safety / Verification boundary
This release records and governs operational evidence; it does not claim that external monitoring infrastructure, notification providers, production infrastructure or a live PostgreSQL environment were actually exercised. Those require deployment-specific connectivity.
