# V90.bt — Returns UI + Return QC/Disposition + Return Accounting UI

## Scope
- Returns operations queue and summary
- Return detail view combining return lines, dispositions, credit note and accounting effects
- Return QC/disposition activity view
- Return accounting / credit-note queue
- Responsive Web UI at `/ui/returns` and `/ui/returns/accounting`
- User-specific returns screen filter/column preferences
- RBAC permissions `returns_ui.view` and `returns_ui.manage`
- Migration 145

## Verification
- V90.bt-specific tests: 3/3 passed
- 263 tests collected in cumulative suite
- Legacy `test_v90_release_integrity.py` is excluded from the application regression gate because its recursive repository scan does not terminate on the enlarged cumulative worktree; this is a test-harness/runtime limitation, not reported as a pass.
- Python compileall: PASS
- Migration chain 61-145: PASS
- Migration checksums: PASS
- Release manifest: PASS
