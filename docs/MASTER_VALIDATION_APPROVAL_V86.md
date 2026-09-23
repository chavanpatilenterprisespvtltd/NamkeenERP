# v86 — PostgreSQL Master Validation / Approval Persistence

## Purpose
v86 makes master validation part of the persistent approval workflow rather than a side record.

## Request path
1. Lock/load the current target master for UPDATE/DEACTIVATE.
2. Run v84 cross-field validation.
3. Persist the master change request and its validation run in one DB transaction.
4. Persist validation_status, validation_id, validator version and timestamp on the request.
5. BLOCKED requests never enter the approval queue.

## Approval path
1. Lock the change request.
2. Lock the target master when applicable.
3. Re-run validation against current persisted state.
4. Re-run optimistic-lock, duplicate-key and effective-date checks.
5. Apply audit snapshot + master mutation + final validation stamp + request status in one transaction.
6. Commit or roll back everything together.

## Atomicity invariant
There must not be a state where the master is changed but the approval's final validation record is absent, nor a state where approval is marked successful while the master mutation rolled back.

## UI queue guidance
Show validation_status directly on the approval queue. WARNING is reviewable; BLOCKED should never appear as an approvable request.
