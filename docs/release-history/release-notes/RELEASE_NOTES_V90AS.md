# V90.as — Production KPI + Factory MIS + Management Reporting

Built cumulatively from V90.ar.

## Implemented
- Factory KPI endpoint with date/entity/location scope.
- Planned vs produced quantity and yield percentage.
- Wastage quantity.
- Production batch counts.
- Production QC release counts.
- Packing run counts and packed quantity.
- Dispatch quantity.
- Posted sales invoice value.
- Production cost and variance cost rollups.
- Persistent factory KPI snapshots for auditability.
- Snapshot listing with scope controls.
- PostgreSQL migration 118.
- Migration manifest/checksum updated.

## Verification
- Cumulative tests: 177 passed, 0 failed.
- Migration sequence: 61 through 118 contiguous.
- Migration checksum: verified.
- Python compilation: verified.
- ZIP integrity: verified before release.
