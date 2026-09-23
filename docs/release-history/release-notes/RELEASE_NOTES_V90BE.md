# V90.be — Audit Log Viewer + Corrective Transaction Workflow

- Central immutable audit log with before/after payloads, actor, reason, correlation and scope metadata.
- Audit query API supports organization/entity/location/object/action filters with bounded pagination.
- Corrective transaction requests are proposal-only until approved; original transactions are not overwritten.
- Duplicate active corrections for the same source transaction are blocked.
- Separate submit/view/approve permissions with entity/location scope checks.
- Requester cannot approve or reject their own correction; rejection requires a reason.
- Approved/rejected correction decisions are themselves audited.
- Migration 130 and release metadata added.
