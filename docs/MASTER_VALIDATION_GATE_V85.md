# v85 — Master Validation Gate

## Purpose

v84 provided cross-field rules. v85 makes validation an actual gate in the master-data workflow.

Flow:

`Structured UI / Bulk Import → v85 validation → Change Request → Approval → Re-validation → v77 persistent write`

## Blocking vs warning

- **BLOCKED**: one or more validator errors; request cannot enter `PENDING_APPROVAL`.
- **WARNING**: no blocking errors; request may enter approval, but warnings are preserved for the requester/approver.
- **PASS**: no blocking errors and no warnings.

## Approval re-validation

Approval re-runs validation against the current persisted master record. This catches changes made after a request was drafted and before approval. The existing v77 optimistic-lock check remains authoritative for version drift.

## Audit

Each validation run stores the payload snapshot, errors, warnings, validator version, actor, stage and outcome. Production migration `073_v85_master_validation_gate.sql` also stamps the change-request row with the latest validation status/reference.

## Safety boundary

Validation never directly writes a master record. Only the v77 persistent master transaction performs the authoritative CREATE/UPDATE/DEACTIVATE.
