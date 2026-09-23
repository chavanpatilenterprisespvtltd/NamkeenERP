# v79 — Bulk Master Import/Export

## Supported input
- CSV
- XLSX/XLSM

## Import columns
`action, master_type, master_id, entity_id, effective_from, effective_to, base_version_no, data_json`

The importer also supports a convenience mode where fields after the control columns are folded into `data_json`.

## Safety model
1. File is hashed (SHA-256).
2. Preview validates every row before any write.
3. Duplicate active keys within the file are rejected.
4. UUID, action, master type, effective dates and version fields are validated.
5. UPDATE/DEACTIVATE require `master_id`.
6. Effective-dated masters require `effective_from`.
7. Deactivation requires a reason.
8. Submit creates the existing audited master-change requests; it does not bypass approval.
9. Version checks remain enforced by v77 optimistic locking when approved.
10. Each row receives an idempotent client event derived from batch+row.

## Rollback
Bulk import is intentionally request-based. Before approval, no authoritative master is modified. After approval, changes use the same v77 transaction/audit pathway and are not silently undone. Corrections should be issued as new UPDATE/DEACTIVATE requests with audit history.

## Export
Exports contain master IDs, entity, type, version, active state, effective period and JSON data. Every export should create a `bulk_master_export_run` record and store the SHA-256/output reference.

## Template generation
`make_xlsx_template(master_type, path)` uses artifact_tool to create a simple XLSX template with an example row. The template is a starting point; customer-specific mandatory fields are validated by the master service during preview/approval.
