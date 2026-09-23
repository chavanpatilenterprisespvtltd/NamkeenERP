# V90.k — Supplier / Customer / Warehouse / Bin Operational Master Workflows

This checkpoint extends the V90.j structured-master workflow to core operational masters:
CUSTOMER, SUPPLIER, WAREHOUSE and BIN.

## Controls
- Role/permission + entity/location scope before read/write.
- Maker/checker approval remains the persistence gate.
- Customer/supplier common-field validation: code, name, phone, GSTIN, credit/payment terms.
- Warehouse requires entity + location context and warehouse type.
- Bin requires a parent active WAREHOUSE in the same organization/entity scope.
- Deactivation requires an explicit reason.
- Existing versioning/history and optimistic-lock fields remain available.

## API
- `GET /v90k/operational-masters`
- `GET /v90k/operational-masters/{master_type}`
- `POST /v90k/operational-masters/{master_type}/changes`
- `GET /v90k/bin/{bin_id}/location`

## Design note
Physical organization locations are still held in the dedicated organization structure tables.
This checkpoint does not duplicate them into the generic master table.
