# V90.g — Access Scope & Warehouse Control

## Completed
- Entity-scoped user access.
- Location/site-scoped user access.
- First-class warehouse master linked to entity and location.
- Warehouse-scoped user access.
- Admin APIs for warehouse creation and access grants.
- `/auth/scope` returns the authenticated user's effective entity/location/warehouse scope.
- `/access/check/{scope_type}/{scope_id}` provides an explicit access check for downstream modules.
- PostgreSQL migration 080 with checksum-manifest registration.
- Release manifest advanced to v90.g / schema target 80.

## Design rule
Future transactional endpoints must enforce these scope helpers rather than trusting a client-supplied entity, location, or warehouse ID.

## Verification
Full cumulative regression suite: 66/66 tests passed.
