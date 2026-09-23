# V90.n — Inventory Operations Checkpoint

This is a cumulative maintenance checkpoint built from V90.m. It is **not** the end of the ERP project.

## Added
- Inventory reservations with open/released lifecycle and reference linkage.
- FEFO preview/allocation API using earliest expiry first and released/available lots only.
- Controlled inter-warehouse transfer draft/post workflow.
- Source-lot availability validation and destination lot creation preserving traceability to the original GRN/source lot.
- Transfer-out/transfer-in stock ledger entries and source/destination balance updates.
- Inventory reservation and transfer table structures plus PostgreSQL migration 087.

## Verification
- Full cumulative test suite: **83 passed, 0 failed**.
- Migration sequence extended to **087**.
- Release version: **v90.n**.

## Next checkpoint
The x-sequence continues after v90.n. The next planned checkpoint is **V90.o**; later checkpoints continue until the ERP project is actually complete and verified.
