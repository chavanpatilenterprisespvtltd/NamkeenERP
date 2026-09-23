# v76 — Master Data API + UI

v76 exposes the v75 master-data approval model through an application-facing API and UI contract.

## Server APIs
- `GET /v76/master-data/{master_type}` search/filter
- `POST /v76/master-data/changes` create change request
- `POST /v76/master-data/changes/{request_id}/approve` approve
- `GET /v76/master-data/{master_type}/{master_id}/history` version history

## Controls
- organization/entity scope is server enforced
- self-approval blocked
- duplicate active masters rejected using configured natural-key fields
- effective-dated master types require `effective_from`
- deactivation requires reason
- update creates historical snapshot before mutation
- reporting/history endpoints are read-only
- mobile offline changes remain requests; server is authoritative

This v76 API uses an in-memory registry only for local contract tests. Production wiring must use PostgreSQL repositories and the v75 schema.
