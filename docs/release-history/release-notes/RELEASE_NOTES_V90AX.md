# V90.ax — Dispatch Reconciliation, Transporter, POD & Backorder Controls

Adds the post-pick dispatch control layer around the existing V90.ag dispatch execution records.

## APIs
- `POST /v90ax/transporters`
- `GET /v90ax/transporters`
- `POST /v90ax/dispatches/{dispatch_id}/assignment`
- `GET /v90ax/sales/orders/{sales_order_id}/reconciliation`
- `GET /v90ax/sales/orders/{sales_order_id}/backorders`
- `POST /v90ax/dispatches/{dispatch_id}/pod`
- `GET /v90ax/dispatches/{dispatch_id}/pod`

## Controls
- Entity/location scope is enforced on dispatch, reconciliation and POD transactions.
- Transporter master is unique by organization/entity/code.
- One active delivery assignment is maintained per dispatch.
- Reconciliation compares ordered versus posted dispatched quantities and derives backorder quantity line-by-line.
- Backorders are idempotently upserted and automatically closed when later reconciliation shows no balance.
- POD references/attachments are retained as auditable metadata; the ERP does not assume an external file store.
- E-way bill reference is carried on the delivery assignment for later statutory integration.
