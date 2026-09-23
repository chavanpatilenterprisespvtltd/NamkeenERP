# v76 Master Data Admin UI Contract

Screens are backed by the v76 API and must enforce role/entity scope from the server:

1. Master list: search, active/inactive filter, entity/organization filter, pagination.
2. Master editor: create/update/deactivate; duplicate preview; effective dates where required.
3. Approval queue: pending requests, request payload diff, requester, approve/reject, reason.
4. History: version timeline, before/after snapshots, actor and timestamp.
5. Scope assignment: entity/warehouse/territory assignment where applicable.
6. Audit viewer: request + approval event history.

Offline creation can be queued with `client_event_id`, but activation/approval and effective-date conflicts are server authoritative.
