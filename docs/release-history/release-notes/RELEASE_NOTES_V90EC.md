# V90.ec — Advanced Factory Bottleneck Optimization + Capacity/Labour/OEE Planning

## Scope
- PostgreSQL migration 204.
- Builds on V90.eb bottleneck analytics and existing manufacturing scheduling/work-centre capacity, workforce capacity and labour availability forecasting.
- Calculates machine load, labour load, combined capacity pressure, excess capacity, overtime requirement and bottleneck status.
- Provides configurable capacity thresholds and auditable work-centre optimization snapshots.
- Adds role-based API/UI access and period close.

## Cumulative rule
- Migration 204 is appended after migration 203; no historical migration is rewritten.

## Verification
- Focused V90.ec regression and cumulative workforce/machine regression executed where possible.
- Python compilation, repository CI gate, migration continuity, checksum verification and ZIP integrity executed.
- PostgreSQL smoke test requires a live DATABASE_URL and is not reported when unavailable.
