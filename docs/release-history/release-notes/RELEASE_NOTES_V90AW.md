# V90.aw — Returns Analytics + Damage/Expiry Analytics + Repack/Rework Accounting

Adds management analytics on the existing returns/disposition pipeline and an auditable repack/rework accounting job workflow for return quantities classified as REPACK or REWORK.

## APIs
- `GET /v90aw/returns/analytics`
- `GET /v90aw/returns/damage-expiry`
- `POST /v90aw/returns/analytics/snapshots`
- `GET /v90aw/returns/analytics/snapshots`
- `POST /v90aw/repack-rework/jobs`
- `POST /v90aw/repack-rework/jobs/{job_id}/complete`
- `GET /v90aw/repack-rework/jobs`

## Controls
- Entity/location scope enforced for all endpoints.
- Damage/expiry estimated cost uses the latest active kg product cost rate for the return SKU, with zero when no rate exists.
- Repack/rework input is limited to the remaining disposition quantity and reference numbers are unique per entity.
- Completion cannot produce more than the input quantity; loss and output unit cost are calculated and stored.
- Analytics snapshots are idempotent by organization/entity/location/period.
