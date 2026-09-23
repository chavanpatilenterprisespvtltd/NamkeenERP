# V90.av — Scheme Management + Discount Settlement + Incentive Settlement

## Scope
- Commercial scheme master with effective dates and scheme types.
- Percent/fixed discount settlement with minimum base and settlement caps.
- Duplicate settlement-reference protection.
- Salesperson incentive settlement from accrued incentives.
- Incentive reversal deduction from prior return accounting.
- Entity/location scoped authorization and audit fields.
- PostgreSQL migration 121.

## Verification
- Cumulative tests: 186 passed, 0 failed.
- Migration range: 061 through 121 contiguous.
- Migration 121 SHA-256 is recorded in `config/migration_manifest.json`.
- Python compilation and ZIP integrity verified during release packaging.
- No local SQLite database or Python bytecode artifacts included.
