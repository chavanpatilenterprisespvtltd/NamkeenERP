# v77 Master Data Persistence & Concurrency

## Transaction rules
1. Load and lock the change request.
2. Verify organization/entity scope.
3. Reject self-approval.
4. For update/deactivate, lock the master row.
5. Compare `base_version_no` with the current row version.
6. Snapshot the old state before mutation.
7. Validate active-key uniqueness and effective-date overlap.
8. Commit request decision and master mutation atomically.

## Concurrency
PostgreSQL uses row locking (`FOR UPDATE`) for approval paths. The active normalized-key uniqueness index provides database-level duplicate protection.

## Entity isolation
Callers should supply the entity IDs available to the current role/user. A request/list operation for an entity outside that set is rejected before mutation/read.

## Mobile retries
`client_event_id` is unique and idempotent. A retried identical change returns the original request ID instead of creating a duplicate request.
