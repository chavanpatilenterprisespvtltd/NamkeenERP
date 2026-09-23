# V90.fz — Performance Optimization Execution, Capacity Remediation & Scalability Certification

## Scope
V90.fz extends V90.fy from measurement/readiness into evidence-backed remediation execution and post-change scalability certification.

## Controls
- Performance optimization action lifecycle: PROPOSED → APPROVED → IN_PROGRESS → COMPLETED/BLOCKED/CANCELLED.
- Capacity remediation tracking with target state and evidence.
- Post-change optimization result records with latency, throughput and error-rate deltas.
- Certification gate requiring completed remediation, no open capacity remediations, passing post-change validation, and no failed post-change result.
- Period certification and close are evidence-backed and organization scoped.
- No external production performance test is claimed unless evidence is supplied.

## API/UI
- `/v90fz/performance/actions`
- `/v90fz/performance/capacity-remediations`
- `/v90fz/performance/optimization-results`
- `/v90fz/performance/certification-readiness`
- `/v90fz/performance/{period_key}/certify`
- `/v90fz/performance/{period_key}/close`
- `/ui/performance-optimization`

## Migration
`251_v90fz_performance_optimization.sql`
