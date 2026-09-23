# V90.ao — Integration + UAT + Final Verification

V90.ao is the consolidated end-to-end verification milestone for the ERP flow built through V90.an.

## Scope
- End-to-end UAT run persistence
- Cross-module UAT checks for production → QC → FG → packing → sales → allocation → pick → dispatch → invoice
- Negative UAT validation when the invoice is missing
- Release-readiness verification endpoint
- Persisted UAT check results and release readiness checks
- Scope-aware permissions for UAT and release verification
- PostgreSQL migration 114
- Cumulative regression and release integrity validation

## APIs
- `POST /v90ao/uat/runs`
- `GET /v90ao/uat/runs/{uat_run_id}`
- `POST /v90ao/uat/runs/{uat_run_id}/release-readiness`

## Verification
- Cumulative pytest: 164 passed, 0 failed
- Python compileall: PASS
- Migration versions: 61–114 contiguous
- Migration checksum verification: PASS
- Release package integrity: PASS

This is the final **Integration + UAT + Final Verification workstream** package. It is not a claim that every future ERP roadmap item is complete.
