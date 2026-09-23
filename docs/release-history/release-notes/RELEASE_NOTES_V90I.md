# V90.i Release Notes — Master Data CRUD/API Integration

## Baseline
Built cumulatively from V90.h. Earlier V80–V90 and V90.a–V90.h assets remain in the package as historical checkpoints/components.

## Added
- Main ERP integration for persistent master-data APIs.
- Scoped master-data listing with entity authorization.
- CREATE / UPDATE / DEACTIVATE change request API.
- Approval queue plus approve/reject API.
- Master history API.
- Master type discovery.
- SQLite compatibility schema bootstrap for development/tests while PostgreSQL remains the production migration target.
- Migration checkpoint 082 with API-scope indexes.

## Security
- `masters.view` required for reads.
- `masters.edit` required for writes/approvals.
- Entity scope is checked against active user grants.
- Self-approval remains blocked by the persistent master service.
- X/Y are not hard-coded; entity IDs remain configuration data.

## Verification
`pytest -q` → **69 passed**.
