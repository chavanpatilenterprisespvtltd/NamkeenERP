# V90.fn — Security / RBAC + Organization & Entity Isolation Hardening

Schema target: **240**

V90.fn hardens the existing identity, role/permission and entity/location/warehouse scope architecture rather than introducing a parallel authorization model.

## Delivered
- Persisted organization-level user access control.
- Unified security-scope evaluation for organization → entity → location → warehouse.
- Cross-organization and hierarchy-mismatch rejection.
- Security scope grant/revoke APIs with audit records.
- RBAC/security context API exposing roles, permissions and effective scope.
- User-scope inspection and security scope audit API.
- Persisted-session hardening: disabled users and missing persisted sessions are rejected by the V90.fn validator.
- RBAC/scope management permissions.
- Security/RBAC UI control surface.
- Existing V90.fm and earlier business workflows remain cumulative; no automatic operational mutation is introduced.

## Validation notes
- Functional tests cover organization isolation, scope propagation, persisted-session deactivation, and migration integrity.
- PostgreSQL migration execution requires an actual DATABASE_URL/PostgreSQL instance and is not claimable without one.
- Remote GitHub CI and production deployment are environment-dependent and are not claimed here unless actually executed.
