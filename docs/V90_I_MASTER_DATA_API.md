# V90.i — Master Data CRUD/API Integration

V90.i connects the persistent master-data model to the main ERP API surface while preserving the V90.g/h access controls.

## Implemented
- Master type discovery through the main ERP application.
- Scoped master-data list API.
- Master change requests for CREATE / UPDATE / DEACTIVATE.
- Approval queue and approval/rejection endpoints.
- Version/history endpoint.
- Entity scope enforcement on read/write operations.
- Existing approval, versioning and effective-date rules remain delegated to the persistent master service.
- Single-company and multi-company operation remain configuration-driven.

## APIs
- `GET /v90i/master-types`
- `GET /v90i/master-data/{master_type}`
- `POST /v90i/master-data/changes`
- `GET /v90i/approval-queue`
- `POST /v90i/approval-queue/{request_id}/approve`
- `POST /v90i/approval-queue/{request_id}/reject`
- `GET /v90i/master-data/{master_type}/{master_id}/history`

## Security
Every API operation requires the appropriate master permission. Entity-scoped requests are checked against the user's active entity grants. The API does not hard-code the user's legal structure or entity names.

## Verification
The full cumulative test suite is required to pass before release packaging.
