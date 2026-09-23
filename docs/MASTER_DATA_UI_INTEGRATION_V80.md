# v80 — Master Data UI Integration

## Scope
Persistent v77 master-data repository exposed to a lightweight Web UI and Android contract.

## UI flows
1. List/search/filter master records.
2. Open history.
3. Create/update/deactivate via change request.
4. Review approval queue and approve/reject.
5. Bulk import preview remains validation-only until the existing audited v79 workflow is invoked.

## Controls
- Organization and entity scope.
- Optimistic locking (`base_version_no`).
- Effective-date validation.
- Self-approval prevention.
- Audit snapshots.
- No direct client-side writes to master tables.

## Production note
The included UI is a functional reference/admin surface. Authentication, CSRF/CSP hardening, SSO/IdP integration and production reverse-proxy configuration are deployment requirements before exposing it beyond a trusted internal network.
