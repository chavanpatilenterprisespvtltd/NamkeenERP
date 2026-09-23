# V90.gs — Mobile/Offline Transaction Integration & Field Execution

Baseline: V90.gr / schema 268. Target: schema 269.

Adds an explicit integration and posting boundary for mobile/offline operational events. Supported transaction types are validated, deduplicated by source event, persisted with status and audited. Posting is intentionally a boundary record; existing ERP transaction systems remain the systems of record and are not duplicated.

Endpoints:
- POST `/v90gs/mobile/transactions/integrate`
- POST `/v90gs/mobile/transactions/{integration_id}/post`
- GET `/v90gs/mobile/transactions`
- UI `/ui/mobile-transaction-integration`
