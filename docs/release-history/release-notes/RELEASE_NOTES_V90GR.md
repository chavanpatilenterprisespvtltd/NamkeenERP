# V90.gr — Mobile & Offline Operational Execution

Baseline: V90.gq / schema 267
Target: schema 268

Adds mobile/offline execution sessions, ordered event ingestion, client-event idempotency, sequence gap/replay exception capture, session closure, scoped exception visibility, RBAC and a web command UI. Reuses existing V90.ba barcode/QR and V90.bb offline-sync foundations.

Validation: focused test 1 passed; compileall/checksum/CI gate passed. PostgreSQL smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available. Known pre-existing machine OEE defect remains unchanged.
