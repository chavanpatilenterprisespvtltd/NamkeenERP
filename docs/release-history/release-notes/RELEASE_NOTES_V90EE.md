# V90.ee — Factory Scenario Comparison + Approved Scenario Handoff

## Release
- Version: V90.ee
- Schema target: 206
- Builds cumulatively on V90.ed / migration 205.

## Scope
Adds the management control loop after V90.ed scenario simulation:

- compare two or more factory bottleneck scenarios
- configurable comparison weights for bottleneck relief, residual load and overtime
- ranked scenario score and recommended scenario
- persistent comparison snapshots
- approval/rejection workflow
- one approved scenario per organization/entity/period guard
- approved-scenario handoff into a manufacturing scheduling work queue
- per-work-centre handoff actions preserving the simulated adjustments
- idempotent handoff creation
- role-based permissions
- Web UI

## Safety / execution boundary
The handoff does not silently mutate production schedules. It creates an auditable `MANUFACTURING_SCHEDULING` work queue with per-work-centre actions for the existing scheduling module to consume through a controlled workflow.

## Migration
`206_v90ee_factory_scenario_handoff.sql`
