# V90.h — Master Data Scoping

V90.h extends the V90.g access foundation into master-data operations.

## Implemented
- Entity and location scope checks are available for master-data reads/writes.
- `masters.view` is required for reads.
- `masters.edit` is required for writes.
- Explicit entity/location scope identifiers are checked against the user's active grants.
- Single-company and multi-company configurations remain supported.
- Existing `master_record.entity_id` is preserved; nullable `location_id` is added when the table already exists.
- A policy table records the default entity/location scoping policy.

## APIs
- `GET /masters/access-check?entity_id=&location_id=`
- `POST /masters/access-check` with `entity_id` and/or `location_id`

## Verification
`pytest -q` → **67 passed**.
